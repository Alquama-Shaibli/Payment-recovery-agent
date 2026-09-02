"""
PaymentRecoveryAgent: Main decision-making engine
"""
import json
import numpy as np
import pickle
from datetime import datetime
from typing import Dict, Any, List, Tuple
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    MAX_RETRIES_PER_CARD, MAX_RETRIES_PER_NACH,
    SOFT_DECLINE_RETRY_THRESHOLD, CLASSIFIER_MODEL,
    RETRY_SCORER_MODEL, LABEL_ENCODERS,
    IMMEDIATE_RETRY_DELAY, SOFT_DECLINE_RETRY_DELAY, TECHNICAL_RETRY_DELAY
)
from src.feature_engineering import preprocess_transaction, load_encoders
import catboost as cb
import pandas as pd


class PaymentRecoveryAgent:
    """
    AI agent for payment recovery decisions.

    Process:
    1. Detect root cause (CatBoost classifier)
    2. Check compliance gates (RBI/NACHA rules)
    3. Decide recovery action (retry, escalate, reject)
    4. Execute (mock or real)
    5. Log for audit
    """

    def __init__(self, logger: Any) -> None:
        """
        Initialise agent and load trained models from disk.

        Args:
            logger: AuditLogger instance
        """
        self.logger = logger

        # Load CatBoost model
        self.classifier = cb.CatBoostClassifier()
        self.classifier.load_model(str(CLASSIFIER_MODEL))

        # Load Logistic Regression retry scorer
        self.retry_scorer = pickle.load(open(RETRY_SCORER_MODEL, 'rb'))

        # Load label encoders
        self.label_encoders = load_encoders()

        # Runtime statistics
        self.stats: Dict[str, int] = {
            'processed': 0,
            'recovered': 0,
            'escalated': 0,
            'rejected': 0
        }

    def process_transaction(self, txn: Dict) -> Dict:
        """
        Main agent logic: detect → diagnose → decide → execute → log.

        Args:
            txn: Transaction dict

        Returns:
            Decision dict with agent decision + outcome
        """
        decision: Dict[str, Any] = {
            'txn_id': txn['txn_id'],
            'timestamp': datetime.utcnow().isoformat(),
            'agent_decision': None,
            'root_cause': None,
            'confidence': 0.0,
            'recovery_action': None,
            'retry_delay_hours': None,
            'compliance_gates_applied': [],
            'success': False,
            'reason': ''
        }

        self.stats['processed'] += 1

        try:
            # Step 1: Detect root cause
            root_cause, confidence = self._detect_root_cause(txn)
            decision['root_cause'] = root_cause
            decision['confidence'] = float(confidence)

            # Step 2: Compliance gates
            gates_violated = self._check_compliance_gates(txn)
            decision['compliance_gates_applied'] = gates_violated

            if gates_violated:
                decision['agent_decision'] = 'escalate_human'
                decision['reason'] = f'Compliance gates: {", ".join(gates_violated)}'
                self.stats['escalated'] += 1
            else:
                # Step 3: Recovery decision
                decision = self._decide_recovery_action(txn, decision, root_cause)

                # Step 3b: Merchant-aware enrichment
                from src.merchant_strategies import apply_merchant_logic
                decision = apply_merchant_logic(txn, decision)

            # Step 4: Execute via real Razorpay API (falls back to mock if no credentials)
            if decision['agent_decision'] and 'retry' in decision['agent_decision']:
                success = self._retry_via_api(txn, decision)
                decision['success'] = success
                if success:
                    self.stats['recovered'] += 1
            else:
                if decision['agent_decision'] == 'escalate_human':
                    # Already counted above if compliance gate hit;
                    # count here for non-compliance escalations
                    if not gates_violated:
                        self.stats['escalated'] += 1
                else:
                    self.stats['rejected'] += 1

            # Step 5: Log
            self.logger.log(decision)

        except Exception as e:
            decision['agent_decision'] = 'error'
            decision['reason'] = str(e)
            self.logger.log(decision)

        return decision

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _detect_root_cause(self, txn: Dict) -> Tuple[str, float]:
        """
        Use CatBoost to detect root cause from transaction features.

        Args:
            txn: Raw transaction dict

        Returns:
            Tuple of (root_cause_string, confidence_score)
        """
        processed = preprocess_transaction(txn, self.label_encoders)

        feature_cols = ['amount', 'day_of_week', 'hour_of_day', 'is_payday',
                        'customer_retry_count', 'decline_code_encoded',
                        'payment_method_encoded', 'issuer_encoded']

        X = np.array([[float(processed.get(col, 0)) for col in feature_cols]])

        proba = self.classifier.predict_proba(X)[0]
        class_idx = int(np.argmax(proba))
        confidence = float(proba[class_idx])
        root_cause: str = self.label_encoders['target'].classes_[class_idx]

        return root_cause, confidence

    def _check_compliance_gates(self, txn: Dict) -> List[str]:
        """
        Check regulatory compliance constraints.

        Returns:
            List of violated gate names (empty list if all pass)
        """
        gates_violated: List[str] = []
        retry_count = int(txn.get('customer_retry_count', 0))
        payment_method = str(txn.get('payment_method', ''))

        # RBI NACH rule: max 1 retry per mandate
        if payment_method == 'nach' and retry_count >= MAX_RETRIES_PER_NACH:
            gates_violated.append(f'nach_max_{MAX_RETRIES_PER_NACH}_retry')

        # Card retry limit (RBI guideline)
        if payment_method == 'card' and retry_count >= MAX_RETRIES_PER_CARD:
            gates_violated.append(f'card_max_{MAX_RETRIES_PER_CARD}_retries')

        return gates_violated

    def _decide_recovery_action(self, txn: Dict, decision: Dict, root_cause: str) -> Dict:
        """
        Decide what to do: retry now, retry later, escalate, or reject.

        Args:
            txn: Transaction dict
            decision: Decision dict to update in-place
            root_cause: Detected root cause string

        Returns:
            Updated decision dict
        """
        if root_cause.startswith('hard'):
            # Hard declines: always escalate (expired card, fraud, etc.)
            decision['agent_decision'] = 'escalate_human'
            decision['reason'] = f'Hard decline: {root_cause} -> needs manual intervention'

        elif root_cause == 'soft_insufficient_funds':
            # Score retry likelihood via Logistic Regression
            X_retry = pd.DataFrame([{
                'amount': txn['amount'],
                'is_payday': txn['is_payday'],
                'customer_retry_count': txn['customer_retry_count'],
                'hour_of_day': txn['hour_of_day']
            }])
            retry_score = float(self.retry_scorer.predict_proba(X_retry)[0, 1])

            if retry_score > SOFT_DECLINE_RETRY_THRESHOLD:
                if txn['is_payday']:
                    decision['agent_decision'] = 'retry_immediate'
                    decision['retry_delay_hours'] = IMMEDIATE_RETRY_DELAY
                else:
                    decision['agent_decision'] = 'retry_scheduled'
                    decision['retry_delay_hours'] = SOFT_DECLINE_RETRY_DELAY
                decision['reason'] = f'Soft decline, retry confidence: {retry_score:.2%}'
            else:
                decision['agent_decision'] = 'escalate_human'
                decision['reason'] = f'Soft decline but low confidence ({retry_score:.2%}) -> escalate'

        elif root_cause == 'soft_issuer_hold':
            decision['agent_decision'] = 'retry_scheduled'
            decision['retry_delay_hours'] = SOFT_DECLINE_RETRY_DELAY
            decision['reason'] = 'Issuer hold -> retry in 48h'

        elif root_cause == 'technical_timeout':
            decision['agent_decision'] = 'retry_immediate'
            decision['retry_delay_hours'] = TECHNICAL_RETRY_DELAY
            decision['reason'] = 'Technical timeout -> safe immediate retry'

        else:
            decision['agent_decision'] = 'reject'
            decision['reason'] = f'No recovery strategy for {root_cause}'

        return decision

    def _retry_via_api(self, txn: Dict, decision: Dict) -> bool:
        """
        Call the actual Razorpay test API to execute the retry.

        If credentials are not configured, falls back to the calibrated
        success-probability simulation so the system is always runnable
        in demo / CI environments.

        Args:
            txn:      Transaction dict
            decision: Current decision dict (mutated with api_response)

        Returns:
            True if the retry was successful, False otherwise
        """
        from src.razorpay_integration import RazorpayTestClient

        client = RazorpayTestClient()

        # If credentials are absent, fall back to simulation
        if not client.key_id or not client.key_secret:
            return self._mock_retry(txn, decision)

        result = client.retry_payment(
            txn_id=txn['txn_id'],
            amount=int(txn.get('amount', 0)),
            customer_id=str(txn.get('customer_id', f"cust_{txn['txn_id']}")),
        )

        decision['api_response'] = result
        return result.get('success', False)

    def _mock_retry(self, txn: Dict, decision: Dict) -> bool:
        """
        Simulated retry used when real API credentials are not available.

        Success probability is calibrated per root cause type to reflect
        real-world Razorpay test gateway behaviour.

        Args:
            txn: Transaction dict
            decision: Current decision dict

        Returns:
            True if retry successful, False otherwise
        """
        root_cause = decision.get('root_cause', '')

        if root_cause == 'soft_insufficient_funds':
            # 70% success if payday, 40% if not
            success_rate = 0.70 if txn.get('is_payday') else 0.40
        elif root_cause == 'technical_timeout':
            # 85% success for technical errors on retry
            success_rate = 0.85
        elif root_cause == 'soft_issuer_hold':
            success_rate = 0.60
        else:
            success_rate = 0.50

        return bool(np.random.random() < success_rate)

    def get_stats(self) -> Dict[str, int]:
        """Return cumulative agent statistics."""
        return self.stats.copy()

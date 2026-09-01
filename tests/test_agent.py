"""
Unit tests for PaymentRecoveryAgent
"""
import sys
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestComplianceGates:
    """Test compliance gate logic without loading real models."""

    def _make_agent(self):
        """Build a PaymentRecoveryAgent with mocked models."""
        mock_logger = MagicMock()

        with patch('src.agent.cb.CatBoostClassifier') as MockCB, \
             patch('src.agent.pickle.load') as mock_pkl, \
             patch('src.agent.load_encoders') as mock_enc:

            # Mock CatBoost model
            mock_model = MagicMock()
            mock_model.predict_proba.return_value = np.array([[0.1, 0.8, 0.1]])
            MockCB.return_value = mock_model

            # Mock retry scorer
            mock_scorer = MagicMock()
            mock_scorer.predict_proba.return_value = np.array([[0.2, 0.8]])
            mock_pkl.return_value = mock_scorer

            # Mock label encoders
            from sklearn.preprocessing import LabelEncoder
            le = LabelEncoder()
            le.fit(['soft_insufficient_funds', 'hard_expired_card', 'technical_timeout'])
            mock_enc.return_value = {
                'decline_code': LabelEncoder().fit(['02', '06', 'timeout']),
                'payment_method': LabelEncoder().fit(['card', 'upi', 'nach']),
                'issuer': LabelEncoder().fit(['HDFC', 'ICICI']),
                'target': le,
            }

            from src.agent import PaymentRecoveryAgent
            agent = PaymentRecoveryAgent.__new__(PaymentRecoveryAgent)
            agent.logger = mock_logger
            agent.classifier = mock_model
            agent.retry_scorer = mock_scorer
            agent.label_encoders = mock_enc.return_value
            agent.stats = {'processed': 0, 'recovered': 0, 'escalated': 0, 'rejected': 0}
            return agent

    def _base_txn(self, **kwargs):
        txn = {
            'txn_id': 'TXN_TEST',
            'amount': 500.0,
            'decline_code': '02',
            'payment_method': 'card',
            'issuer': 'HDFC',
            'day_of_week': 0,
            'hour_of_day': 10,
            'is_payday': 0,
            'customer_retry_count': 0,
        }
        txn.update(kwargs)
        return txn

    def test_nach_retry_limit_triggers_gate(self):
        agent = self._make_agent()
        txn = self._base_txn(payment_method='nach', customer_retry_count=1)
        gates = agent._check_compliance_gates(txn)
        assert any('nach' in g for g in gates), "NACH gate should be triggered"

    def test_nach_below_limit_passes(self):
        agent = self._make_agent()
        txn = self._base_txn(payment_method='nach', customer_retry_count=0)
        gates = agent._check_compliance_gates(txn)
        assert gates == [], "NACH below limit should pass"

    def test_card_retry_limit_triggers_gate(self):
        agent = self._make_agent()
        txn = self._base_txn(payment_method='card', customer_retry_count=5)
        gates = agent._check_compliance_gates(txn)
        assert any('card' in g for g in gates), "Card gate should be triggered"

    def test_card_below_limit_passes(self):
        agent = self._make_agent()
        txn = self._base_txn(payment_method='card', customer_retry_count=4)
        gates = agent._check_compliance_gates(txn)
        assert gates == [], "Card below limit should pass"

    def test_upi_no_gate(self):
        agent = self._make_agent()
        txn = self._base_txn(payment_method='upi', customer_retry_count=99)
        gates = agent._check_compliance_gates(txn)
        assert gates == [], "UPI has no compliance gate in current rules"


class TestDecisionLogic:
    """Test recovery decision logic for each root cause."""

    def _agent_with_scorer(self, scorer_proba: float):
        mock_logger = MagicMock()

        with patch('src.agent.cb.CatBoostClassifier'), \
             patch('src.agent.pickle.load') as mock_pkl, \
             patch('src.agent.load_encoders') as mock_enc:

            mock_scorer = MagicMock()
            mock_scorer.predict_proba.return_value = np.array([[1 - scorer_proba, scorer_proba]])
            mock_pkl.return_value = mock_scorer
            mock_enc.return_value = {}

            from src.agent import PaymentRecoveryAgent
            agent = PaymentRecoveryAgent.__new__(PaymentRecoveryAgent)
            agent.logger = mock_logger
            agent.classifier = MagicMock()
            agent.retry_scorer = mock_scorer
            agent.label_encoders = {}
            agent.stats = {'processed': 0, 'recovered': 0, 'escalated': 0, 'rejected': 0}
            return agent

    def _decision_template(self):
        return {
            'txn_id': 'TXN_001', 'timestamp': '', 'agent_decision': None,
            'root_cause': None, 'confidence': 0.0, 'recovery_action': None,
            'retry_delay_hours': None, 'compliance_gates_applied': [],
            'success': False, 'reason': ''
        }

    def _base_txn(self, **kwargs):
        txn = {
            'txn_id': 'TXN_001', 'amount': 500.0, 'decline_code': '02',
            'payment_method': 'card', 'issuer': 'HDFC', 'day_of_week': 0,
            'hour_of_day': 10, 'is_payday': 1, 'customer_retry_count': 0,
        }
        txn.update(kwargs)
        return txn

    def test_hard_decline_always_escalates(self):
        agent = self._agent_with_scorer(0.9)
        txn = self._base_txn()
        decision = self._decision_template()
        result = agent._decide_recovery_action(txn, decision, 'hard_expired_card')
        assert result['agent_decision'] == 'escalate_human'

    def test_soft_insufficient_funds_high_score_payday_retries_immediately(self):
        agent = self._agent_with_scorer(0.9)
        txn = self._base_txn(is_payday=1)
        decision = self._decision_template()
        result = agent._decide_recovery_action(txn, decision, 'soft_insufficient_funds')
        assert result['agent_decision'] == 'retry_immediate'

    def test_soft_insufficient_funds_high_score_nonpayday_schedules(self):
        agent = self._agent_with_scorer(0.9)
        txn = self._base_txn(is_payday=0)
        decision = self._decision_template()
        result = agent._decide_recovery_action(txn, decision, 'soft_insufficient_funds')
        assert result['agent_decision'] == 'retry_scheduled'

    def test_soft_insufficient_funds_low_score_escalates(self):
        agent = self._agent_with_scorer(0.1)
        txn = self._base_txn(is_payday=1)
        decision = self._decision_template()
        result = agent._decide_recovery_action(txn, decision, 'soft_insufficient_funds')
        assert result['agent_decision'] == 'escalate_human'

    def test_technical_timeout_retries_immediately(self):
        agent = self._agent_with_scorer(0.5)
        txn = self._base_txn()
        decision = self._decision_template()
        result = agent._decide_recovery_action(txn, decision, 'technical_timeout')
        assert result['agent_decision'] == 'retry_immediate'

    def test_unknown_root_cause_rejects(self):
        agent = self._agent_with_scorer(0.5)
        txn = self._base_txn()
        decision = self._decision_template()
        result = agent._decide_recovery_action(txn, decision, 'technical_gateway_error')
        assert result['agent_decision'] == 'reject'

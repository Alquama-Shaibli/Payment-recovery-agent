"""
Advanced unit tests: real API integration, merchant strategies,
and end-to-end process_transaction flows.

Run with:
    pytest tests/test_agent_advanced.py -v
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _make_agent(classifier_class_idx: int = 0, scorer_proba: float = 0.90):
    """
    Build a PaymentRecoveryAgent with all external dependencies mocked.

    Args:
        classifier_class_idx: Which class the mock CatBoost classifier picks
        scorer_proba: Probability returned by the logistic-regression scorer
    """
    from sklearn.preprocessing import LabelEncoder

    # Build a label encoder whose class[classifier_class_idx] is what we want
    classes = [
        "soft_insufficient_funds",
        "soft_issuer_hold",
        "hard_expired_card",
        "hard_fraud_blocked",
        "technical_timeout",
    ]
    le_target = LabelEncoder()
    le_target.fit(classes)

    # CatBoost mock: put all probability mass on classifier_class_idx
    proba = np.zeros(len(classes))
    proba[classifier_class_idx] = 1.0
    mock_classifier = MagicMock()
    mock_classifier.predict_proba.return_value = np.array([proba])

    # Logistic scorer mock
    mock_scorer = MagicMock()
    mock_scorer.predict_proba.return_value = np.array([[1 - scorer_proba, scorer_proba]])

    mock_encoders = {
        "decline_code": LabelEncoder().fit(["02", "04", "06", "43", "05", "timeout"]),
        "payment_method": LabelEncoder().fit(["card", "upi", "nach"]),
        "issuer": LabelEncoder().fit(["HDFC", "ICICI", "SBI"]),
        "target": le_target,
    }

    from src.agent import PaymentRecoveryAgent

    agent = PaymentRecoveryAgent.__new__(PaymentRecoveryAgent)
    agent.logger = MagicMock()
    agent.classifier = mock_classifier
    agent.retry_scorer = mock_scorer
    agent.label_encoders = mock_encoders
    agent.stats = {"processed": 0, "recovered": 0, "escalated": 0, "rejected": 0}
    return agent


def _base_txn(**kwargs):
    txn = {
        "txn_id": "TEST_001",
        "amount": 1000,
        "decline_code": "02",
        "payment_method": "card",
        "issuer": "HDFC",
        "day_of_week": 4,
        "hour_of_day": 14,
        "is_payday": 1,
        "customer_retry_count": 0,
        "customer_id": "cust_test_001",
        "merchant_category": "ecommerce_retail",
    }
    txn.update(kwargs)
    return txn


# ===========================================================================
# 1. Agent decision logic (no real model loading)
# ===========================================================================

class TestAgentDecisionLogic:
    """End-to-end process_transaction tests with fully mocked models."""

    def test_agent_handles_soft_insufficient_funds(self):
        """Soft decline (code 02) on payday → retry decision."""
        from sklearn.preprocessing import LabelEncoder

        # LabelEncoder sorts alphabetically — find the real index for this class
        classes = [
            "hard_expired_card",
            "hard_fraud_blocked",
            "soft_insufficient_funds",
            "soft_issuer_hold",
            "technical_timeout",
        ]
        le_target = LabelEncoder().fit(classes)
        soft_idx = list(le_target.classes_).index("soft_insufficient_funds")

        agent = _make_agent(classifier_class_idx=soft_idx, scorer_proba=0.90)
        agent.label_encoders["target"] = le_target

        txn = _base_txn(
            txn_id="TEST_001",
            decline_code="02",
            amount=1000,
            is_payday=1,
            customer_retry_count=0,
            payment_method="card",
        )

        # _retry_via_api does a local import, so we patch the module where the
        # class is defined, not the agent module.
        with patch("src.razorpay_integration.RazorpayTestClient", autospec=True) as MockClient:
            instance = MockClient.return_value
            instance.key_id = ""          # trigger mock-fallback path
            instance.key_secret = ""
            decision = agent.process_transaction(txn)

        assert decision["root_cause"] == "soft_insufficient_funds", (
            f"Expected soft_insufficient_funds, got {decision['root_cause']}"
        )
        assert "retry" in decision["agent_decision"], (
            f"Expected a retry action, got {decision['agent_decision']}"
        )
        assert decision["compliance_gates_applied"] == [], (
            "No compliance gates should be triggered for retry_count=0"
        )

    def test_compliance_gate_max_retries(self):
        """Card retry limit (5) enforced → escalate_human."""
        agent = _make_agent(classifier_class_idx=0, scorer_proba=0.90)
        txn = _base_txn(
            txn_id="TEST_002",
            decline_code="02",
            amount=1000,
            is_payday=0,
            customer_retry_count=5,  # Already at RBI maximum
            payment_method="card",
        )

        decision = agent.process_transaction(txn)

        assert decision["agent_decision"] == "escalate_human", (
            f"Expected escalate_human when retry_count == MAX, got {decision['agent_decision']}"
        )
        assert "card_max_5_retries" in decision["compliance_gates_applied"], (
            f"Expected card gate in {decision['compliance_gates_applied']}"
        )

    def test_hard_decline_always_escalates(self):
        """Hard decline → escalate_human (regardless of scorer probability)."""
        from sklearn.preprocessing import LabelEncoder

        # Build an agent whose classifier always predicts 'hard_expired_card'.
        # LabelEncoder sorts alphabetically, so we need the real index.
        classes = [
            "hard_expired_card",
            "hard_fraud_blocked",
            "soft_insufficient_funds",
            "soft_issuer_hold",
            "technical_timeout",
        ]
        le_target = LabelEncoder().fit(classes)
        hard_idx = list(le_target.classes_).index("hard_expired_card")

        agent = _make_agent(classifier_class_idx=hard_idx)
        # Override the label encoder with our ordered one
        agent.label_encoders["target"] = le_target

        txn = _base_txn(decline_code="06")
        decision = agent.process_transaction(txn)

        assert decision["agent_decision"] == "escalate_human", (
            f"Expected escalate_human for hard decline, got {decision['agent_decision']}"
        )
        assert decision["root_cause"].startswith("hard"), (
            f"Expected root_cause starting with 'hard', got {decision['root_cause']}"
        )

    def test_technical_timeout_retries_immediately(self):
        """Technical timeout → retry_immediate with 0h delay."""
        from sklearn.preprocessing import LabelEncoder

        classes = [
            "hard_expired_card",
            "hard_fraud_blocked",
            "soft_insufficient_funds",
            "soft_issuer_hold",
            "technical_timeout",
        ]
        le_target = LabelEncoder().fit(classes)
        timeout_idx = list(le_target.classes_).index("technical_timeout")

        agent = _make_agent(classifier_class_idx=timeout_idx)
        agent.label_encoders["target"] = le_target

        txn = _base_txn(decline_code="timeout")

        # Patch at the source module — the import is inside _retry_via_api body
        with patch("src.razorpay_integration.RazorpayTestClient", autospec=True) as MockClient:
            instance = MockClient.return_value
            instance.key_id = ""
            instance.key_secret = ""
            decision = agent.process_transaction(txn)

        assert decision["agent_decision"] == "retry_immediate", (
            f"Expected retry_immediate, got {decision['agent_decision']}"
        )
        assert decision["root_cause"] == "technical_timeout"

    def test_nach_compliance_gate(self):
        """NACH mandate already retried once → nach gate fires."""
        agent = _make_agent(classifier_class_idx=0, scorer_proba=0.90)
        txn = _base_txn(payment_method="nach", customer_retry_count=1)

        decision = agent.process_transaction(txn)

        assert decision["agent_decision"] == "escalate_human"
        assert any("nach" in g for g in decision["compliance_gates_applied"])


# ===========================================================================
# 2. Merchant strategy
# ===========================================================================

class TestMerchantStrategy:
    """Unit tests for merchant_strategies module."""

    def test_saas_strategy_fields(self):
        """SaaS strategy has correct fields."""
        from src.merchant_strategies import get_merchant_strategy

        strategy = get_merchant_strategy("saas_subscription")

        assert strategy["name"] == "SaaS Subscription"
        assert strategy["success_rate_soft_decline"] == 0.75
        assert strategy["ideal_retry_delay_hours"] == 72
        assert strategy["max_retry_attempts"] == 5

    def test_b2b_strategy_fields(self):
        """B2B strategy recommends weekly (168h) delay."""
        from src.merchant_strategies import get_merchant_strategy

        strategy = get_merchant_strategy("b2b_invoice")

        assert strategy["ideal_retry_delay_hours"] == 168
        assert strategy["success_rate_soft_decline"] == 0.82

    def test_unknown_category_falls_back_to_ecommerce(self):
        """Unknown merchant category silently falls back to ecommerce_retail."""
        from src.merchant_strategies import get_merchant_strategy

        strategy = get_merchant_strategy("mystery_vertical")

        assert strategy["name"] == "E-commerce Retail"

    def test_apply_merchant_logic_annotates_decision(self):
        """apply_merchant_logic adds merchant_strategy key to decision."""
        from src.merchant_strategies import apply_merchant_logic

        txn = _base_txn(merchant_category="saas_subscription")
        decision = {
            "agent_decision": "retry_scheduled",
            "retry_delay_hours": 48,
        }

        enriched = apply_merchant_logic(txn, decision)

        assert enriched["merchant_strategy"] == "SaaS Subscription"
        assert "strategy_details" in enriched
        # SaaS ideal delay (72) > current (48), so delay should be overridden
        assert enriched["retry_delay_hours"] == 72
        assert enriched.get("retry_delay_source") == "merchant_strategy"

    def test_apply_merchant_logic_does_not_shorten_delay(self):
        """Merchant logic must not shrink a delay that is already longer."""
        from src.merchant_strategies import apply_merchant_logic

        txn = _base_txn(merchant_category="ecommerce_retail")  # ideal = 24h
        decision = {
            "agent_decision": "retry_scheduled",
            "retry_delay_hours": 96,  # already longer than 24h ideal
        }

        enriched = apply_merchant_logic(txn, decision)

        # Delay should NOT be shortened
        assert enriched["retry_delay_hours"] == 96


# ===========================================================================
# 3. Razorpay integration
# ===========================================================================

class TestRazorpayIntegration:
    """Unit tests for RazorpayTestClient."""

    def test_missing_credentials_returns_failure(self):
        """Client without credentials returns a structured failure dict."""
        from src.razorpay_integration import RazorpayTestClient

        with patch.dict("os.environ", {}, clear=True):
            client = RazorpayTestClient()
            result = client.retry_payment("TXN_001", 500, "cust_001")

        assert result["success"] is False
        assert "credentials" in result["error"].lower()

    def test_successful_api_call(self):
        """200 response is parsed into a clean success dict."""
        from src.razorpay_integration import RazorpayTestClient

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": "order_test_123",
            "status": "created",
            "amount": 50000,
        }

        with patch("src.razorpay_integration.requests.post", return_value=mock_response), \
             patch.dict("os.environ", {
                 "RAZORPAY_TEST_KEY_ID": "rzp_test_abc",
                 "RAZORPAY_TEST_KEY_SECRET": "secret_xyz",
             }):
            client = RazorpayTestClient()
            result = client.retry_payment("TXN_001", 500, "cust_001")

        assert result["success"] is True
        assert result["order_id"] == "order_test_123"
        assert result["status"] == "created"

    def test_api_error_returns_failure(self):
        """4xx/5xx response from Razorpay is caught and returned as failure."""
        from src.razorpay_integration import RazorpayTestClient

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = '{"error": {"description": "Bad Request"}}'

        with patch("src.razorpay_integration.requests.post", return_value=mock_response), \
             patch.dict("os.environ", {
                 "RAZORPAY_TEST_KEY_ID": "rzp_test_abc",
                 "RAZORPAY_TEST_KEY_SECRET": "secret_xyz",
             }):
            client = RazorpayTestClient()
            result = client.retry_payment("TXN_001", 500, "cust_001")

        assert result["success"] is False
        assert result["status_code"] == 400

    def test_timeout_returns_failure(self):
        """Connection timeout is caught and surfaced as a failure dict."""
        import requests as req
        from src.razorpay_integration import RazorpayTestClient

        with patch("src.razorpay_integration.requests.post", side_effect=req.Timeout), \
             patch.dict("os.environ", {
                 "RAZORPAY_TEST_KEY_ID": "rzp_test_abc",
                 "RAZORPAY_TEST_KEY_SECRET": "secret_xyz",
             }):
            client = RazorpayTestClient()
            result = client.retry_payment("TXN_001", 500, "cust_001")

        assert result["success"] is False
        # After the backoff refactor, _post_order exhausts all 3 attempts
        # and retry_payment surfaces the "unreachable" message.
        assert result["success"] is False
        assert "error" in result

    def test_amount_converted_to_paise(self):
        """Verify the amount sent to Razorpay is in paise (amount × 100)."""
        from src.razorpay_integration import RazorpayTestClient

        captured_payload = {}

        def fake_post(url, json=None, **kwargs):
            captured_payload.update(json or {})
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"id": "order_x", "status": "created"}
            return mock_resp

        with patch("src.razorpay_integration.requests.post", side_effect=fake_post), \
             patch.dict("os.environ", {
                 "RAZORPAY_TEST_KEY_ID": "rzp_test_abc",
                 "RAZORPAY_TEST_KEY_SECRET": "secret_xyz",
             }):
            client = RazorpayTestClient()
            client.retry_payment("TXN_001", 500, "cust_001")

        assert captured_payload["amount"] == 50000, (
            f"Expected 50000 paise, got {captured_payload['amount']}"
        )

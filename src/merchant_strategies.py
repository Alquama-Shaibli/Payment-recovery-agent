"""
Merchant-Aware Recovery Strategies
-------------------------------------
Different merchant categories have different optimal retry strategies.
This module maps merchant_category → recovery playbook.

Usage:
    from src.merchant_strategies import get_merchant_strategy, apply_merchant_logic

    strategy = get_merchant_strategy('saas_subscription')
    enriched_decision = apply_merchant_logic(txn, agent_decision)
"""
from typing import Dict, Any

# ---------------------------------------------------------------------------
# Strategy catalogue
# ---------------------------------------------------------------------------

MERCHANT_STRATEGIES: Dict[str, Dict[str, Any]] = {
    "saas_subscription": {
        "name": "SaaS Subscription",
        # Wait until after next salary credit before retrying
        "soft_decline_strategy": "retry_on_next_billing_cycle",
        "max_retry_attempts": 5,
        "ideal_retry_delay_hours": 72,        # ~3 days (post-payday window)
        "success_rate_soft_decline": 0.75,
        "success_rate_technical": 0.90,
        "expected_churn_reduction": "5-8%",
        "customer_communication": "email_before_retry",
        "notes": (
            "SaaS customers expect seamless renewals. "
            "Silent retry on the 3rd day post-billing maximises success "
            "without alerting the customer unnecessarily."
        ),
    },
    "ecommerce_retail": {
        "name": "E-commerce Retail",
        # Urgency: customer wants the item now
        "soft_decline_strategy": "retry_in_24h_urgent",
        "max_retry_attempts": 3,
        "ideal_retry_delay_hours": 24,
        "success_rate_soft_decline": 0.65,
        "success_rate_technical": 0.85,
        "expected_churn_reduction": "3-5%",
        "customer_communication": "sms_alert_with_payment_link",
        "notes": (
            "Cart abandonment risk is high. Retry within 24 h and send "
            "a payment link so the customer can complete the order quickly."
        ),
    },
    "b2b_invoice": {
        "name": "B2B Invoice",
        # B2B: align with accounting cycles (payday / EOM settlement)
        "soft_decline_strategy": "defer_to_next_payday",
        "max_retry_attempts": 7,
        "ideal_retry_delay_hours": 168,       # 7 days (weekly EOM cycle)
        "success_rate_soft_decline": 0.82,
        "success_rate_technical": 0.92,
        "expected_churn_reduction": "8-12%",
        "customer_communication": "email_with_invoice_reminder",
        "notes": (
            "B2B payments follow accounts-payable cycles. "
            "Weekly retry cadence aligned to end-of-week settlement "
            "has the highest success rate."
        ),
    },
    "utility_payments": {
        "name": "Utility Payments",
        "soft_decline_strategy": "retry_on_due_date",
        "max_retry_attempts": 4,
        "ideal_retry_delay_hours": 48,
        "success_rate_soft_decline": 0.70,
        "success_rate_technical": 0.88,
        "expected_churn_reduction": "4-6%",
        "customer_communication": "push_notification",
        "notes": (
            "Utility customers rarely churn but may face temporary shortfalls. "
            "48 h retry keeps them compliant without penalty."
        ),
    },
}

# Default fallback — used when merchant_category is unrecognised
_DEFAULT_CATEGORY = "ecommerce_retail"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_merchant_strategy(merchant_category: str) -> Dict[str, Any]:
    """
    Return the recovery strategy for a given merchant category.

    Args:
        merchant_category: One of 'saas_subscription', 'ecommerce_retail',
                           'b2b_invoice', 'utility_payments'.

    Returns:
        Strategy dict. Falls back to ecommerce_retail if unknown.
    """
    return MERCHANT_STRATEGIES.get(
        merchant_category,
        MERCHANT_STRATEGIES[_DEFAULT_CATEGORY],
    )


def apply_merchant_logic(txn: Dict[str, Any], agent_decision: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich an agent decision with merchant-specific strategy details.

    This does **not** override the core agent decision; it annotates it
    with the recommended merchant playbook for downstream execution.

    Args:
        txn:            Transaction dict (must include 'merchant_category')
        agent_decision: Decision dict produced by PaymentRecoveryAgent

    Returns:
        Enriched decision dict (mutated in-place and returned)
    """
    merchant_category = txn.get("merchant_category", _DEFAULT_CATEGORY)
    strategy = get_merchant_strategy(merchant_category)

    agent_decision["merchant_category"] = merchant_category
    agent_decision["merchant_strategy"] = strategy["name"]
    agent_decision["merchant_communication"] = strategy.get("customer_communication")

    # Override retry delay only if the strategy suggests a longer wait
    current_delay = agent_decision.get("retry_delay_hours") or 0
    ideal_delay = strategy["ideal_retry_delay_hours"]
    if ideal_delay > current_delay and "retry" in str(agent_decision.get("agent_decision", "")):
        agent_decision["retry_delay_hours"] = ideal_delay
        agent_decision["retry_delay_source"] = "merchant_strategy"

    # Surface expected outcomes
    agent_decision["strategy_details"] = {
        "strategy": strategy["soft_decline_strategy"],
        "max_retries": strategy["max_retry_attempts"],
        "ideal_retry_delay_hours": ideal_delay,
        "expected_success_rate": strategy.get("success_rate_soft_decline"),
        "expected_churn_reduction": strategy.get("expected_churn_reduction"),
        "notes": strategy.get("notes", ""),
    }

    return agent_decision


def list_supported_categories() -> list:
    """Return all supported merchant category keys."""
    return list(MERCHANT_STRATEGIES.keys())

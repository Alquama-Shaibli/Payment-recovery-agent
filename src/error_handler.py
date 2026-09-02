"""
Error Handler — Graceful degradation for payment recovery failures.
"""
from typing import Dict, Any


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class PaymentRecoveryException(Exception):
    """Base exception for payment recovery pipeline."""


class APIConnectionError(PaymentRecoveryException):
    """Razorpay API is unreachable or timed out."""


class ComplianceViolationError(PaymentRecoveryException):
    """A compliance gate was violated programmatically (not via normal flow)."""


class ModelLoadError(PaymentRecoveryException):
    """A required ML model could not be loaded from disk."""


# ---------------------------------------------------------------------------
# Recovery handler
# ---------------------------------------------------------------------------

def handle_api_error(
    error: Exception,
    txn: Dict[str, Any],
    decision: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Gracefully degrade to human escalation when the Razorpay API call fails.

    Args:
        error:    The caught exception
        txn:      Transaction dict (for context)
        decision: Partial decision dict (mutated in-place)

    Returns:
        Updated decision dict with agent_decision='escalate_human'
    """
    error_type = type(error).__name__
    decision["error"] = str(error)
    decision["error_type"] = error_type
    decision["agent_decision"] = "escalate_human"
    decision["reason"] = f"API error [{error_type}] — escalated to human review"
    decision["success"] = False
    return decision


def handle_model_error(
    error: Exception,
    txn: Dict[str, Any],
    decision: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Degrade gracefully when the ML model fails to produce a prediction.
    Falls back to rule-based escalation using the raw decline code.
    """
    decision["error"] = str(error)
    decision["error_type"] = type(error).__name__

    decline_code = str(txn.get("decline_code", ""))
    if decline_code in ("06", "43", "05"):
        decision["root_cause"] = "hard_unknown"
        decision["agent_decision"] = "escalate_human"
        decision["reason"] = "Hard decline (model fallback) — escalate"
    else:
        decision["root_cause"] = "unknown"
        decision["agent_decision"] = "escalate_human"
        decision["reason"] = f"Model error [{type(error).__name__}] — safe escalation"

    decision["confidence"] = 0.0
    decision["success"] = False
    return decision

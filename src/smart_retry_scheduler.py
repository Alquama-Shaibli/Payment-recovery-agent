"""
Smart Retry Scheduler
-----------------------
Computes optimal payment retry timestamps using:
  - Indian bank payday calendar (1st and 15th of each month)
  - IST timezone context
  - Decline root cause (each type has a different optimal window)
  - Customer retry history (exponential back-off on repeated failures)

Usage:
    from src.smart_retry_scheduler import SmartRetryScheduler

    scheduler = SmartRetryScheduler()
    result = scheduler.calculate_optimal_retry_time(txn, 'soft_insufficient_funds')
    # -> {'retry_at': '2026-09-15T09:00:00', 'delay_seconds': ..., ...}
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# IST offset (UTC+5:30)
# ---------------------------------------------------------------------------
IST = timezone(timedelta(hours=5, minutes=30))

# ---------------------------------------------------------------------------
# Strategy parameters per root cause
# ---------------------------------------------------------------------------
_STRATEGY = {
    "soft_insufficient_funds": {
        "description": "Wait for next payday (salary credit)",
        "base_confidence": 0.85,
        "retry_hour_ist": 9,       # 9 AM IST — morning banking window
    },
    "soft_issuer_hold": {
        "description": "Issuer hold clears within 48 h",
        "fixed_delay_hours": 48,
        "base_confidence": 0.78,
        "retry_hour_ist": 10,
    },
    "technical_timeout": {
        "description": "Transient technical error — retry with exponential backoff",
        "base_delay_hours": 1,
        "base_confidence": 0.95,
        "retry_hour_ist": None,   # retry at current time + delay (no hour pinning)
    },
    "technical_gateway_error": {
        "description": "Gateway error — retry after short cooldown",
        "base_delay_hours": 2,
        "base_confidence": 0.88,
        "retry_hour_ist": None,
    },
}

# Indian paydays: 1st and 15th of every month
_PAYDAYS = (1, 15)


class SmartRetryScheduler:
    """
    Computes optimal retry timestamps for failed payment transactions.

    Decision logic:
      soft_insufficient_funds → next payday at 9 AM IST
      soft_issuer_hold        → fixed 48 h delay at 10 AM IST
      technical_*             → exponential backoff from now
      hard_*                  → no retry (escalate)
    """

    def calculate_optimal_retry_time(
        self,
        txn: Dict[str, Any],
        root_cause: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """
        Return the optimal retry schedule for a failed transaction.

        Args:
            txn:        Transaction dict (uses customer_retry_count)
            root_cause: Root cause string from the classifier
            now:        Override current time (defaults to now in IST)

        Returns:
            dict:
                retry_at       (ISO timestamp string or None)
                delay_seconds  (int or None)
                reason         (str)
                confidence     (float)
                strategy       (str)
        """
        now_ist = now or datetime.now(IST)
        retry_count = int(txn.get("customer_retry_count", 0))

        if root_cause == "soft_insufficient_funds":
            return self._schedule_payday_retry(now_ist)

        elif root_cause == "soft_issuer_hold":
            return self._schedule_fixed_delay(now_ist, hours=48, retry_hour=10,
                                              confidence=0.78,
                                              reason="Issuer hold — retry in 48 h at 10 AM IST")

        elif root_cause in ("technical_timeout", "technical_gateway_error"):
            return self._schedule_exponential_backoff(now_ist, retry_count, root_cause)

        else:
            # Hard declines — no retry
            return {
                "retry_at": None,
                "delay_seconds": None,
                "reason": f"No retry for {root_cause} — requires human escalation",
                "confidence": 1.0,
                "strategy": "escalate",
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _schedule_payday_retry(self, now_ist: datetime) -> Dict[str, Any]:
        """Schedule retry for the next Indian payday (1st or 15th) at 9 AM IST."""
        next_payday = self._next_payday(now_ist)
        retry_at = next_payday.replace(
            hour=_STRATEGY["soft_insufficient_funds"]["retry_hour_ist"],
            minute=0, second=0, microsecond=0
        )
        delay_seconds = int((retry_at - now_ist).total_seconds())

        # Clamp: don't schedule a retry in the past (edge case: it IS payday now)
        if delay_seconds <= 0:
            retry_at = now_ist + timedelta(minutes=30)
            delay_seconds = 1800

        return {
            "retry_at": retry_at.isoformat(),
            "delay_seconds": delay_seconds,
            "reason": f"Retry on payday ({retry_at.strftime('%d %b %Y')}) at 9 AM IST — salary credited",
            "confidence": _STRATEGY["soft_insufficient_funds"]["base_confidence"],
            "strategy": "payday_window",
        }

    def _schedule_fixed_delay(
        self,
        now_ist: datetime,
        hours: int,
        retry_hour: int,
        confidence: float,
        reason: str,
    ) -> Dict[str, Any]:
        """Schedule retry after a fixed delay, pinned to a specific hour of day."""
        raw_retry = now_ist + timedelta(hours=hours)
        # Pin to retry_hour on the same date (or next day if we've passed it)
        retry_at = raw_retry.replace(hour=retry_hour, minute=0, second=0, microsecond=0)
        if retry_at < raw_retry:
            retry_at += timedelta(days=1)

        delay_seconds = int((retry_at - now_ist).total_seconds())

        return {
            "retry_at": retry_at.isoformat(),
            "delay_seconds": delay_seconds,
            "reason": reason,
            "confidence": confidence,
            "strategy": "fixed_delay",
        }

    def _schedule_exponential_backoff(
        self, now_ist: datetime, retry_count: int, root_cause: str
    ) -> Dict[str, Any]:
        """
        Exponential backoff: delay = base_hours * 2^retry_count, capped at 24 h.
        """
        strategy = _STRATEGY.get(root_cause, _STRATEGY["technical_timeout"])
        base_hours = strategy.get("base_delay_hours", 1)
        delay_hours = min(base_hours * (2 ** retry_count), 24)  # cap at 24 h
        retry_at = now_ist + timedelta(hours=delay_hours)
        delay_seconds = int(timedelta(hours=delay_hours).total_seconds())

        return {
            "retry_at": retry_at.isoformat(),
            "delay_seconds": delay_seconds,
            "reason": (
                f"{strategy['description']} "
                f"(attempt #{retry_count + 1}, backoff={delay_hours:.1f}h)"
            ),
            "confidence": strategy["base_confidence"],
            "strategy": "exponential_backoff",
        }

    @staticmethod
    def _next_payday(now_ist: datetime) -> datetime:
        """
        Return the next Indian payday date (1st or 15th of month).

        If today IS a payday, returns today (caller pins the hour).
        Handles December → January rollover correctly.
        """
        day = now_ist.day
        month = now_ist.month
        year = now_ist.year

        for payday in _PAYDAYS:
            if day <= payday:
                return datetime(year, month, payday, tzinfo=IST)

        # Both paydays this month have passed — jump to 1st of next month
        if month == 12:
            return datetime(year + 1, 1, 1, tzinfo=IST)
        return datetime(year, month + 1, 1, tzinfo=IST)

"""
Enhanced Merchant Freeze Predictor
------------------------------------
Analyses an entire payment batch grouped by merchant category and
produces a structured risk report with:
  - Per-merchant freeze risk scores + risk levels
  - Threshold breach details (Razorpay's published limits)
  - Business-impact estimate
  - Saved JSON freeze alerts file

This is the *batch-level* predictor (complements the per-merchant
src/freeze_predictor.py which works on pre-aggregated metrics dicts).
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Razorpay published risk thresholds
# ---------------------------------------------------------------------------
_THRESHOLD_DECLINE_RATE    = 0.20   # >20% → review
_THRESHOLD_RETRY_EXHAUSTION = 0.30  # >30% → review
_THRESHOLD_VOLUME_SPIKE     = 1.50  # >1.5x baseline → review
_BASELINE_TXNS_PER_CATEGORY = 50    # assumed baseline per merchant group

# ---------------------------------------------------------------------------
# Freeze risk score threshold
# ---------------------------------------------------------------------------
_FREEZE_THRESHOLD = 0.65


def _train_model() -> RandomForestClassifier:
    """Train freeze-risk model on synthetic merchant data."""
    rng = np.random.default_rng(42)
    n = 500

    decline_rate       = rng.beta(2, 6, n)
    volume_spike       = rng.lognormal(0, 0.4, n)
    retry_exhaustion   = rng.beta(2, 5, n)
    settlement_delay_h = rng.exponential(24, n)
    chargeback_rate    = rng.beta(1, 30, n)

    X = np.column_stack([
        decline_rate,
        volume_spike,
        retry_exhaustion,
        settlement_delay_h / 168,
        chargeback_rate,
    ])
    y = (
        ((decline_rate > 0.20) & (volume_spike > 1.3)) |
        ((chargeback_rate > 0.01) & (retry_exhaustion > 0.25)) |
        (retry_exhaustion > 0.50)          # alone is high risk regardless
    ).astype(int)

    clf = RandomForestClassifier(n_estimators=100, max_depth=6,
                                  random_state=42, class_weight="balanced")
    clf.fit(X, y)
    return clf


class EnhancedMerchantFreezePredictor:
    """
    Batch-level account freeze predictor.

    Groups a transaction DataFrame by merchant_category, computes
    aggregate risk metrics per group, then scores each group with
    a RandomForest model trained on Razorpay risk heuristics.
    """

    def __init__(self) -> None:
        self.model = _train_model()
        logger.info("EnhancedMerchantFreezePredictor initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_batch_freeze_risk(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Analyse an entire transaction batch for merchant freeze risk.

        Args:
            df: Transaction DataFrame (must have columns:
                merchant_category, root_cause, customer_retry_count)

        Returns:
            dict with keys: timestamp, batch_analysis, summary, alerts,
            business_impact
        """
        merchants: Dict[str, Dict] = {}

        for category in sorted(df["merchant_category"].unique()):
            sub = df[df["merchant_category"] == category]
            profile = self._profile_merchant(category, sub)
            merchants[category] = profile

        # Aggregate summary
        def count_level(level):
            return sum(1 for m in merchants.values() if m["risk_level"] == level)

        alerts = [m for m in merchants.values()
                  if m["risk_level"] in ("CRITICAL", "HIGH")]

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "batch_analysis": merchants,
            "summary": {
                "critical_risk": count_level("CRITICAL"),
                "high_risk":     count_level("HIGH"),
                "medium_risk":   count_level("MEDIUM"),
                "low_risk":      count_level("LOW"),
                "total_merchants_analyzed": len(merchants),
            },
            "alerts": alerts,
            "business_impact": self._business_impact(alerts),
        }

    def save_alerts(
        self,
        analysis: Dict[str, Any],
        output_path: str | Path = "outputs/freeze_alerts.json",
    ) -> None:
        """Persist freeze risk analysis as JSON."""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(analysis, f, indent=2, default=str)
        logger.info("Freeze alerts saved to %s", output_path)

    def print_report(self, analysis: Dict[str, Any]) -> None:
        """Print a formatted freeze risk report to stdout."""
        merchants = list(analysis["batch_analysis"].values())
        s = analysis["summary"]

        print("\n[FREEZE RISK REPORT]")
        print("-" * 68)
        print(f"  {'Merchant':<24} {'Risk':<10} {'Score':>6}  Action")
        print(f"  {'-'*22}  {'-'*8}  {'-'*5}  {'-'*26}")

        for m in sorted(merchants, key=lambda x: -x["freeze_risk_score"]):
            mid    = m["merchant_id"][:24]
            level  = m["risk_level"]
            score  = m["freeze_risk_score"]
            action = m["recommendation"][:35]
            print(f"  {mid:<24} {level:<10} {score:>5.2f}  {action}")

        print("-" * 68)
        print(f"  Merchants analysed : {s['total_merchants_analyzed']}")
        print(f"  CRITICAL           : {s['critical_risk']}")
        print(f"  HIGH               : {s['high_risk']}")
        print(f"  MEDIUM             : {s['medium_risk']}")

        if analysis["alerts"]:
            print(f"\n  ALERT: {len(analysis['alerts'])} merchant(s) at elevated freeze risk!")
            for a in analysis["alerts"]:
                print(f"    -> [{a['risk_level']}] {a['merchant_id']}")
                print(f"       {a['recommendation']}")
                for breach in a["threshold_breaches"]:
                    print(f"       [BREACH] {breach}")

        bi = analysis["business_impact"]
        print(
            f"\n  Monthly revenue at risk : Rs {bi['estimated_monthly_revenue_at_risk_inr']:,}"
        )
        print(
            f"  Savings from early alert: Rs {bi['estimated_revenue_saved_inr']:,}"
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _profile_merchant(self, category: str, sub: pd.DataFrame) -> Dict[str, Any]:
        n = len(sub)

        hard_mask = sub["root_cause"].str.startswith("hard", na=False)
        soft_mask = sub["root_cause"].str.startswith("soft", na=False)

        hard_count   = int(hard_mask.sum())
        soft_count   = int(soft_mask.sum())
        tech_count   = n - hard_count - soft_count

        decline_rate      = hard_count / n if n else 0.0
        retry_exhaustion  = int((sub["customer_retry_count"] >= 4).sum()) / n if n else 0.0
        volume_spike      = n / _BASELINE_TXNS_PER_CATEGORY

        features = np.array([[
            decline_rate,
            volume_spike,
            retry_exhaustion,
            0.0,   # settlement_delay — not available at batch level
            0.0,   # chargeback_rate  — not available at batch level
        ]])
        score = float(self.model.predict_proba(features)[0, 1])

        # ── Risk level ────────────────────────────────────────────────
        if score >= 0.70:
            risk_level, emoji = "CRITICAL", "🔴"
        elif score >= 0.50:
            risk_level, emoji = "HIGH", "🟠"
        elif score >= 0.30:
            risk_level, emoji = "MEDIUM", "🟡"
        else:
            risk_level, emoji = "LOW", "🟢"

        # ── Threshold breaches ────────────────────────────────────────
        breaches = []
        if decline_rate > _THRESHOLD_DECLINE_RATE:
            breaches.append(
                f"decline_rate {decline_rate:.0%} > {_THRESHOLD_DECLINE_RATE:.0%} (Razorpay limit)"
            )
        if retry_exhaustion > _THRESHOLD_RETRY_EXHAUSTION:
            breaches.append(
                f"retry_exhaustion {retry_exhaustion:.0%} > {_THRESHOLD_RETRY_EXHAUSTION:.0%}"
            )
        if volume_spike > _THRESHOLD_VOLUME_SPIKE:
            breaches.append(
                f"volume_spike {volume_spike:.1f}x > {_THRESHOLD_VOLUME_SPIKE}x baseline"
            )

        merchant_id = f"merch_{category}_{int(score * 1000):03d}"

        return {
            "merchant_id": merchant_id,
            "merchant_category": category,
            "risk_level": risk_level,
            "freeze_risk_score": round(score, 4),
            "emoji": emoji,
            "metrics": {
                "total_transactions": n,
                "soft_declines": soft_count,
                "hard_declines": hard_count,
                "technical_errors": tech_count,
                "decline_rate": round(decline_rate, 4),
                "retry_exhaustion_rate": round(retry_exhaustion, 4),
                "volume_spike": round(volume_spike, 2),
            },
            "threshold_breaches": breaches,
            "breach_count": len(breaches),
            "recommendation": self._recommendation(score),
        }

    @staticmethod
    def _recommendation(score: float) -> str:
        if score >= 0.70:
            return "URGENT: Escalate to Razorpay compliance within 2 h"
        elif score >= 0.50:
            return "HIGH: Contact merchant + increase monitoring"
        elif score >= 0.30:
            return "MEDIUM: Monitor next 24 h, prepare recovery plan"
        return "LOW: Continue normal monitoring"

    @staticmethod
    def _business_impact(alerts: List[Dict]) -> Dict[str, Any]:
        """Rough financial-impact estimate for at-risk merchants."""
        critical = [a for a in alerts if a["risk_level"] == "CRITICAL"]
        # Assume ₹2,000 average txn × 10,000 txns/month per merchant
        avg_monthly = 2_000 * 10_000 / 12
        at_risk_inr    = len(critical) * avg_monthly
        saved_inr      = at_risk_inr * 0.60   # 60% recoverable with early action

        return {
            "critical_merchants_at_risk": len(critical),
            "estimated_monthly_revenue_at_risk_inr": int(at_risk_inr),
            "estimated_revenue_saved_inr": int(saved_inr),
            "action_window_hours": 24,
        }

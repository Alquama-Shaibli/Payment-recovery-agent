"""
Merchant Account Freeze Predictor
------------------------------------
Predicts which merchants are at risk of an account freeze
in the next 24 hours — Razorpay's #1 operational pain point.

A freeze is triggered when Razorpay's risk engine detects:
  - Sustained high decline rates
  - Sudden transaction volume spikes
  - Retry exhaustion (merchants burning through card limits)
  - Settlement inconsistencies / delayed payouts
  - Rising chargeback ratios

By predicting the freeze BEFORE Razorpay's system flags it,
merchants can take corrective action (contact support, reduce
volume, fix payment flow) proactively.

Usage:
    from src.freeze_predictor import MerchantFreezePredictor

    predictor = MerchantFreezePredictor()
    result = predictor.predict_freeze_risk({
        'decline_rate': 0.35,
        'volume_spike': 2.1,
        'retry_exhaustion': 0.45,
        'settlement_delay': 60,
        'chargeback_rate': 0.03
    })
"""
import logging
from typing import Dict, Any, List

import numpy as np
from sklearn.ensemble import RandomForestClassifier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Feature schema (order matters — must match training)
# ---------------------------------------------------------------------------
FEATURE_NAMES: List[str] = [
    "decline_rate",         # 0–1: fraction of payments declining
    "volume_spike",         # ratio vs 7-day rolling baseline (1.0 = normal)
    "retry_exhaustion",     # 0–1: fraction of txns hitting max retry limit
    "settlement_delay_norm",# settlement_delay_hours / 168 (normalised to 1 week)
    "chargeback_rate",      # 0–1: fraction of payments disputed
]

FREEZE_RISK_THRESHOLD = 0.65   # score above this → freeze imminent

# Razorpay's internal risk thresholds (approximate, from public docs)
_RAZORPAY_DECLINE_LIMIT = 0.30       # >30% decline rate triggers review
_RAZORPAY_CHARGEBACK_LIMIT = 0.01    # >1% chargeback rate triggers review


def _generate_training_data(n_samples: int = 500, seed: int = 42):
    """
    Generate realistic synthetic merchant metrics for training.

    Freeze label is 1 when:
      - decline_rate  > 0.30  AND volume_spike > 1.8, OR
      - chargeback_rate > 0.02 AND retry_exhaustion > 0.40
    """
    rng = np.random.default_rng(seed)

    decline_rate       = rng.beta(2, 6, n_samples)           # skewed low
    volume_spike       = rng.lognormal(0, 0.4, n_samples)    # centred around 1
    retry_exhaustion   = rng.beta(2, 5, n_samples)
    settlement_delay_h = rng.exponential(24, n_samples)      # hours
    chargeback_rate    = rng.beta(1, 30, n_samples)          # usually tiny

    X = np.column_stack([
        decline_rate,
        volume_spike,
        retry_exhaustion,
        settlement_delay_h / 168,          # normalise to 1-week window
        chargeback_rate,
    ])

    # Deterministic freeze label (mirrors Razorpay's rule heuristics)
    y = (
        ((decline_rate > 0.30) & (volume_spike > 1.8)) |
        ((chargeback_rate > 0.02) & (retry_exhaustion > 0.40))
    ).astype(int)

    return X, y


class MerchantFreezePredictor:
    """
    RandomForest model that predicts account freeze risk in the next 24 h.

    The model is trained on init using synthetic merchant-metric data whose
    labels are derived from Razorpay's publicly documented risk thresholds.
    No disk I/O is required — the model trains in < 1 s.
    """

    def __init__(self, n_estimators: int = 100, seed: int = 42) -> None:
        self.threshold = FREEZE_RISK_THRESHOLD
        self.model: RandomForestClassifier = RandomForestClassifier(
            n_estimators=n_estimators,
            max_depth=6,
            random_state=seed,
            class_weight="balanced",   # handles label imbalance
        )
        self._train()
        logger.info("MerchantFreezePredictor trained (n_estimators=%d)", n_estimators)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict_freeze_risk(self, merchant_metrics: Dict[str, float]) -> Dict[str, Any]:
        """
        Predict the probability that this merchant will be frozen in the next 24 h.

        Args:
            merchant_metrics: dict with keys:
                decline_rate       (float 0–1)
                volume_spike       (float, ratio vs baseline; 1.0 = normal)
                retry_exhaustion   (float 0–1)
                settlement_delay   (float, hours)
                chargeback_rate    (float 0–1)

        Returns:
            dict:
                freeze_risk_score  (float 0–1)
                will_freeze        (bool)
                risk_level         (str: LOW / MEDIUM / HIGH / CRITICAL)
                recommended_action (str)
                contributing_factors (list[str])
                razorpay_thresholds_breached (list[str])
        """
        features = self._extract_features(merchant_metrics)
        score = float(self.model.predict_proba(features)[0, 1])

        risk_level, action = self._classify_risk(score)
        factors = self._identify_factors(merchant_metrics)
        breaches = self._check_razorpay_thresholds(merchant_metrics)

        return {
            "freeze_risk_score": round(score, 4),
            "will_freeze": score >= self.threshold,
            "risk_level": risk_level,
            "recommended_action": action,
            "contributing_factors": factors,
            "razorpay_thresholds_breached": breaches,
        }

    def batch_predict(
        self, merchants: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Run prediction for a list of merchant metric dicts.

        Returns a list of result dicts sorted by freeze_risk_score descending.
        """
        results = []
        for m in merchants:
            result = self.predict_freeze_risk(m.get("metrics", m))
            result["merchant_id"] = m.get("merchant_id", "unknown")
            results.append(result)

        return sorted(results, key=lambda r: r["freeze_risk_score"], reverse=True)

    def get_feature_importances(self) -> Dict[str, float]:
        """Return feature importances from the trained RandomForest."""
        return dict(zip(FEATURE_NAMES, self.model.feature_importances_))

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _train(self) -> None:
        X, y = _generate_training_data()
        self.model.fit(X, y)

    def _extract_features(self, metrics: Dict[str, float]) -> np.ndarray:
        return np.array([[
            float(metrics.get("decline_rate", 0.0)),
            float(metrics.get("volume_spike", 1.0)),
            float(metrics.get("retry_exhaustion", 0.0)),
            float(metrics.get("settlement_delay", 0.0)) / 168.0,
            float(metrics.get("chargeback_rate", 0.0)),
        ]])

    @staticmethod
    def _classify_risk(score: float):
        if score < 0.25:
            return "LOW", "Monitor normally — no action required"
        elif score < 0.50:
            return "MEDIUM", "Review payment flow — consider pre-emptive support contact"
        elif score < 0.65:
            return "HIGH", "Alert merchant — request transaction volume reduction"
        else:
            return "CRITICAL", "URGENT: Escalate to Razorpay support immediately"

    @staticmethod
    def _identify_factors(metrics: Dict[str, float]) -> List[str]:
        """Human-readable list of what is driving the risk score."""
        factors = []
        if metrics.get("decline_rate", 0) > 0.25:
            factors.append(f"High decline rate ({metrics['decline_rate']:.0%})")
        if metrics.get("volume_spike", 1.0) > 1.5:
            factors.append(f"Volume spike detected ({metrics['volume_spike']:.1f}x baseline)")
        if metrics.get("retry_exhaustion", 0) > 0.35:
            factors.append(f"Retry exhaustion ({metrics['retry_exhaustion']:.0%} at limit)")
        if metrics.get("settlement_delay", 0) > 48:
            factors.append(f"Settlement delay ({metrics['settlement_delay']:.0f}h)")
        if metrics.get("chargeback_rate", 0) > 0.01:
            factors.append(f"Elevated chargebacks ({metrics['chargeback_rate']:.2%})")
        return factors or ["No single dominant factor — composite risk"]

    @staticmethod
    def _check_razorpay_thresholds(metrics: Dict[str, float]) -> List[str]:
        """Check against Razorpay's documented risk thresholds."""
        breaches = []
        if metrics.get("decline_rate", 0) > _RAZORPAY_DECLINE_LIMIT:
            breaches.append("decline_rate > 30% (Razorpay review threshold)")
        if metrics.get("chargeback_rate", 0) > _RAZORPAY_CHARGEBACK_LIMIT:
            breaches.append("chargeback_rate > 1% (Razorpay review threshold)")
        return breaches

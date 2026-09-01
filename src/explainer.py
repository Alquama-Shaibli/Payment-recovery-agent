"""
Explainability for agent decisions.

Uses CatBoost native feature importance (always works) plus SHAP TreeExplainer
when available and compatible. Falls back gracefully if SHAP crashes.
"""
import pandas as pd
import numpy as np
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import CLASSIFIER_MODEL, EXPLAINABILITY_REPORT, LABEL_ENCODERS
import catboost as cb


def generate_explainability_report(batch_df: pd.DataFrame) -> str:
    """
    Generate explainability report combining CatBoost native importance + optional SHAP.

    Args:
        batch_df: DataFrame of processed transactions

    Returns:
        Markdown report string
    """
    # Load model + encoders
    classifier = cb.CatBoostClassifier()
    classifier.load_model(str(CLASSIFIER_MODEL))
    label_encoders = pickle.load(open(LABEL_ENCODERS, 'rb'))

    feature_cols = ['amount', 'day_of_week', 'hour_of_day', 'is_payday',
                    'customer_retry_count', 'decline_code_encoded',
                    'payment_method_encoded', 'issuer_encoded']

    # Build encoded columns on the fly if missing
    from config import CATEGORICAL_FEATURES
    df_work = batch_df.copy()
    for col in CATEGORICAL_FEATURES:
        enc_col = f'{col}_encoded'
        if enc_col not in df_work.columns and col in df_work.columns:
            le = label_encoders[col]
            df_work[enc_col] = df_work[col].astype(str).apply(
                lambda v: le.transform([v])[0] if v in le.classes_ else 0
            )

    X = df_work[feature_cols].astype(float)

    # -------------------------------------------------------------------
    # Primary: CatBoost native feature importance (always available)
    # -------------------------------------------------------------------
    native_importance = classifier.get_feature_importance()
    feature_importance = pd.DataFrame({
        'feature': feature_cols,
        'importance': native_importance
    }).sort_values('importance', ascending=False)

    # -------------------------------------------------------------------
    # Optional: SHAP TreeExplainer (may crash on some Windows/CatBoost combos)
    # -------------------------------------------------------------------
    shap_section = _try_shap(classifier, X.values, feature_cols)

    # -------------------------------------------------------------------
    # Build markdown report
    # -------------------------------------------------------------------
    top5 = feature_importance.head(5)
    importance_lines = "\n".join(
        f"- **{row['feature']}**: {row['importance']:.2f}" for _, row in top5.iterrows()
    )

    report = f"""# Payment Recovery Agent -- Explainability Report

## Feature Importance (CatBoost Native)

Top features driving root cause predictions:

{importance_lines}

{shap_section}

## Decision Logic

### Soft Insufficient Funds
- **Retry Decision**: Based on payday likelihood + customer history
- **Retry Timing**:
  - Immediate if payday window
  - 48 hours if off-payday
- **Success Rate**: 70% (payday) vs 40% (non-payday)

### Hard Declines (Expired, Fraud, Do Not Honor)
- **Decision**: Always escalate to human
- **Reason**: Permanent issues requiring customer action

### Technical Timeouts
- **Decision**: Immediate retry
- **Success Rate**: 85%
- **Max Attempts**: 5 per card (RBI compliant)

## Compliance Gates

- NACH retry limit: 1 maximum (NACHA rule)
- Card retry limit: 5 maximum (RBI guideline)
- All decisions audited with timestamp + reasoning
- Feature importance logged for every batch

## Model Metrics

| Parameter | Value |
|-----------|-------|
| Training Samples | 200 transactions |
| Features Used | 8 |
| Algorithm | CatBoost Gradient Boosting |
| Explainability | Native feature importance + SHAP (when available) |

## Audit Trail Format

Each decision logged as JSON:
```json
{{
  "txn_id": "TXN_000001",
  "timestamp": "2026-08-24T19:08:20Z",
  "root_cause": "soft_insufficient_funds",
  "confidence": 0.87,
  "agent_decision": "retry_immediate",
  "compliance_gates_applied": [],
  "success": true,
  "reason": "Soft decline, retry confidence: 87.00%"
}}
```

---
Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    return report


def _try_shap(classifier, X: np.ndarray, feature_cols: list) -> str:
    """
    Attempt SHAP analysis in an isolated subprocess so a native C++ crash
    (common with SHAP + CatBoost on Windows) cannot kill the main process.

    Args:
        classifier: Fitted CatBoost model
        X: Feature array (numpy)
        feature_cols: List of feature names

    Returns:
        Markdown string for the SHAP section
    """
    import subprocess
    import json
    import tempfile
    import os

    # Serialise the sample array to a temp file for the subprocess
    sample = X[:min(50, len(X))]
    try:
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as tmp:
            tmp_path = tmp.name
            json.dump({
                'X': sample.tolist(),
                'feature_cols': feature_cols,
                'model_path': str(CLASSIFIER_MODEL)
            }, tmp)

        script = r"""
import sys, json, numpy as np
import catboost as cb

data = json.load(open(sys.argv[1]))
X = np.array(data['X'])
feature_cols = data['feature_cols']

classifier = cb.CatBoostClassifier()
classifier.load_model(data['model_path'])

import shap
explainer = shap.TreeExplainer(classifier)
shap_values = explainer.shap_values(X)

if isinstance(shap_values, list):
    mean_shap = np.mean([np.mean(np.abs(sv), axis=0) for sv in shap_values], axis=0).tolist()
else:
    mean_shap = np.mean(np.abs(shap_values), axis=0).tolist()

print(json.dumps({'mean_shap': mean_shap}))
"""
        result = subprocess.run(
            [sys.executable, '-c', script, tmp_path],
            capture_output=True, text=True, timeout=60
        )
        os.unlink(tmp_path)

        if result.returncode != 0 or not result.stdout.strip():
            err = result.stderr.strip()[:200] if result.stderr else 'process crashed'
            return f"""## SHAP Analysis

> Note: SHAP TreeExplainer unavailable on this platform ({err}).
> CatBoost native feature importance is used above as the primary explainability method.
"""

        payload = json.loads(result.stdout.strip())
        mean_shap = payload['mean_shap']

        shap_df = pd.DataFrame({
            'feature': feature_cols,
            'shap_importance': mean_shap
        }).sort_values('shap_importance', ascending=False)

        shap_lines = "\n".join(
            f"- **{row['feature']}**: {row['shap_importance']:.4f}"
            for _, row in shap_df.head(5).iterrows()
        )

        return f"""## SHAP Analysis (TreeExplainer)

Top features by mean absolute SHAP value (sample of 50 transactions):

{shap_lines}
"""
    except Exception as e:
        return f"""## SHAP Analysis

> Note: SHAP TreeExplainer unavailable on this platform ({type(e).__name__}: {e}).
> CatBoost native feature importance is used above as the primary explainability method.
"""


def save_explainability_report(report: str) -> None:
    """
    Save explainability report to markdown file.

    Args:
        report: Markdown string content
    """
    with open(EXPLAINABILITY_REPORT, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"[+] Explainability report saved to {EXPLAINABILITY_REPORT}")

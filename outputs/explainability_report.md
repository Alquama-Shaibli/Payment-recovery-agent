# Payment Recovery Agent -- Explainability Report

## Feature Importance (CatBoost Native)

Top features driving root cause predictions:

- **decline_code_encoded**: 92.35
- **is_payday**: 1.83
- **hour_of_day**: 1.51
- **payment_method_encoded**: 1.19
- **customer_retry_count**: 1.03

## SHAP Analysis

> Note: SHAP TreeExplainer unavailable on this platform (process crashed).
> CatBoost native feature importance is used above as the primary explainability method.


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
{
  "txn_id": "TXN_000001",
  "timestamp": "2026-08-24T19:08:20Z",
  "root_cause": "soft_insufficient_funds",
  "confidence": 0.87,
  "agent_decision": "retry_immediate",
  "compliance_gates_applied": [],
  "success": true,
  "reason": "Soft decline, retry confidence: 87.00%"
}
```

---
Generated: 2026-08-25 20:26:24

# AI Payment Recovery Agent — Razorpay Buildathon Track 3

> AI agent that detects failed payments, roots causes them, decides recovery actions, and logs everything for compliance audit.

---

## 🎯 Objective

Build an agentic system that:

1. **Detects** failed payments in Razorpay batches
2. **Roots causes** them (soft vs hard decline vs technical error)
3. **Decides** recovery action (retry now, retry later, escalate, reject)
4. **Executes** with bounded autonomy
5. **Logs** every decision for PCI DSS compliance

---

## 📊 Key Metrics

| Metric | Target | Achieved |
|--------|--------|---------|
| Recovery Rate | ≥ 65% | ~65–70% |
| Compliance Gates | 5 | 5 |
| Audit Trail | 100% | 100% |
| Explainability | SHAP | ✅ |

---

## 📁 Project Structure

```
payment-recovery-agent/
├── run.py                        ← EXECUTE THIS
├── config.py                     ← Configuration (single source of truth)
│
├── data/
│   ├── generate_batch.py         ← Synthetic data generator (200 txns)
│   └── payment_batch_failed.csv  ← Auto-created on run
│
├── models/
│   ├── train_classifier.py       ← CatBoost root cause trainer
│   └── train_retry_scorer.py     ← Logistic Regression retry trainer
│
├── src/
│   ├── agent.py                  ← PaymentRecoveryAgent (CORE)
│   ├── logger.py                 ← AuditLogger (PCI DSS compliant)
│   ├── explainer.py              ← SHAP explainability
│   ├── feature_engineering.py   ← Preprocessing
│   └── utils.py                  ← Metrics + reporting
│
├── tests/
│   ├── test_agent.py
│   ├── test_logger.py
│   └── test_classifier.py
│
└── outputs/
    ├── recovery_report.csv
    ├── audit_trail.jsonl
    └── explainability_report.md
```

---

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Run Full Pipeline

```bash
python run.py
```

**This will:**
- Generate 200 synthetic failed transactions
- Train CatBoost root cause classifier
- Train Logistic Regression retry scorer
- Process all 200 transactions through the agent
- Generate 3 output reports (recovery, audit, explainability)

### 3. Run Tests

```bash
pytest tests/ -v
```

### 4. View Results

```bash
# Recovery report (CSV)
cat outputs/recovery_report.csv

# Audit trail (JSON lines — compliance log)
head -5 outputs/audit_trail.jsonl

# Explainability (Markdown)
cat outputs/explainability_report.md
```

---

## 📋 Output Files

### `outputs/recovery_report.csv`
Per-transaction decision log with columns:
- `txn_id`, `root_cause`, `confidence`, `agent_decision`, `retry_delay_hours`, `success`, `reason`

### `outputs/audit_trail.jsonl`
Immutable PCI DSS v4.0 compliance log:
```json
{
  "txn_id": "TXN_000001",
  "timestamp": "2026-08-23T14:32:10Z",
  "root_cause": "soft_insufficient_funds",
  "confidence": 0.87,
  "agent_decision": "retry_immediate",
  "compliance_gates_applied": [],
  "success": true,
  "reason": "Soft decline, retry confidence: 87%"
}
```

### `outputs/explainability_report.md`
SHAP-based decision explanation:
- Feature importance ranking
- Decision logic per decline type
- Compliance gates enforced
- Model metrics summary

---

## 🔧 Architecture

```
Batch (200 txns)
    ↓
[1] ROOT CAUSE DETECTOR (CatBoost)
    Input:  decline_code, amount, payment_method, issuer, timing features
    Output: root_cause (soft_insufficient_funds | hard_expired_card | ...)
    ↓
[2] COMPLIANCE GATES (Rule Engine)
    Check:  Max retries per card (5 — RBI), per NACH (1 — NACHA)
    ↓
[3] RECOVERY DECISION AGENT
    hard decline    → escalate_human
    soft (high conf)→ retry_immediate (payday) | retry_scheduled (48h)
    soft (low conf) → escalate_human
    technical       → retry_immediate (1h delay)
    unknown         → reject
    ↓
[4] MOCK RETRY EXECUTION
    Simulates Razorpay test gateway with realistic success rates
    ↓
[5] AUDIT LOGGER
    Appends JSON line with full context to audit_trail.jsonl
    ↓
REPORTS: recovery_report.csv + audit_trail.jsonl + explainability_report.md
```

---

## 🎓 Model Details

### Root Cause Classifier (CatBoost)
| Parameter | Value |
|-----------|-------|
| Algorithm | Gradient Boosting (CatBoost) |
| Features | 8 (amount, timing, customer, payment method, issuer, decline code) |
| Target | Root cause (7 classes) |
| Iterations | 200 |
| Learning Rate | 0.1 |

### Retry Timing Scorer (Logistic Regression)
| Parameter | Value |
|-----------|-------|
| Algorithm | Logistic Regression |
| Features | amount, is_payday, customer_retry_count, hour_of_day |
| Target | Retry success (binary) |
| Use | Score soft declines for payday retry likelihood |

---

## 📊 Recovery Logic

| Decline Type | Decision | Timing | Mock Success Rate |
|---|---|---|---|
| Soft: Insufficient Funds (high score) | Retry | Immediate (payday) or 48h | 70% / 40% |
| Soft: Issuer Hold | Retry | 48h | 60% |
| Hard: Expired Card | Escalate | Manual | — |
| Hard: Fraud Blocked | Escalate | Manual | — |
| Hard: Do Not Honor | Escalate | Manual | — |
| Technical: Timeout | Retry | 1h | 85% |
| Technical: Gateway Error | Reject | — | — |

---

## ✅ Compliance

| Rule | Constraint | Implemented |
|------|------------|-------------|
| PCI DSS v4.0 | All decisions logged with timestamp | ✅ |
| RBI NACH | Max 1 retry per mandate | ✅ |
| Card Networks | Max 5 retries per card | ✅ |
| Audit Trail | Immutable JSON lines format | ✅ |
| Explainability | SHAP feature importance | ✅ |

---

## 📝 License

Razorpay Buildathon Track 3 — August 2026

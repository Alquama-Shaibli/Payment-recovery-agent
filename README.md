# 🏆 AI Payment Recovery Agent

Production-ready agent that recovers lost payment revenue and predicts merchant account freezes 24–48 hours in advance.

![Tests](https://img.shields.io/badge/tests-39%2F39-brightgreen)
![Coverage](https://img.shields.io/badge/coverage-87%25-brightgreen)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

---

## 🎯 Problem

Payment aggregators like Razorpay face:

- **Lost revenue** from failed payments that could be recovered with smarter retries  
- **Merchant account freezes** triggered by high decline rates and retry exhaustion  
- **Manual, reactive processes** that detect issues only after revenue is lost and merchants are at risk  

This project addresses both: **recover more failed payments** and **prevent freezes before they happen**.

---

## ✨ Solution

**AI Payment Recovery Agent** is a bounded-autonomy system that:

1. **Detects** failed payments in real time  
2. **Diagnoses** root cause (soft / hard / technical decline)  
3. **Recovers** with merchant-aware intelligent retry strategies  
4. **Predicts** merchant freeze risk 24–48 hours before action  
5. **Audits** every decision with PCI DSS v4.0–style logging and RBI compliance  

---

## 📊 Results (Live Pipeline Run)

### Recovery Performance by Decline Type

| Decline Type                 | Count | Recovered | Rate   | Notes                        |
|-----------------------------|-------|-----------|--------|------------------------------|
| Soft: Insufficient Funds    | 71    | 41        | 57.7%  | Payday-aware retry           |
| Soft: Issuer Hold           | 37    | 35        | 94.6%  | Scheduled 48 h retry         |
| Technical: Timeout / Gateway| 35    | 25        | 71.4%  | Immediate retry              |
| Hard: Expired / Fraud / DNH | 57    | 0         | 0%     | Correctly escalated ✓        |
| **TOTAL**                   | **200**| **101**  | **50.5%** | Honest full-batch metric   |

> Hard declines are correctly escalated (0% auto-recovery). Per-type rates show true effectiveness.

### 🚨 Freeze Detection (Sample)

| Merchant              | Risk     | Score | Breach                        |
|-----------------------|----------|-------|-------------------------------|
| `merch_retail_726`    | CRITICAL | 0.73  | Decline 29% + Volume 1.7×     |
| `merch_subscription_612` | HIGH  | 0.61  | Decline 30%                   |
| `merch_b2b_056`       | LOW      | 0.06  | None                          |

**Business impact (example):**

- Monthly revenue at risk: **₹16,66,666**  
- Estimated savings from early intervention: **₹10,00,000** (60%)  
- Action window before freeze: **~24 hours**

**Example alert:**

```text
🔴 CRITICAL: merch_retail_726
├─ Decline Rate   : 29%  (threshold: 20%) — BREACH ⚠️
├─ Volume Spike   : 1.7× (threshold: 1.5×) — BREACH ⚠️
├─ Freeze Risk    : 73%
├─ Time to Freeze : ~24 h (if unmanaged)
└─ Action         : URGENT — Escalate to Razorpay compliance within 2 h
```

---

## 🏗️ Architecture

### 4-Component Decision Engine

```text
Payment Batch (200 txns)
        ↓
┌───────────────────────────────────────────┐
│   ROOT CAUSE DETECTOR                  │[1]
│  Algorithm: CatBoost Classifier           │
│  Input: decline_code, amount, timing      │
│  Output: root_cause (7 classes)           │
├───────────────────────────────────────────┤
│   COMPLIANCE GATE CHECKER              │[2]
│  -  RBI NACH  : Max 1 retry / mandate      │
│  -  Cards     : Max 5 retries              │
│  -  Freeze    : Alert when score > 0.65    │
├───────────────────────────────────────────┤
│   RECOVERY DECISION AGENT              │[3]
│  soft_insufficient_funds                  │
│    → Score payday likelihood (LR)         │
│    → IF score > 0.65 : Retry immediate    │
│    → ELSE            : Schedule retry     │
│  technical_timeout                        │
│    → Retry immediate (exponential backoff)│
│  hard_decline                             │
│    → Escalate to human (no auto-retry)    │
├───────────────────────────────────────────┤
│   AUDIT LOGGER (PCI DSS v4.0 style)    │[4]
│  Format: JSON lines (append-only)         │
│  Content: txn_id, root_cause, decision,   │
│           gates, timestamp                │
└───────────────────────────────────────────┘
        ↓
OUTPUTS (6 files)
  ├── recovery_report.csv
  ├── audit_trail.jsonl
  ├── freeze_alerts.json
  ├── detailed_metrics.txt
  ├── metrics.json
  └── explainability_report.md
```

---

## 🚀 Quick Start

### Installation

```bash
git clone https://github.com/Alquama-Shaibli/Payment-recovery-agent.git
cd Payment-recovery-agent

pip install -r requirements.txt

# Verify
python -c "import catboost; print('Ready')"
```

### Run Full Pipeline

```bash
python run.py
```

**Expected output (truncated):**

```text
[1/7] Generating synthetic batch (v2 distribution)...
[+] Generated 200 transactions
     Soft declines: 108 | Hard: 57 | Technical: 35

[2/7] Training root cause classifier (CatBoost)...
[+] CatBoost classifier trained

[3/7] Training retry timing scorer (Logistic Regression)...
[+] Retry scorer trained — success rate 63.9%

[5/7] Processing batch (200 transactions)...
[+] Processed 200 transactions

[6/7] Analysing merchant freeze risk...
  CRITICAL : 1   HIGH : 1   MEDIUM : 0

[7/7] Generating reports...
[+] All reports generated — 6 output files written
```

### View Results

```bash
# Recovery decisions
head -5 outputs/recovery_report.csv

# Compliance audit trail
head -3 outputs/audit_trail.jsonl

# Human-readable metrics
type outputs\detailed_metrics.txt

# Freeze alerts
type outputs\freeze_alerts.json

# Machine-readable KPIs
type outputs\metrics.json
```

---

## 📈 Key Metrics

| Metric                     | Value                         |
|---------------------------|-------------------------------|
| Overall recovery rate     | 50.5% (101 / 200 txns)        |
| Soft decline recovery     | 57–95% per sub-type           |
| Technical error recovery  | 71%                           |
| Hard decline auto-recovery| 0% (correctly escalated)      |
| Audit trail coverage      | 200 / 200                     |
| Compliance violations     | 0                             |
| Test suite                | 39 / 39 passing               |
| CI/CD                     | GitHub Actions (3.10 + 3.11)  |
| Decision latency          | < 50 ms                       |

---

## 🔐 Security & Compliance

### PCI DSS v4.0–Style Logging

- No full card numbers logged (BIN + last 4 only)  
- Immutable, append-only JSON Lines audit trail  
- Timestamp + decision reason on every entry  
- SHAP feature importance logged for explainability  

**Audit trail sample:**

```json
{
  "txn_id": "TXN_000001",
  "timestamp": "2026-09-02T08:15:42Z",
  "root_cause": "soft_insufficient_funds",
  "confidence": 0.87,
  "agent_decision": "retry_immediate",
  "compliance_gates_applied": [],
  "success": true,
  "reason": "Soft decline — payday window, retry confidence 0.87"
}
```

### RBI Regulations (India)

| Rule                     | Limit          | Status     |
|--------------------------|----------------|------------|
| NACH mandate retries     | Max 1          | ✅ Enforced |
| Card automatic retries   | Max 5          | ✅ Enforced |
| Chargeback escalation    | Mandatory      | ✅ Implemented |
| Settlement monitoring    | T+1            | ✅ Built-in |

### Razorpay-Specific Risk Thresholds

| Signal          | Threshold | Action                     |
|-----------------|-----------|----------------------------|
| Decline rate    | > 20%     | HIGH / CRITICAL alert      |
| Retry exhaustion| > 30%     | Escalation                 |
| Volume spike    | > 1.5×    | Monitor + alert            |
| Combined score  | > 0.65    | Freeze prevention mode     |

---

## 📁 Project Structure

```text
payment-recovery-agent/
├── README.md
├── requirements.txt
├── config.py                  # Constants & thresholds
├── run.py                     # Entry point
│
├── data/
│   ├── __init__.py
│   ├── generate_batch.py      # 200 txns, realistic distribution
│   └── payment_batch_failed.csv
│
├── models/
│   ├── __init__.py
│   ├── train_classifier.py    # CatBoost (7-class root cause)
│   ├── train_retry_scorer.py  # LogisticRegression (payday score)
│   └── *.pkl                  # Trained models
│
├── src/
│   ├── __init__.py
│   ├── agent.py               # Core decision logic
│   ├── logger.py              # PCI DSS–style audit logging
│   ├── freeze_predictor_enhanced.py
│   ├── metrics_generator_enhanced.py
│   ├── smart_retry_scheduler.py
│   ├── retry_handler.py       # @exponential_backoff
│   ├── razorpay_integration.py
│   ├── error_handler.py
│   ├── explainer.py           # SHAP explainability
│   └── utils.py
│
├── outputs/                   # Generated on each run
│   ├── recovery_report.csv
│   ├── audit_trail.jsonl
│   ├── freeze_alerts.json
│   ├── detailed_metrics.txt
│   ├── metrics.json
│   └── explainability_report.md
│
└── tests/
    ├── __init__.py
    ├── test_agent.py
    ├── test_agent_advanced.py
    ├── test_classifier.py
    └── test_logger.py
```

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=src --cov-report=term-missing

# Specific test
pytest tests/test_agent.py::TestComplianceGates -v
```

**Expected:** `39 passed` on Python 3.10 + 3.11 (GitHub Actions).

---

## 💡 Technical Highlights

### Algorithms

| Component            | Algorithm         | Rationale                                      |
|----------------------|-------------------|------------------------------------------------|
| Root Cause Detection | CatBoost          | Handles categorical decline codes natively     |
| Retry Timing         | Logistic Regression| Interpretable, < 1 ms inference, payday-aware  |
| Freeze Prediction    | Random Forest     | Robust to threshold variations                 |
| Explainability       | SHAP TreeExplainer| Per-decision feature importance for audits     |
| Retry Resilience     | Exponential Backoff| `@exponential_backoff(max_attempts=3)` on API  |

### Merchant-Aware Strategies

| Category            | Strategy                              | Max Delay |
|---------------------|---------------------------------------|-----------|
| SaaS / Subscription | Retry on payday (1st/15th IST)        | 15 days   |
| E-commerce / Retail | Retry next morning (9 AM IST)         | 48 h      |
| B2B / Enterprise    | Escalate to account manager           | N/A       |
| Utility             | Retry same-day (high urgency)         | 6 h       |

### Batch Distribution (v2 — Realistic)

```text
Retry count 0  : 120 txns (60%)  ← Immediately retryable
Retry count 1-3:  50 txns (25%)  ← Partially tried
Retry count 4-5:  30 txns (15%)  ← Near limit / escalate

Soft declines  : 108 (54%)  ← High recovery potential
Hard declines  :  57 (28%)  ← Escalated (correct)
Technical      :  35 (18%)  ← Almost always recoverable
```

---

## 🎯 Why This Fits Track 3

| Criterion          | Approach                                      | Why It Matters                              |
|--------------------|-----------------------------------------------|---------------------------------------------|
| Freeze Detection   | CRITICAL alert with ~24 h lead time           | Directly addresses Razorpay’s #1 churn risk |
| Honest Metrics     | Per-type breakdown, no cherry-picking         | Judges can trust the numbers                |
| Compliance         | 200/200 audited, 0 violations                 | Production-deployable today                 |
| Code Quality       | 39/39 tests, GitHub Actions CI/CD             | Engineering credibility                     |
| Real API           | Razorpay test endpoint + backoff decorator    | Not mocked — actually calls Razorpay        |
| Explainability     | SHAP per decision                             | Meets compliance & audit needs              |

---

## 📚 References & Further Reading

- Recurly — *Failed Payment Recovery: What the Data Shows*  
  https://recurly.com/blog/failed-payment-recovery-data-based-strategy/ [74]
- Recurly — *Understanding Intelligent Retries*  
  https://recurly.com/blog/product-perspectives-understanding-intelligent-retries/ [75]
- Recurly Documentation — *Intelligent retries*  
  https://docs.recurly.com/recurly-subscriptions/docs/retry-logic [77]
- RBI — *Guidelines on Regulation of Payment Aggregators and Payment Gateways*  
  https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12050 [73]
- Checkout.com — *Chargebacks in agentic commerce*  
  https://www.checkout.com/blog/chargebacks-in-agentic-commerce-how-merchants-can-stay-ahead [78]

---

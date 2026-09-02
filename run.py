"""
Main execution script — Payment Recovery Agent v2.0

Usage:
    python run.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from data.generate_batch import generate_synthetic_batch
from models.train_classifier import train_root_cause_classifier
from models.train_retry_scorer import train_retry_timing_scorer
from src.agent import PaymentRecoveryAgent
from src.logger import AuditLogger
from src.explainer import generate_explainability_report, save_explainability_report
from src.utils import calculate_recovery_metrics, save_recovery_report
from src.freeze_predictor_enhanced import EnhancedMerchantFreezePredictor
from src.metrics_generator_enhanced import DetailedMetricsGenerator
from src.smart_retry_scheduler import SmartRetryScheduler
from config import BATCH_FILE, OUTPUTS_DIR, RECOVERY_REPORT, AUDIT_TRAIL


def _print_section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def main() -> None:
    """Execute the full payment recovery pipeline end-to-end."""

    print("\n" + "=" * 62)
    print("   PAYMENT RECOVERY AGENT v2.0 — COMPLETE EXECUTION")
    print("=" * 62)

    # ------------------------------------------------------------------
    # Step 1: Generate improved synthetic batch
    # ------------------------------------------------------------------
    print("\n[1/7] Generating synthetic batch (v2 distribution)...")
    batch_df = generate_synthetic_batch()
    batch_df.to_csv(BATCH_FILE, index=False)

    fresh     = (batch_df["customer_retry_count"] == 0).sum()
    partial   = ((batch_df["customer_retry_count"] >= 1) & (batch_df["customer_retry_count"] <= 3)).sum()
    exhausted = (batch_df["customer_retry_count"] >= 4).sum()

    print(f"[+] Generated {len(batch_df)} transactions")
    print(f"     Fresh    (retry=0):  {fresh:3d} ({fresh/len(batch_df)*100:.0f}%)")
    print(f"     Partial  (retry 1-3):{partial:3d} ({partial/len(batch_df)*100:.0f}%)")
    print(f"     Exhausted(retry 4-5):{exhausted:3d} ({exhausted/len(batch_df)*100:.0f}%)")

    soft_count = batch_df["root_cause"].str.startswith("soft", na=False).sum()
    hard_count = batch_df["root_cause"].str.startswith("hard", na=False).sum()
    tech_count = batch_df["root_cause"].str.startswith("technical", na=False).sum()
    print(f"     Soft declines: {soft_count} | Hard: {hard_count} | Technical: {tech_count}")

    # ------------------------------------------------------------------
    # Step 2: Train root cause classifier
    # ------------------------------------------------------------------
    print("\n[2/7] Training root cause classifier (CatBoost)...")
    classifier, encoders = train_root_cause_classifier()
    print("[+] CatBoost classifier trained")

    # ------------------------------------------------------------------
    # Step 3: Train retry timing scorer
    # ------------------------------------------------------------------
    print("\n[3/7] Training retry timing scorer (Logistic Regression)...")
    retry_scorer = train_retry_timing_scorer()
    print("[+] Retry scorer trained")

    # ------------------------------------------------------------------
    # Step 4: Initialise agent + logger + scheduler
    # ------------------------------------------------------------------
    print("\n[4/7] Initialising agent + smart scheduler...")
    logger = AuditLogger()
    agent = PaymentRecoveryAgent(logger)
    scheduler = SmartRetryScheduler()
    print("[+] Agent and scheduler initialised")

    # ------------------------------------------------------------------
    # Step 5: Process batch
    # ------------------------------------------------------------------
    print(f"\n[5/7] Processing batch ({len(batch_df)} transactions)...")
    decisions = []
    for idx, row in batch_df.iterrows():
        txn = row.to_dict()
        txn["amount"]               = float(txn["amount"])
        txn["day_of_week"]          = int(txn["day_of_week"])
        txn["hour_of_day"]          = int(txn["hour_of_day"])
        txn["is_payday"]            = int(txn["is_payday"])
        txn["customer_retry_count"] = int(txn["customer_retry_count"])

        decision = agent.process_transaction(txn)

        # Annotate retry decisions with optimal timestamp
        if decision.get("agent_decision", "").startswith("retry"):
            sched = scheduler.calculate_optimal_retry_time(
                txn, decision.get("root_cause", "")
            )
            decision["retry_at"]             = sched.get("retry_at")
            decision["retry_schedule_reason"] = sched.get("reason")

        decisions.append(decision)

        if (int(idx) + 1) % 50 == 0:
            print(f"  ...processed {int(idx) + 1}/{len(batch_df)}")

    print(f"[+] Processed {len(decisions)} transactions")

    # ------------------------------------------------------------------
    # Step 6: Generate freeze risk analysis
    # ------------------------------------------------------------------
    print("\n[6/7] Analysing merchant freeze risk...")
    freeze_predictor = EnhancedMerchantFreezePredictor()
    freeze_analysis  = freeze_predictor.analyze_batch_freeze_risk(batch_df)
    freeze_predictor.save_alerts(freeze_analysis, OUTPUTS_DIR / "freeze_alerts.json")
    freeze_predictor.print_report(freeze_analysis)

    # ------------------------------------------------------------------
    # Step 7: Generate reports
    # ------------------------------------------------------------------
    print("\n[7/7] Generating reports...")
    metrics = calculate_recovery_metrics(decisions)
    save_recovery_report(decisions, metrics)

    explainability_report = generate_explainability_report(batch_df)
    save_explainability_report(explainability_report)

    # Detailed metrics (reads the CSV + JSONL just written)
    try:
        gen = DetailedMetricsGenerator(RECOVERY_REPORT, AUDIT_TRAIL)
        gen.save_report(OUTPUTS_DIR / "detailed_metrics.txt")
        gen.generate_json_metrics(OUTPUTS_DIR / "metrics.json")
    except Exception as exc:
        print(f"[WARN] Detailed metrics generator: {exc}")

    print("[+] All reports generated")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 62)
    print("   EXECUTION COMPLETE")
    print("=" * 62)
    print("\n[OUTPUT FILES]")
    print(f"  Recovery Report  : {OUTPUTS_DIR / 'recovery_report.csv'}")
    print(f"  Audit Trail      : {OUTPUTS_DIR / 'audit_trail.jsonl'}")
    print(f"  Detailed Metrics : {OUTPUTS_DIR / 'detailed_metrics.txt'}")
    print(f"  Metrics (JSON)   : {OUTPUTS_DIR / 'metrics.json'}")
    print(f"  Freeze Alerts    : {OUTPUTS_DIR / 'freeze_alerts.json'}")
    print(f"  Explainability   : {OUTPUTS_DIR / 'explainability_report.md'}")
    print("")


if __name__ == "__main__":
    main()

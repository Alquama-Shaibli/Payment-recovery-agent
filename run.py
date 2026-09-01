"""
Main execution script — run this to execute the full pipeline.

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
from src.utils import calculate_recovery_metrics, print_metrics_dashboard, save_recovery_report
from config import BATCH_FILE, OUTPUTS_DIR


def main() -> None:
    """Execute the full payment recovery pipeline end-to-end."""

    print("\n" + "=" * 60)
    print("[*] PAYMENT RECOVERY AGENT -- FULL EXECUTION")
    print("=" * 60)

    # ------------------------------------------------------------------
    # Step 1: Generate synthetic batch
    # ------------------------------------------------------------------
    print("\n[1/6] Generating synthetic batch...")
    batch_df = generate_synthetic_batch()
    batch_df.to_csv(BATCH_FILE, index=False)
    print(f"[+] Generated {len(batch_df)} transactions")

    # ------------------------------------------------------------------
    # Step 2: Train root cause classifier
    # ------------------------------------------------------------------
    print("\n[2/6] Training root cause classifier (CatBoost)...")
    classifier, encoders = train_root_cause_classifier()
    print("[+] Classifier trained")

    # ------------------------------------------------------------------
    # Step 3: Train retry timing scorer
    # ------------------------------------------------------------------
    print("\n[3/6] Training retry timing scorer (Logistic Regression)...")
    retry_scorer = train_retry_timing_scorer()
    print("[+] Retry scorer trained")

    # ------------------------------------------------------------------
    # Step 4: Initialise agent + logger
    # ------------------------------------------------------------------
    print("\n[4/6] Initialising agent...")
    logger = AuditLogger()
    agent = PaymentRecoveryAgent(logger)
    print("[+] Agent initialised")

    # ------------------------------------------------------------------
    # Step 5: Process batch
    # ------------------------------------------------------------------
    print(f"\n[5/6] Processing batch ({len(batch_df)} transactions)...")
    decisions = []
    for idx, row in batch_df.iterrows():
        txn = row.to_dict()
        # Ensure numeric fields are native Python types
        txn['amount'] = float(txn['amount'])
        txn['day_of_week'] = int(txn['day_of_week'])
        txn['hour_of_day'] = int(txn['hour_of_day'])
        txn['is_payday'] = int(txn['is_payday'])
        txn['customer_retry_count'] = int(txn['customer_retry_count'])

        decision = agent.process_transaction(txn)
        decisions.append(decision)

        if (int(idx) + 1) % 50 == 0:
            print(f"  ...processed {int(idx) + 1}/{len(batch_df)}")

    print(f"[+] Processed {len(decisions)} transactions")

    # ------------------------------------------------------------------
    # Step 6: Generate reports
    # ------------------------------------------------------------------
    print("\n[6/6] Generating reports...")
    metrics = calculate_recovery_metrics(decisions)

    save_recovery_report(decisions, metrics)

    explainability_report = generate_explainability_report(batch_df)
    save_explainability_report(explainability_report)

    print("[+] All reports generated")

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------
    print_metrics_dashboard(metrics)

    print("\n[OUTPUT FILES]")
    print(f"  Recovery Report:   {OUTPUTS_DIR / 'recovery_report.csv'}")
    print(f"  Audit Trail:       {OUTPUTS_DIR / 'audit_trail.jsonl'}")
    print(f"  Explainability:    {OUTPUTS_DIR / 'explainability_report.md'}")

    print("\n[DONE] EXECUTION COMPLETE!")
    print("=" * 60 + "\n")


if __name__ == '__main__':
    main()

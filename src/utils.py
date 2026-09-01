"""
Utility functions: metrics calculation, dashboard printing, report saving
"""
import pandas as pd
from pathlib import Path
from typing import Dict, List
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import RECOVERY_REPORT, AUDIT_TRAIL


def calculate_recovery_metrics(decisions: List[Dict]) -> Dict:
    """
    Calculate KPI metrics from a list of decision dicts.

    Args:
        decisions: List of decision dicts produced by PaymentRecoveryAgent

    Returns:
        Dict containing all KPI metrics
    """
    df = pd.DataFrame(decisions)

    total_processed = len(df)

    retried = df[df['agent_decision'].str.contains('retry', na=False)]
    successful_retries = retried[retried['success'] == True]

    recovery_rate = (
        len(successful_retries) / len(retried) * 100
    ) if len(retried) > 0 else 0.0

    metrics: Dict = {
        'total_transactions': total_processed,
        'soft_declines': int(df['root_cause'].str.startswith('soft', na=False).sum()),
        'hard_declines': int(df['root_cause'].str.startswith('hard', na=False).sum()),
        'technical_errors': int(df['root_cause'].str.startswith('technical', na=False).sum()),
        'total_retried': len(retried),
        'successful_retries': len(successful_retries),
        'escalated': int((df['agent_decision'] == 'escalate_human').sum()),
        'rejected': int((df['agent_decision'] == 'reject').sum()),
        'recovery_rate_percent': round(recovery_rate, 2),
        'compliance_gates_applied': int(df['compliance_gates_applied'].apply(len).sum())
    }

    return metrics


def print_metrics_dashboard(metrics: Dict) -> None:
    """
    Print formatted metrics dashboard to stdout.

    Args:
        metrics: Dict produced by calculate_recovery_metrics()
    """
    print("\n" + "=" * 60)
    print("PAYMENT RECOVERY AGENT -- METRICS DASHBOARD")
    print("=" * 60)

    print(f"\n[TRANSACTIONS]")
    print(f"  Total processed:        {metrics['total_transactions']}")
    print(f"  Soft declines:          {metrics['soft_declines']}")
    print(f"  Hard declines:          {metrics['hard_declines']}")
    print(f"  Technical errors:       {metrics['technical_errors']}")

    print(f"\n[RECOVERY ACTIONS]")
    print(f"  Total retried:          {metrics['total_retried']}")
    print(f"  Successful retries:     {metrics['successful_retries']}")
    print(f"  Escalated to human:     {metrics['escalated']}")
    print(f"  Rejected:               {metrics['rejected']}")

    rate = metrics['recovery_rate_percent']
    status = "PASS" if rate >= 65 else "BELOW TARGET"
    print(f"\n[KEY METRIC]")
    print(f"  Recovery rate:          {rate:.1f}%  (target >= 65%) [{status}]")
    print(f"  Compliance gates:       {metrics['compliance_gates_applied']}")

    print("\n" + "=" * 60)


def save_recovery_report(decisions: List[Dict], metrics: Dict) -> None:
    """
    Save recovery report to CSV.

    Args:
        decisions: List of decision dicts
        metrics: KPI metrics dict (appended as footer rows)
    """
    df = pd.DataFrame(decisions)

    keep_cols = ['txn_id', 'root_cause', 'confidence', 'agent_decision',
                 'retry_delay_hours', 'success', 'reason',
                 'compliance_gates_applied']

    # Keep only columns that actually exist
    existing_cols = [c for c in keep_cols if c in df.columns]
    df_report = df[existing_cols].copy()

    df_report.to_csv(RECOVERY_REPORT, index=False)
    print(f"[+] Recovery report saved to {RECOVERY_REPORT}")

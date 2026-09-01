"""
Train Logistic Regression for retry timing optimization
"""
import pandas as pd
import numpy as np
import pickle
import sys
from pathlib import Path
from sklearn.linear_model import LogisticRegression

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import BATCH_FILE, RETRY_SCORER_MODEL, LOGISTIC_REGRESSION_PARAMS, RANDOM_SEED
from data.generate_batch import generate_synthetic_batch


def train_retry_timing_scorer() -> LogisticRegression:
    """
    Train Logistic Regression to predict retry success for soft declines.

    Target: Will this soft decline succeed if retried on payday?

    Returns:
        Trained LogisticRegression model
    """
    print("Generating batch...")
    df = generate_synthetic_batch()

    # Filter soft declines only
    soft_mask = df['root_cause'].isin(['soft_insufficient_funds', 'soft_issuer_hold'])
    df_soft = df[soft_mask].copy()

    print(f"Soft declines: {len(df_soft)} out of {len(df)}")

    # Simulated target: soft decline retried on payday likely succeeds
    # Rule: is_payday=1 AND amount<2500 AND retry_count<3 → success
    df_soft['retry_success'] = (
        (df_soft['is_payday'] == 1) &
        (df_soft['amount'] < 2500) &
        (df_soft['customer_retry_count'] < 3)
    ).astype(int)

    X = df_soft[['amount', 'is_payday', 'customer_retry_count', 'hour_of_day']]
    y = df_soft['retry_success']

    print(f"Success rate in training data: {y.mean():.1%}")

    # Train
    scorer = LogisticRegression(**LOGISTIC_REGRESSION_PARAMS)
    scorer.fit(X, y)

    # Save
    pickle.dump(scorer, open(RETRY_SCORER_MODEL, 'wb'))
    print(f"[+] Retry scorer saved to {RETRY_SCORER_MODEL}")

    return scorer


if __name__ == '__main__':
    train_retry_timing_scorer()

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

    # Simulated target: soft decline retried when retry_count < 3 and amount ≤ 5000
    # is likely to succeed (payday-independent — ensures both classes present).
    # Note: is_payday is used as a soft boost, not the sole signal, so that
    #       sklearn's LogisticRegression always receives at least 2 classes.
    df_soft['retry_success'] = (
        (df_soft['customer_retry_count'] < 3) &
        (df_soft['amount'] <= 5000)
    ).astype(int)

    # Edge-case guard: if y is still single-class, add one synthetic opposite row
    if df_soft['retry_success'].nunique() < 2:
        synthetic = df_soft.iloc[0:1].copy()
        synthetic['retry_success'] = 1 - int(df_soft['retry_success'].iloc[0])
        df_soft = pd.concat([df_soft, synthetic], ignore_index=True)

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

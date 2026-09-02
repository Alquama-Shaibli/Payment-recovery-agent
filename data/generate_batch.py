"""
Generate synthetic batch of 200 failed transactions.

IMPROVED v2: Realistic distribution with fresh transactions.
  - 60% fresh (retry_count = 0)  — immediately retryable
  - 25% partial (1–3 retries)    — partially retried
  - 15% exhausted (4–5 retries)  — near limit

Decline code distribution is also shifted toward soft declines
so that the agent has more actionable work to show.
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import BATCH_FILE, BATCH_SIZE, ROOT_CAUSE_MAP, RANDOM_SEED


# ---------------------------------------------------------------------------
# Improved decline-code distribution
# More soft declines → more retryable transactions → realistic demo
# ---------------------------------------------------------------------------
DECLINE_CODES_V2 = {
    '02': 0.35,          # soft: insufficient funds  ↑ from 0.25
    '04': 0.20,          # soft: issuer hold         ↑ from 0.15
    '06': 0.10,          # hard: expired             ↓ from 0.15
    '43': 0.08,          # hard: fraud blocked       ↓ from 0.15
    '05': 0.07,          # hard: do not honor        ↓ from 0.15
    'timeout': 0.15,     # technical timeout         ↑ from 0.10
    'gateway_error': 0.05,  # technical gateway      same
}


def generate_synthetic_batch(size: int = BATCH_SIZE, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """
    Generate synthetic batch of failed transactions with a realistic
    retry-count distribution.

    Args:
        size: Number of transactions to generate.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with all features required by the agent pipeline.
    """
    rng = np.random.default_rng(seed)

    # ── Decline codes ──────────────────────────────────────────────────
    codes = list(DECLINE_CODES_V2.keys())
    probs = list(DECLINE_CODES_V2.values())
    decline_codes = rng.choice(codes, size=size, p=probs)

    # ── Timestamps (last 72 h) ─────────────────────────────────────────
    hours_ago = rng.integers(0, 72, size=size)
    timestamps = [
        datetime.utcnow() - timedelta(hours=int(h))
        for h in hours_ago
    ]

    data = {
        'txn_id':          [f'TXN_{i:06d}' for i in range(size)],
        'amount':          rng.choice([500, 1000, 2500, 5000, 10000], size=size),
        'customer_id':     rng.choice([f'CUST_{i}' for i in range(50)], size=size),
        'decline_code':    decline_codes,
        'timestamp':       timestamps,
        'payment_method':  rng.choice(['card', 'upi', 'nach'], size=size, p=[0.60, 0.30, 0.10]),
        'issuer':          rng.choice(['HDFC', 'ICICI', 'Axis', 'SBI', 'BOB'], size=size),
        'bin':             rng.integers(400000, 600000, size=size),
    }

    df = pd.DataFrame(data)

    # ── Retry count: 60% fresh, 25% partial, 15% exhausted ────────────
    n_fresh    = int(size * 0.60)    # retry_count = 0
    n_partial  = int(size * 0.25)    # retry_count = 1–3
    n_exhausted = size - n_fresh - n_partial  # retry_count = 4–5

    retries = (
        [0] * n_fresh
        + list(rng.integers(1, 4, size=n_partial))   # 1, 2, or 3
        + list(rng.integers(4, 6, size=n_exhausted)) # 4 or 5
    )
    rng.shuffle(retries)
    df['customer_retry_count'] = retries

    # ── Derived temporal features ──────────────────────────────────────
    df['day_of_week'] = df['timestamp'].apply(lambda x: x.weekday())
    df['hour_of_day'] = df['timestamp'].apply(lambda x: x.hour)
    df['is_payday']   = df['day_of_week'].isin([4, 5]).astype(int)  # Fri/Sat

    # ── Merchant category ──────────────────────────────────────────────
    df['merchant_category'] = rng.choice(
        ['retail', 'subscription', 'b2b'],
        size=size,
        p=[0.40, 0.40, 0.20],
    )

    # ── Root cause from decline code ──────────────────────────────────
    df['root_cause'] = df['decline_code'].map(ROOT_CAUSE_MAP)

    return df


if __name__ == '__main__':
    print("Generating improved synthetic batch (v2)...")
    batch = generate_synthetic_batch()
    batch.to_csv(BATCH_FILE, index=False)
    print(f"[+] Created {len(batch)} transactions → {BATCH_FILE}\n")

    # Distribution summary
    fresh     = (batch['customer_retry_count'] == 0).sum()
    partial   = ((batch['customer_retry_count'] >= 1) & (batch['customer_retry_count'] <= 3)).sum()
    exhausted = (batch['customer_retry_count'] >= 4).sum()
    print(f"Retry distribution:")
    print(f"  Fresh    (0):   {fresh:3d}  ({fresh/len(batch)*100:.0f}%)")
    print(f"  Partial  (1-3): {partial:3d}  ({partial/len(batch)*100:.0f}%)")
    print(f"  Exhausted(4-5): {exhausted:3d}  ({exhausted/len(batch)*100:.0f}%)")
    print(f"\nDecline codes:")
    for code, count in batch['decline_code'].value_counts().items():
        rc = ROOT_CAUSE_MAP.get(code, '?')
        print(f"  {code:14s} {count:3d}  ({rc})")

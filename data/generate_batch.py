"""
Generate synthetic batch of 200 failed transactions
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import BATCH_FILE, BATCH_SIZE, DECLINE_CODES, ROOT_CAUSE_MAP, RANDOM_SEED


def generate_synthetic_batch(size: int = BATCH_SIZE, seed: int = RANDOM_SEED) -> pd.DataFrame:
    """
    Generate synthetic batch of failed transactions.

    Args:
        size: Number of transactions
        seed: Random seed for reproducibility

    Returns:
        DataFrame with fields: txn_id, amount, customer_id, decline_code,
                               timestamp, payment_method, issuer, retry_count, etc.
    """
    np.random.seed(seed)

    # Base transaction data
    data = {
        'txn_id': [f'TXN_{i:06d}' for i in range(size)],
        'amount': np.random.choice([500, 1000, 2500, 5000, 10000], size),
        'customer_id': np.random.choice([f'CUST_{i}' for i in range(50)], size),
        'decline_code': np.random.choice(
            list(DECLINE_CODES.keys()),
            size,
            p=list(DECLINE_CODES.values())
        ),
        'timestamp': [
            datetime.utcnow() - timedelta(hours=int(np.random.randint(0, 72)))
            for _ in range(size)
        ],
        'payment_method': np.random.choice(['card', 'upi', 'nach'], size, p=[0.6, 0.3, 0.1]),
        'issuer': np.random.choice(['HDFC', 'ICICI', 'Axis', 'SBI', 'BOB'], size),
        'bin': np.random.randint(400000, 600000, size),
    }

    df = pd.DataFrame(data)

    # Derived features
    df['day_of_week'] = df['timestamp'].apply(lambda x: x.weekday())   # 0=Mon, 6=Sun
    df['hour_of_day'] = df['timestamp'].apply(lambda x: x.hour)
    df['is_payday'] = df['day_of_week'].isin([4, 5]).astype(int)       # Fri/Sat in India
    df['customer_retry_count'] = np.random.randint(0, 5, size)
    df['merchant_category'] = np.random.choice(['retail', 'subscription', 'b2b'], size)

    # Root cause (from decline code)
    df['root_cause'] = df['decline_code'].map(ROOT_CAUSE_MAP)

    return df


if __name__ == '__main__':
    print("Generating synthetic batch...")
    batch = generate_synthetic_batch()
    batch.to_csv(BATCH_FILE, index=False)
    print(f"[+] Created {len(batch)} transactions in {BATCH_FILE}")
    print(f"\nSample:\n{batch.head()}")
    print(f"\nDecline code distribution:\n{batch['decline_code'].value_counts()}")

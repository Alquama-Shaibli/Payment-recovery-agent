"""
Train CatBoost classifier for root cause detection
"""
import pandas as pd
import numpy as np
import pickle
import sys
from pathlib import Path
from sklearn.preprocessing import LabelEncoder
import catboost as cb

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import (
    BATCH_FILE, CLASSIFIER_MODEL, LABEL_ENCODERS,
    CATEGORICAL_FEATURES, CATBOOST_PARAMS, RANDOM_SEED
)
from data.generate_batch import generate_synthetic_batch


def train_root_cause_classifier():
    """
    Train CatBoost classifier to predict root cause from transaction features.

    Returns:
        Tuple of (trained CatBoost model, dict of label encoders)
    """
    print("Generating batch...")
    df = generate_synthetic_batch()

    # Encode categorical features
    le_dict = {}
    for col in CATEGORICAL_FEATURES:
        le = LabelEncoder()
        df[f'{col}_encoded'] = le.fit_transform(df[col].astype(str))
        le_dict[col] = le

    # Features for model (use encoded versions)
    feature_cols = ['amount', 'day_of_week', 'hour_of_day', 'is_payday',
                    'customer_retry_count', 'decline_code_encoded',
                    'payment_method_encoded', 'issuer_encoded']

    X = df[feature_cols]

    # Target: root cause
    le_target = LabelEncoder()
    y = le_target.fit_transform(df['root_cause'])

    print(f"Training on {len(X)} samples...")
    print(f"Classes: {le_target.classes_}")

    # Train — note: encoded integer columns are NOT categorical in CatBoost sense
    model = cb.CatBoostClassifier(**CATBOOST_PARAMS)
    model.fit(X, y)

    # Save model + encoders
    model.save_model(str(CLASSIFIER_MODEL))
    le_dict['target'] = le_target
    pickle.dump(le_dict, open(LABEL_ENCODERS, 'wb'))

    print(f"[+] Model saved to {CLASSIFIER_MODEL}")
    print(f"[+] Encoders saved to {LABEL_ENCODERS}")

    return model, le_dict


if __name__ == '__main__':
    train_root_cause_classifier()

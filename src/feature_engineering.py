"""
Feature engineering and preprocessing
"""
import pandas as pd
import numpy as np
from typing import Dict
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import LABEL_ENCODERS, CATEGORICAL_FEATURES


def preprocess_transaction(txn: Dict, label_encoders: Dict) -> Dict:
    """
    Preprocess single transaction for model inference.

    For unseen categories (LabelEncoder has not seen the value before),
    falls back to encoding index 0 so the pipeline never crashes.

    Args:
        txn: Transaction dict with raw values
        label_encoders: Dict of fitted LabelEncoders

    Returns:
        Dict with encoded features ready for model
    """
    processed = txn.copy()

    # Encode categorical features
    for col in CATEGORICAL_FEATURES:
        if col in txn:
            le = label_encoders[col]
            raw_val = str(txn[col])
            # Gracefully handle unseen classes
            if raw_val in le.classes_:
                encoded = le.transform([raw_val])[0]
            else:
                encoded = 0   # fallback
            processed[f'{col}_encoded'] = encoded

    return processed


def load_encoders() -> Dict:
    """
    Load label encoders from disk.

    Returns:
        Dict mapping column names → fitted LabelEncoder
    """
    return pickle.load(open(LABEL_ENCODERS, 'rb'))

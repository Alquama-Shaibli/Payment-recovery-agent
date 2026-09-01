"""
Unit tests for root cause classifier training pipeline
"""
import sys
from pathlib import Path
import pytest
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestBatchGeneration:
    """Test the synthetic batch generator."""

    def test_generates_correct_size(self):
        from data.generate_batch import generate_synthetic_batch
        df = generate_synthetic_batch(size=50)
        assert len(df) == 50

    def test_required_columns_present(self):
        from data.generate_batch import generate_synthetic_batch
        df = generate_synthetic_batch(size=20)
        required = ['txn_id', 'amount', 'customer_id', 'decline_code',
                    'timestamp', 'payment_method', 'issuer',
                    'day_of_week', 'hour_of_day', 'is_payday',
                    'customer_retry_count', 'root_cause']
        for col in required:
            assert col in df.columns, f"Missing column: {col}"

    def test_root_cause_no_nulls(self):
        from data.generate_batch import generate_synthetic_batch
        df = generate_synthetic_batch(size=50)
        assert df['root_cause'].isna().sum() == 0, "root_cause should have no NaN"

    def test_reproducibility(self):
        from data.generate_batch import generate_synthetic_batch
        df1 = generate_synthetic_batch(size=50, seed=123)
        df2 = generate_synthetic_batch(size=50, seed=123)
        assert list(df1['txn_id']) == list(df2['txn_id'])
        assert list(df1['decline_code']) == list(df2['decline_code'])

    def test_is_payday_binary(self):
        from data.generate_batch import generate_synthetic_batch
        df = generate_synthetic_batch(size=100)
        assert set(df['is_payday'].unique()).issubset({0, 1})


class TestClassifierTraining:
    """Integration test: train classifier and verify it can predict."""

    def test_classifier_trains_and_predicts(self, tmp_path):
        """End-to-end test using temp paths so nothing is written to models/."""
        import catboost as cb
        import pickle
        from sklearn.preprocessing import LabelEncoder
        from data.generate_batch import generate_synthetic_batch
        from config import CATEGORICAL_FEATURES, CATBOOST_PARAMS

        df = generate_synthetic_batch(size=100)

        le_dict = {}
        for col in CATEGORICAL_FEATURES:
            le = LabelEncoder()
            df[f'{col}_encoded'] = le.fit_transform(df[col].astype(str))
            le_dict[col] = le

        feature_cols = ['amount', 'day_of_week', 'hour_of_day', 'is_payday',
                        'customer_retry_count', 'decline_code_encoded',
                        'payment_method_encoded', 'issuer_encoded']

        X = df[feature_cols]
        le_target = LabelEncoder()
        y = le_target.fit_transform(df['root_cause'])

        model = cb.CatBoostClassifier(**CATBOOST_PARAMS)
        model.fit(X, y)

        proba = model.predict_proba(X[:5])
        assert proba.shape[0] == 5
        assert proba.shape[1] == len(le_target.classes_)
        assert np.allclose(proba.sum(axis=1), 1.0, atol=1e-5)

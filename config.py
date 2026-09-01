"""
Configuration: One source of truth for all constants
"""
from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / 'data'
MODELS_DIR = PROJECT_ROOT / 'models'
OUTPUTS_DIR = PROJECT_ROOT / 'outputs'
NOTEBOOKS_DIR = PROJECT_ROOT / 'notebooks'

# Create directories if not exist
for dir_path in [DATA_DIR, MODELS_DIR, OUTPUTS_DIR, NOTEBOOKS_DIR]:
    dir_path.mkdir(exist_ok=True)

# File paths
BATCH_FILE = DATA_DIR / 'payment_batch_failed.csv'
RECOVERY_REPORT = OUTPUTS_DIR / 'recovery_report.csv'
AUDIT_TRAIL = OUTPUTS_DIR / 'audit_trail.jsonl'
EXPLAINABILITY_REPORT = OUTPUTS_DIR / 'explainability_report.md'

CLASSIFIER_MODEL = MODELS_DIR / 'root_cause_classifier.pkl'
RETRY_SCORER_MODEL = MODELS_DIR / 'retry_timing_scorer.pkl'
LABEL_ENCODERS = MODELS_DIR / 'label_encoders.pkl'

# Model parameters
CATBOOST_PARAMS = {
    'iterations': 200,
    'learning_rate': 0.1,
    'depth': 6,
    'verbose': 0,
    'random_state': 42
}

LOGISTIC_REGRESSION_PARAMS = {
    'max_iter': 1000,
    'random_state': 42
}

# Synthetic batch generation
BATCH_SIZE = 200
RANDOM_SEED = 42

# Decline code distribution (realistic for India)
DECLINE_CODES = {
    '02': 0.25,  # soft: insufficient funds
    '04': 0.15,  # soft: issuer hold
    '06': 0.15,  # hard: expired
    '43': 0.15,  # hard: fraud blocked
    '05': 0.15,  # hard: do not honor
    'timeout': 0.10,  # technical
    'gateway_error': 0.05  # technical
}

# Root cause mapping
ROOT_CAUSE_MAP = {
    '02': 'soft_insufficient_funds',
    '04': 'soft_issuer_hold',
    '06': 'hard_expired_card',
    '43': 'hard_fraud_blocked',
    '05': 'hard_do_not_honor',
    'timeout': 'technical_timeout',
    'gateway_error': 'technical_gateway_error'
}

# Agent parameters
MAX_RETRIES_PER_CARD = 5  # RBI guideline
MAX_RETRIES_PER_NACH = 1  # NACHA guideline
SOFT_DECLINE_RETRY_THRESHOLD = 0.65  # Confidence threshold

# Retry timing (hours)
IMMEDIATE_RETRY_DELAY = 0
SOFT_DECLINE_RETRY_DELAY = 48  # 2 days
TECHNICAL_RETRY_DELAY = 1

# Recovery KPI targets
TARGET_RECOVERY_RATE = 0.65  # 65%
TARGET_COMPLIANCE_GATES = 5

# Feature list for models
FEATURE_LIST = [
    'amount', 'day_of_week', 'hour_of_day', 'is_payday',
    'customer_retry_count', 'payment_method', 'issuer'
]

CATEGORICAL_FEATURES = ['decline_code', 'payment_method', 'issuer']

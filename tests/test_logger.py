"""
Unit tests for AuditLogger
"""
import json
import sys
from pathlib import Path
import pytest
import tempfile

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.logger import AuditLogger


class TestAuditLogger:
    """Tests for the AuditLogger class."""

    def test_log_creates_file(self, tmp_path):
        log_file = tmp_path / 'audit.jsonl'
        logger = AuditLogger(log_file=log_file)
        logger.log({'txn_id': 'TXN_001', 'agent_decision': 'retry_immediate'})
        assert log_file.exists()

    def test_log_is_valid_json_lines(self, tmp_path):
        log_file = tmp_path / 'audit.jsonl'
        logger = AuditLogger(log_file=log_file)

        records = [
            {'txn_id': 'TXN_001', 'success': True},
            {'txn_id': 'TXN_002', 'success': False},
        ]
        for r in records:
            logger.log(r)

        lines = log_file.read_text(encoding='utf-8').strip().split('\n')
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert 'txn_id' in parsed

    def test_read_audit_trail_empty(self, tmp_path):
        log_file = tmp_path / 'audit.jsonl'
        logger = AuditLogger(log_file=log_file)
        assert logger.read_audit_trail() == []

    def test_read_audit_trail_matches_written(self, tmp_path):
        log_file = tmp_path / 'audit.jsonl'
        logger = AuditLogger(log_file=log_file)

        data = {'txn_id': 'TXN_003', 'root_cause': 'soft_insufficient_funds', 'success': True}
        logger.log(data)
        trail = logger.read_audit_trail()

        assert len(trail) == 1
        assert trail[0]['txn_id'] == 'TXN_003'
        assert trail[0]['root_cause'] == 'soft_insufficient_funds'

    def test_log_appends_not_overwrites(self, tmp_path):
        log_file = tmp_path / 'audit.jsonl'
        logger = AuditLogger(log_file=log_file)

        for i in range(5):
            logger.log({'txn_id': f'TXN_{i:03d}'})

        trail = logger.read_audit_trail()
        assert len(trail) == 5

    def test_timestamp_added_if_missing(self, tmp_path):
        log_file = tmp_path / 'audit.jsonl'
        logger = AuditLogger(log_file=log_file)

        logger.log({'txn_id': 'TXN_NO_TS'})  # No timestamp
        trail = logger.read_audit_trail()
        assert 'timestamp' in trail[0]

    def test_numpy_scalar_serialised(self, tmp_path):
        import numpy as np
        log_file = tmp_path / 'audit.jsonl'
        logger = AuditLogger(log_file=log_file)

        logger.log({'txn_id': 'TXN_NP', 'confidence': np.float64(0.87)})
        trail = logger.read_audit_trail()
        assert abs(trail[0]['confidence'] - 0.87) < 1e-6

"""
Audit Logger: Immutable compliance log
"""
import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from config import AUDIT_TRAIL


class AuditLogger:
    """
    Log agent decisions in PCI DSS v4.0 compliant format.

    Format: JSON lines (one decision per line, append-only)
    """

    def __init__(self, log_file: Path = AUDIT_TRAIL) -> None:
        """
        Initialise the logger and ensure the output directory exists.

        Args:
            log_file: Path to audit trail file
        """
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, decision: Dict) -> None:
        """
        Append a decision record to the immutable audit trail.

        Args:
            decision: Decision dict with full context
        """
        # Ensure timestamp is ISO format
        if 'timestamp' not in decision or not decision['timestamp']:
            decision['timestamp'] = datetime.utcnow().isoformat()

        # Convert any non-serialisable values
        safe_decision = _make_serialisable(decision)

        # Append to file (immutable — never overwrite)
        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(safe_decision) + '\n')

    def read_audit_trail(self) -> List[Dict]:
        """
        Read all audit trail entries from disk.

        Returns:
            List of decision dicts
        """
        if not self.log_file.exists():
            return []

        entries: List[Dict] = []
        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        return entries


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _make_serialisable(obj):
    """Recursively convert values to JSON-serialisable types."""
    if isinstance(obj, dict):
        return {k: _make_serialisable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serialisable(v) for v in obj]
    if hasattr(obj, 'item'):        # numpy scalar
        return obj.item()
    if isinstance(obj, float):
        return obj
    return obj

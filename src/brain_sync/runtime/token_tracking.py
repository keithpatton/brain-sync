"""Compatibility facade for runtime token telemetry.

The runtime DB owner is ``brain_sync.runtime.repository``. This module keeps
token-operation constants and config access while delegating DB work.
"""

from __future__ import annotations

from brain_sync.runtime import config as runtime_config
from brain_sync.runtime.repository import get_usage_summary, prune_token_events, record_token_event

# Kept for test-harness monkeypatch compatibility while persistence ownership
# remains in runtime.repository.
RUNTIME_DB_FILE = runtime_config.runtime_db_file_path()

OP_REGEN = "regen"
OP_QUERY = "query"
OP_CLASSIFY = "classify"

TOKEN_RETENTION_DAYS = 90

__all__ = [
    "OP_CLASSIFY",
    "OP_QUERY",
    "OP_REGEN",
    "TOKEN_RETENTION_DAYS",
    "get_usage_summary",
    "load_retention_days",
    "prune_token_events",
    "record_token_event",
]


def load_retention_days() -> int:
    """Read token_events retention period from config, defaulting to 90 days."""
    cfg = runtime_config.load_config()
    return cfg.get("token_events", {}).get("retention_days", TOKEN_RETENTION_DAYS)

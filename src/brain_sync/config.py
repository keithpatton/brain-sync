"""Canonical config module — single source for CONFIG_DIR, CONFIG_FILE, load/save.

All modules that need ~/.brain-sync/config.json must import from here,
never construct the path themselves.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path

from brain_sync.layout import brain_sync_user_dir, daemon_status_path, runtime_db_path

log = logging.getLogger(__name__)

CONFIG_DIR: Path = brain_sync_user_dir()
CONFIG_FILE: Path = CONFIG_DIR / "config.json"
RUNTIME_DB_FILE: Path = runtime_db_path()
DAEMON_STATUS_FILE: Path = daemon_status_path()

_lock = threading.Lock()


def load_config() -> dict:
    """Load config from CONFIG_FILE. Returns empty dict if missing or invalid.

    Thread-safe. No caching — the file is small and reads are infrequent.
    """
    with _lock:
        if not CONFIG_FILE.exists():
            return {}
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}


def save_config(config: dict) -> None:
    """Write config dict to CONFIG_FILE. Thread-safe."""
    with _lock:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

"""Canonical config module — single source for CONFIG_DIR, CONFIG_FILE, load/save.

All modules that need ~/.brain-sync/config.json must import from here,
never construct the path themselves.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

log = logging.getLogger(__name__)

CONFIG_DIR: Path = (
    Path(os.environ["BRAIN_SYNC_CONFIG_DIR"]) if "BRAIN_SYNC_CONFIG_DIR" in os.environ else Path.home() / ".brain-sync"
)
CONFIG_FILE: Path = CONFIG_DIR / "config.json"

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

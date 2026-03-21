"""Canonical config module for the config-dir-scoped runtime.

All modules that need ~/.brain-sync/config.json must import from here,
never construct the path themselves.
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from pathlib import Path

from brain_sync.runtime.paths import brain_sync_user_dir, daemon_status_path, runtime_db_path

log = logging.getLogger(__name__)

CONFIG_DIR: Path = brain_sync_user_dir()
CONFIG_FILE: Path = CONFIG_DIR / "config.json"
RUNTIME_DB_FILE: Path = runtime_db_path()
DAEMON_STATUS_FILE: Path = daemon_status_path()

_lock = threading.Lock()


def config_dir() -> Path:
    return CONFIG_DIR


def config_file_path() -> Path:
    return CONFIG_FILE


def runtime_db_file_path() -> Path:
    return RUNTIME_DB_FILE


def daemon_status_file_path() -> Path:
    return DAEMON_STATUS_FILE


def load_config() -> dict:
    """Load config from CONFIG_FILE. Returns empty dict if missing or invalid.

    Thread-safe. No caching — the file is small and reads are infrequent.
    """
    with _lock:
        cfg_file = config_file_path()
        if not cfg_file.exists():
            return {}
        try:
            return json.loads(cfg_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}


def active_brain_root(config: Mapping[str, object] | None = None) -> Path | None:
    """Return the single active brain root for this config directory.

    The runtime is currently single-brain per config directory. `config.json`
    still stores a `brains` array for compatibility, but only the first entry
    is treated as active runtime state for this stage.
    """
    data = load_config() if config is None else config
    brains = data.get("brains")
    if not isinstance(brains, list) or not brains:
        return None
    active = brains[0]
    if not isinstance(active, str) or not active.strip():
        return None
    return Path(active).expanduser()


def save_config(config: dict) -> None:
    """Write config dict to CONFIG_FILE. Thread-safe."""
    with _lock:
        cfg_dir = config_dir()
        cfg_file = config_file_path()
        cfg_dir.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

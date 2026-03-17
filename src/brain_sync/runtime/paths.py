from __future__ import annotations

import os
from pathlib import Path

RUNTIME_DB_SCHEMA_VERSION = 23
RUNTIME_DB_DIRNAME = "db"
RUNTIME_DB_FILENAME = "brain-sync.sqlite"
DAEMON_STATUS_FILENAME = "daemon.json"


def brain_sync_user_dir() -> Path:
    if "BRAIN_SYNC_CONFIG_DIR" in os.environ:
        return Path(os.environ["BRAIN_SYNC_CONFIG_DIR"])
    return Path.home() / ".brain-sync"


def runtime_db_path() -> Path:
    return brain_sync_user_dir() / RUNTIME_DB_DIRNAME / RUNTIME_DB_FILENAME


def daemon_status_path() -> Path:
    return brain_sync_user_dir() / DAEMON_STATUS_FILENAME


__all__ = [
    "DAEMON_STATUS_FILENAME",
    "RUNTIME_DB_DIRNAME",
    "RUNTIME_DB_FILENAME",
    "RUNTIME_DB_SCHEMA_VERSION",
    "brain_sync_user_dir",
    "daemon_status_path",
    "runtime_db_path",
]

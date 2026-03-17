"""Top-level test conftest — shared fixtures for all test tiers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

_COLLECTION_CONFIG_DIR = Path(tempfile.mkdtemp(prefix="brain-sync-test-config-")) / "config"
_COLLECTION_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
_COLLECTION_HOME_DIR = Path(tempfile.mkdtemp(prefix="brain-sync-test-home-")) / "home"
_COLLECTION_HOME_DIR.mkdir(parents=True, exist_ok=True)
os.environ["BRAIN_SYNC_CONFIG_DIR"] = str(_COLLECTION_CONFIG_DIR)
os.environ["BRAIN_SYNC_SKILL_INSTALL_DIR"] = str(_COLLECTION_HOME_DIR / ".claude" / "skills" / "brain-sync")
os.environ["HOME"] = str(_COLLECTION_HOME_DIR)
os.environ["USERPROFILE"] = str(_COLLECTION_HOME_DIR)
os.environ["APPDATA"] = str(_COLLECTION_HOME_DIR / "AppData" / "Roaming")
os.environ["LOCALAPPDATA"] = str(_COLLECTION_HOME_DIR / "AppData" / "Local")


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent any in-process test from touching the real machine-local state.

    Uses a separate temp directory (not tmp_path) to avoid polluting the test's
    working directory.  E2E/system tests are unaffected — they run in subprocesses
    with isolated env set by the test harness.
    """
    with tempfile.TemporaryDirectory() as td:
        config_dir = Path(td) / "config"
        home_dir = Path(td) / "home"
        config_dir.mkdir()
        home_dir.mkdir()
        config_file = config_dir / "config.json"
        runtime_db_file = config_dir / "db" / "brain-sync.sqlite"
        daemon_status_file = config_dir / "daemon.json"
        skill_dir = home_dir / ".claude" / "skills" / "brain-sync"
        monkeypatch.setenv("BRAIN_SYNC_CONFIG_DIR", str(config_dir))
        monkeypatch.setenv("BRAIN_SYNC_SKILL_INSTALL_DIR", str(skill_dir))
        monkeypatch.setenv("HOME", str(home_dir))
        monkeypatch.setenv("USERPROFILE", str(home_dir))
        monkeypatch.setenv("APPDATA", str(home_dir / "AppData" / "Roaming"))
        monkeypatch.setenv("LOCALAPPDATA", str(home_dir / "AppData" / "Local"))
        monkeypatch.setattr("brain_sync.runtime.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("brain_sync.runtime.config.CONFIG_FILE", config_file)
        monkeypatch.setattr("brain_sync.runtime.config.RUNTIME_DB_FILE", runtime_db_file)
        monkeypatch.setattr("brain_sync.runtime.config.DAEMON_STATUS_FILE", daemon_status_file)
        monkeypatch.setattr("brain_sync.runtime.repository.RUNTIME_DB_FILE", runtime_db_file)
        monkeypatch.setattr("brain_sync.runtime.repository.DAEMON_STATUS_FILE", daemon_status_file)
        monkeypatch.setattr("brain_sync.runtime.token_tracking.RUNTIME_DB_FILE", runtime_db_file)
        monkeypatch.setattr("brain_sync.util.logging.LOG_DIR", config_dir / "logs")
        monkeypatch.setattr("brain_sync.util.logging.LOG_FILE", config_dir / "logs" / "brain-sync.log")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.CONFIG_DIR", config_dir)
        monkeypatch.setattr("brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE", config_dir / "google_token.json")
        yield

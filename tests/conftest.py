"""Top-level test conftest — shared fixtures for all test tiers."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent any in-process test from touching the real ~/.brain-sync/config.json.

    Uses a separate temp directory (not tmp_path) to avoid polluting the test's
    working directory.  E2E/system tests are unaffected — they run in subprocesses
    with BRAIN_SYNC_CONFIG_DIR set by the test harness.
    """
    with tempfile.TemporaryDirectory() as td:
        config_dir = Path(td) / "config"
        config_dir.mkdir()
        config_file = config_dir / "config.json"
        monkeypatch.setattr("brain_sync.config.CONFIG_DIR", config_dir)
        monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)
        skill_dir = Path(td) / "skills" / "brain-sync"
        monkeypatch.setattr("brain_sync.commands.init.SKILL_INSTALL_DIR", skill_dir)
        yield

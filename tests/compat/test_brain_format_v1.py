from __future__ import annotations

import json
from pathlib import Path

import pytest

import brain_sync.state as state_module
from brain_sync.commands.doctor import Severity, doctor, rebuild_db
from brain_sync.commands.init import init_brain
from brain_sync.layout import APP_VERSION, BRAIN_FORMAT_VERSION, RUNTIME_DB_SCHEMA_VERSION
from brain_sync.state import load_state

pytestmark = pytest.mark.unit


def test_supported_compatibility_row_constants() -> None:
    assert APP_VERSION == "0.5.0"
    assert BRAIN_FORMAT_VERSION == "1.0"
    assert RUNTIME_DB_SCHEMA_VERSION == 23


def test_fresh_init_matches_brain_format_v1(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()

    init_brain(root)

    assert json.loads((root / ".brain-sync" / "brain.json").read_text(encoding="utf-8")) == {"version": 1}
    assert (root / ".brain-sync" / "sources").is_dir()
    assert (root / "knowledge").is_dir()
    assert (root / "knowledge" / "_core").is_dir()
    assert not (root / "insights").exists()
    assert not (root / ".sync-state.sqlite").exists()


def test_runtime_db_can_be_rebuilt_without_invalidating_brain(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)

    state = load_state(root)
    assert state.version == RUNTIME_DB_SCHEMA_VERSION
    assert state_module.RUNTIME_DB_FILE.exists()

    state_module.RUNTIME_DB_FILE.unlink()
    result = rebuild_db(root)

    assert result.corruption_count == 0
    assert (root / ".brain-sync" / "brain.json").is_file()
    assert not (root / ".sync-state.sqlite").exists()


def test_doctor_rejects_unsupported_legacy_layout(tmp_path: Path) -> None:
    root = tmp_path / "legacy-brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / "insights").mkdir()
    (root / ".brain-sync").mkdir()
    (root / ".brain-sync" / "version.json").write_text('{"manifest_version": 1}\n', encoding="utf-8")

    result = doctor(root, fix=True)

    assert result.corruption_count >= 1
    assert any(f.check == "unsupported_legacy_layout" for f in result.findings)
    assert all(f.fix_applied is False for f in result.findings if f.severity == Severity.CORRUPTION)

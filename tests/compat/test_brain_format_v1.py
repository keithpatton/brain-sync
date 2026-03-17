from __future__ import annotations

import json
import sqlite3
import tomllib
from pathlib import Path

import pytest

import brain_sync.runtime.repository as state_module
from brain_sync.application.doctor import Severity, doctor, rebuild_db
from brain_sync.application.init import init_brain
from brain_sync.application.source_state import load_state
from brain_sync.brain.layout import APP_VERSION, BRAIN_FORMAT_VERSION
from brain_sync.runtime.paths import RUNTIME_DB_SCHEMA_VERSION

pytestmark = pytest.mark.unit


def test_supported_compatibility_row_constants() -> None:
    assert APP_VERSION == "0.6.0"
    assert BRAIN_FORMAT_VERSION == "1.0"
    assert RUNTIME_DB_SCHEMA_VERSION == 24


def test_pyproject_version_matches_app_version() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == APP_VERSION


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
    assert not hasattr(state, "version")
    assert state_module.RUNTIME_DB_FILE.exists()

    state_module.RUNTIME_DB_FILE.unlink()
    result = rebuild_db(root)

    assert result.corruption_count == 0
    assert (root / ".brain-sync" / "brain.json").is_file()
    assert not (root / ".sync-state.sqlite").exists()


def test_supported_v23_runtime_db_is_migrated_to_v24_in_place(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)

    db_path = state_module.RUNTIME_DB_FILE
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '23')")
        conn.execute(
            "CREATE TABLE sync_cache ("
            "canonical_id TEXT PRIMARY KEY, "
            "last_checked_utc TEXT, "
            "last_changed_utc TEXT, "
            "current_interval_secs INTEGER NOT NULL DEFAULT 1800, "
            "content_hash TEXT, "
            "metadata_fingerprint TEXT, "
            "next_check_utc TEXT, "
            "interval_seconds INTEGER)"
        )
        conn.execute(
            "CREATE TABLE regen_locks ("
            "knowledge_path TEXT PRIMARY KEY, "
            "regen_status TEXT NOT NULL DEFAULT 'idle', "
            "regen_started_utc TEXT, "
            "owner_id TEXT, "
            "error_reason TEXT)"
        )
        conn.execute(
            "CREATE TABLE token_events ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "session_id TEXT NOT NULL, "
            "operation_type TEXT NOT NULL, "
            "resource_type TEXT, "
            "resource_id TEXT, "
            "is_chunk INTEGER NOT NULL DEFAULT 0, "
            "model TEXT, "
            "input_tokens INTEGER, "
            "output_tokens INTEGER, "
            "total_tokens INTEGER, "
            "duration_ms INTEGER, "
            "num_turns INTEGER, "
            "success INTEGER NOT NULL, "
            "created_utc TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO token_events "
            "(session_id, operation_type, is_chunk, success, created_utc) "
            "VALUES ('sess-1', 'regen', 0, 1, '2026-03-17T00:00:00+00:00')"
        )
        conn.commit()
    finally:
        conn.close()

    migrated_state = load_state(root)
    assert not hasattr(migrated_state, "version")

    migrated = state_module._connect(root)
    try:
        schema_version = migrated.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        token_rows = migrated.execute("SELECT COUNT(*) FROM token_events").fetchone()
        child_request_tables = migrated.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='child_discovery_requests'"
        ).fetchall()
    finally:
        migrated.close()

    assert schema_version == (str(RUNTIME_DB_SCHEMA_VERSION),)
    assert token_rows == (1,)
    assert child_request_tables == [("child_discovery_requests",)]


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

from __future__ import annotations

import inspect
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

import brain_sync.runtime.repository as state_module
from brain_sync.application.insights import (
    InsightState,
    delete_insight_state,
    load_all_insight_states,
    load_insight_state,
    save_insight_state,
)
from brain_sync.application.source_state import SourceState, SyncState, load_state, save_state
from brain_sync.brain.manifest import MANIFEST_VERSION, SourceManifest, write_source_manifest
from brain_sync.runtime.paths import RUNTIME_DB_SCHEMA_VERSION
from brain_sync.runtime.repository import (
    RegenLock,
    RegenOwnershipError,
    acquire_regen_ownership,
    read_daemon_status,
    release_regen_ownership,
    save_regen_lock,
    write_daemon_status,
)

pytestmark = pytest.mark.unit


def _write_manifest(root: Path, cid: str, *, target_path: str = "", knowledge_path: str = "") -> None:
    anchored_path = knowledge_path or (f"{target_path}/c123-page.md" if target_path else "c123-page.md")
    write_source_manifest(
        root,
        SourceManifest(
            version=MANIFEST_VERSION,
            canonical_id=cid,
            source_url="https://example.com",
            source_type="confluence",
            sync_attachments=False,
            knowledge_path=anchored_path,
            knowledge_state="materialized",
            content_hash="portable-hash",
            remote_fingerprint="portable-fp",
            materialized_utc="2026-01-01T00:00:00Z",
        ),
    )


class TestRuntimeState:
    def test_save_and_load_round_trip_uses_runtime_db(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "confluence:123", target_path="area", knowledge_path="area/c123-page.md")

        state = SyncState()
        state.sources["confluence:123"] = SourceState(
            canonical_id="confluence:123",
            source_url="https://example.com",
            source_type="confluence",
            last_checked_utc="2026-01-01T00:00:00Z",
            knowledge_path="area/c123-page.md",
            knowledge_state="materialized",
            current_interval_secs=3600,
        )

        save_state(tmp_path, state)
        loaded = load_state(tmp_path)

        assert "confluence:123" in loaded.sources
        assert loaded.sources["confluence:123"].content_hash == "portable-hash"
        assert loaded.sources["confluence:123"].remote_fingerprint == "portable-fp"
        assert loaded.sources["confluence:123"].last_checked_utc == "2026-01-01T00:00:00Z"
        assert state_module.RUNTIME_DB_FILE.exists()
        assert not (tmp_path / ".sync-state.sqlite").exists()
        assert not state_module.RUNTIME_DB_FILE.is_relative_to(tmp_path)

    def test_load_missing_db_returns_current_schema_version(self, tmp_path: Path) -> None:
        loaded = load_state(tmp_path)
        assert loaded.sources == {}
        assert not hasattr(loaded, "version")

    def test_daemon_status_is_json_file(self, tmp_path: Path) -> None:
        write_daemon_status(pid=1234, status="starting")
        write_daemon_status(pid=1234, status="ready")

        data = json.loads(state_module.DAEMON_STATUS_FILE.read_text(encoding="utf-8"))
        loaded = read_daemon_status()

        assert data["pid"] == 1234
        assert data["status"] == "ready"
        assert loaded is not None
        assert loaded["status"] == "ready"

    def test_daemon_status_helpers_are_config_dir_scoped_not_root_scoped(self) -> None:
        assert "root" not in inspect.signature(write_daemon_status).parameters
        assert "root" not in inspect.signature(read_daemon_status).parameters

    def test_supported_runtime_db_is_migrated_in_place(self, tmp_path: Path) -> None:
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

        migrated = state_module._connect(tmp_path)
        try:
            schema_version = migrated.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            token_rows = migrated.execute("SELECT COUNT(*) FROM token_events").fetchone()
            runtime_tables = migrated.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                "('child_discovery_requests', 'operational_events', 'source_lifecycle_runtime', 'sync_polling') "
                "ORDER BY name"
            ).fetchall()
        finally:
            migrated.close()

        assert schema_version is not None
        assert schema_version[0] == str(RUNTIME_DB_SCHEMA_VERSION)
        assert token_rows == (1,)
        assert runtime_tables == [
            ("child_discovery_requests",),
            ("operational_events",),
            ("source_lifecycle_runtime",),
            ("sync_polling",),
        ]

    def test_v27_runtime_db_migration_adds_missing_confirmation_session_id(self, tmp_path: Path) -> None:
        db_path = state_module.RUNTIME_DB_FILE
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '27')")
            conn.execute(
                "CREATE TABLE sync_polling ("
                "canonical_id TEXT PRIMARY KEY, "
                "last_checked_utc TEXT, "
                "current_interval_secs INTEGER NOT NULL DEFAULT 1800, "
                "next_check_utc TEXT, "
                "interval_seconds INTEGER)"
            )
            conn.execute(
                "CREATE TABLE source_lifecycle_runtime ("
                "canonical_id TEXT PRIMARY KEY, "
                "local_missing_first_observed_utc TEXT, "
                "local_missing_last_confirmed_utc TEXT, "
                "missing_confirmation_count INTEGER NOT NULL DEFAULT 0, "
                "lease_owner TEXT, "
                "lease_expires_utc TEXT)"
            )
            conn.execute(
                "INSERT INTO source_lifecycle_runtime "
                "(canonical_id, local_missing_first_observed_utc, local_missing_last_confirmed_utc, "
                "missing_confirmation_count, lease_owner, lease_expires_utc) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "confluence:123",
                    "2026-03-20T00:00:00+00:00",
                    "2026-03-20T01:00:00+00:00",
                    2,
                    "daemon-owner",
                    "2099-01-01T00:00:00+00:00",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        migrated = state_module._connect(tmp_path)
        try:
            schema_version = migrated.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            row = migrated.execute(
                "SELECT canonical_id, missing_confirmation_count, last_missing_confirmation_session_id, lease_owner "
                "FROM source_lifecycle_runtime WHERE canonical_id = 'confluence:123'"
            ).fetchone()
        finally:
            migrated.close()

        assert schema_version is not None
        assert schema_version[0] == str(RUNTIME_DB_SCHEMA_VERSION)
        assert row == ("confluence:123", 2, None, "daemon-owner")

    def test_provisional_pre_narrowing_v25_runtime_db_is_rebuilt(self, tmp_path: Path) -> None:
        db_path = state_module.RUNTIME_DB_FILE
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            conn.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '25')")
            conn.execute(
                "CREATE TABLE dirty_knowledge_paths (knowledge_path TEXT PRIMARY KEY, reason TEXT, updated_utc TEXT)"
            )
            conn.execute("CREATE TABLE sync_cache (canonical_id TEXT PRIMARY KEY)")
            conn.execute("CREATE TABLE regen_locks (knowledge_path TEXT PRIMARY KEY, regen_status TEXT NOT NULL)")
            conn.execute(
                "CREATE TABLE token_events ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "session_id TEXT NOT NULL, "
                "operation_type TEXT NOT NULL, "
                "success INTEGER NOT NULL, "
                "created_utc TEXT NOT NULL)"
            )
            conn.execute(
                "INSERT INTO token_events (session_id, operation_type, success, created_utc) "
                "VALUES ('sess-1', 'regen', 1, '2026-03-18T00:00:00+00:00')"
            )
            conn.commit()
        finally:
            conn.close()

        rebuilt = state_module._connect(tmp_path)
        try:
            runtime_tables = rebuilt.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT IN ('sqlite_sequence') ORDER BY name"
            ).fetchall()
            token_rows = rebuilt.execute("SELECT COUNT(*) FROM token_events").fetchone()
        finally:
            rebuilt.close()

        assert runtime_tables == [
            ("child_discovery_requests",),
            ("meta",),
            ("operational_events",),
            ("regen_locks",),
            ("source_lifecycle_runtime",),
            ("sync_polling",),
            ("token_events",),
        ]
        assert token_rows == (0,)

    def test_fresh_runtime_db_excludes_legacy_documents_table(self, tmp_path: Path) -> None:
        conn = state_module._connect(tmp_path)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        finally:
            conn.close()

        assert "documents" not in tables


class TestInsightStatePaths:
    def test_save_and_load_uses_colocated_insight_state_path(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge" / "area").mkdir(parents=True)

        save_insight_state(
            tmp_path,
            InsightState(
                knowledge_path="area",
                content_hash="content-hash",
                summary_hash="summary-hash",
                structure_hash="structure-hash",
            ),
        )

        loaded = load_insight_state(tmp_path, "area")

        assert loaded is not None
        assert loaded.content_hash == "content-hash"
        assert (tmp_path / "knowledge" / "area" / ".brain-sync" / "insights" / "insight-state.json").is_file()

    def test_root_area_roundtrip(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge").mkdir(parents=True)

        save_insight_state(
            tmp_path,
            InsightState(
                knowledge_path="",
                content_hash="root-content",
                structure_hash="root-structure",
            ),
        )

        loaded = load_insight_state(tmp_path, "")
        all_states = load_all_insight_states(tmp_path)

        assert loaded is not None
        assert loaded.content_hash == "root-content"
        assert any(state.knowledge_path == "" for state in all_states)
        assert (tmp_path / "knowledge" / ".brain-sync" / "insights" / "insight-state.json").is_file()

    def test_save_regen_lock_does_not_touch_portable_insight_state(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge" / "area").mkdir(parents=True)

        save_insight_state(
            tmp_path,
            InsightState(
                knowledge_path="area",
                content_hash="content-hash",
                summary_hash="summary-hash",
                structure_hash="structure-hash",
                last_regen_utc="2026-03-17T00:00:00Z",
            ),
        )
        sidecar_path = tmp_path / "knowledge" / "area" / ".brain-sync" / "insights" / "insight-state.json"
        before_bytes = sidecar_path.read_bytes()

        with patch(
            "brain_sync.brain.sidecar.write_regen_meta",
            side_effect=AssertionError("portable state should not be rewritten"),
        ):
            save_regen_lock(
                tmp_path,
                RegenLock(
                    knowledge_path="area",
                    regen_status="idle",
                ),
            )
            assert acquire_regen_ownership(tmp_path, "area", "owner-1")
            save_regen_lock(
                tmp_path,
                RegenLock(
                    knowledge_path="area",
                    regen_status="running",
                    regen_started_utc="2026-03-17T01:00:00Z",
                    owner_id="owner-1",
                ),
            )

        loaded = load_insight_state(tmp_path, "area")

        assert loaded is not None
        assert loaded.content_hash == "content-hash"
        assert loaded.last_regen_utc == "2026-03-17T00:00:00Z"
        assert loaded.regen_status == "running"
        assert loaded.owner_id == "owner-1"
        assert sidecar_path.read_bytes() == before_bytes

    def test_save_insight_state_does_not_write_runtime_lock_when_portable_write_fails(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge" / "area").mkdir(parents=True)

        with patch(
            "brain_sync.brain.repository.BrainRepository.save_portable_insight_state",
            side_effect=OSError("disk full"),
        ):
            with pytest.raises(OSError, match="disk full"):
                save_insight_state(
                    tmp_path,
                    InsightState(
                        knowledge_path="area",
                        content_hash="content-hash",
                        summary_hash="summary-hash",
                        structure_hash="structure-hash",
                        regen_status="running",
                        regen_started_utc="2026-03-17T01:00:00Z",
                        owner_id="owner-1",
                    ),
                )

        assert load_insight_state(tmp_path, "area") is None

    def test_delete_insight_state_does_not_remove_runtime_lock_when_portable_delete_fails(self, tmp_path: Path) -> None:
        (tmp_path / "knowledge" / "area").mkdir(parents=True)

        save_insight_state(
            tmp_path,
            InsightState(
                knowledge_path="area",
                content_hash="content-hash",
                summary_hash="summary-hash",
                structure_hash="structure-hash",
            ),
        )

        with patch(
            "brain_sync.brain.repository.BrainRepository.delete_portable_insight_state",
            side_effect=OSError("permission denied"),
        ):
            with pytest.raises(OSError, match="permission denied"):
                delete_insight_state(tmp_path, "area")

        loaded = load_insight_state(tmp_path, "area")

        assert loaded is not None
        assert loaded.content_hash == "content-hash"
        assert loaded.regen_status == "idle"


class TestApplicationInsightProjection:
    def test_load_all_insight_states_merges_sidecar_and_runtime_sources(self, tmp_path: Path) -> None:
        from brain_sync.brain.repository import BrainRepository

        (tmp_path / "knowledge" / "area").mkdir(parents=True)
        repository = BrainRepository(tmp_path)
        repository.save_portable_insight_state(
            "area",
            content_hash="content-hash",
            summary_hash="summary-hash",
            structure_hash="structure-hash",
            last_regen_utc="2026-03-17T00:00:00Z",
        )
        save_regen_lock(
            tmp_path,
            RegenLock(knowledge_path="lock-only", regen_status="idle"),
        )
        assert acquire_regen_ownership(tmp_path, "lock-only", "owner-1")
        save_regen_lock(
            tmp_path,
            RegenLock(
                knowledge_path="lock-only",
                regen_status="running",
                regen_started_utc="2026-03-17T01:00:00Z",
            ),
        )

        states = {state.knowledge_path: state for state in load_all_insight_states(tmp_path)}

        assert states["area"].content_hash == "content-hash"
        assert states["area"].regen_status == "idle"
        assert states["lock-only"].content_hash is None
        assert states["lock-only"].regen_status == "running"
        assert states["lock-only"].owner_id == "owner-1"


class TestRegenLockOwnership:
    def test_same_owner_update_is_allowed(self, tmp_path: Path) -> None:
        save_regen_lock(
            tmp_path,
            RegenLock(knowledge_path="area", regen_status="idle"),
        )
        assert acquire_regen_ownership(tmp_path, "area", "owner-1")

        save_regen_lock(
            tmp_path,
            RegenLock(
                knowledge_path="area",
                regen_status="failed",
                regen_started_utc="2026-03-18T00:00:00+00:00",
                owner_id="owner-1",
                error_reason="same owner update",
            ),
        )

        loaded = load_insight_state(tmp_path, "area")
        assert loaded is not None
        assert loaded.owner_id == "owner-1"
        assert loaded.regen_status == "failed"

    def test_owner_preserving_write_keeps_existing_owner(self, tmp_path: Path) -> None:
        save_regen_lock(
            tmp_path,
            RegenLock(knowledge_path="area", regen_status="idle"),
        )
        assert acquire_regen_ownership(tmp_path, "area", "owner-1")

        save_regen_lock(
            tmp_path,
            RegenLock(
                knowledge_path="area",
                regen_status="failed",
                error_reason="owner preserved",
            ),
        )

        loaded = load_insight_state(tmp_path, "area")
        assert loaded is not None
        assert loaded.owner_id == "owner-1"
        assert loaded.regen_status == "failed"

    def test_terminal_release_clears_owner_and_allows_reacquire(self, tmp_path: Path) -> None:
        save_regen_lock(
            tmp_path,
            RegenLock(knowledge_path="area", regen_status="idle"),
        )
        assert acquire_regen_ownership(tmp_path, "area", "owner-1")

        assert release_regen_ownership(
            tmp_path,
            "area",
            "owner-1",
            regen_status="idle",
            error_reason=None,
        )

        loaded = load_insight_state(tmp_path, "area")
        assert loaded is not None
        assert loaded.owner_id is None
        assert loaded.regen_status == "idle"
        assert acquire_regen_ownership(tmp_path, "area", "owner-2")

    def test_terminal_release_is_owner_guarded(self, tmp_path: Path) -> None:
        save_regen_lock(
            tmp_path,
            RegenLock(knowledge_path="area", regen_status="idle"),
        )
        assert acquire_regen_ownership(tmp_path, "area", "owner-1")

        assert not release_regen_ownership(
            tmp_path,
            "area",
            "owner-2",
            regen_status="failed",
            error_reason="should not release",
        )

        loaded = load_insight_state(tmp_path, "area")
        assert loaded is not None
        assert loaded.owner_id == "owner-1"
        assert loaded.regen_status == "running"

    def test_conflicting_owner_update_is_rejected(self, tmp_path: Path) -> None:
        save_regen_lock(
            tmp_path,
            RegenLock(knowledge_path="area", regen_status="idle"),
        )
        assert acquire_regen_ownership(tmp_path, "area", "owner-1")

        with pytest.raises(RegenOwnershipError, match="cannot transfer ownership"):
            save_regen_lock(
                tmp_path,
                RegenLock(
                    knowledge_path="area",
                    regen_status="running",
                    owner_id="owner-2",
                ),
            )

    def test_new_owner_claim_requires_acquire_path(self, tmp_path: Path) -> None:
        with pytest.raises(RegenOwnershipError, match="cannot claim ownership"):
            save_regen_lock(
                tmp_path,
                RegenLock(
                    knowledge_path="area",
                    regen_status="running",
                    owner_id="owner-1",
                ),
            )

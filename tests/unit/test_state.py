from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import brain_sync.state as state_module
from brain_sync.layout import RUNTIME_DB_SCHEMA_VERSION
from brain_sync.manifest import SourceManifest, write_source_manifest
from brain_sync.state import (
    InsightState,
    RegenLock,
    SourceState,
    SyncState,
    load_all_insight_states,
    load_insight_state,
    load_state,
    read_daemon_status,
    save_insight_state,
    save_regen_lock,
    save_state,
    write_daemon_status,
)

pytestmark = pytest.mark.unit


def _write_manifest(root: Path, cid: str, *, target_path: str = "", materialized_path: str = "") -> None:
    write_source_manifest(
        root,
        SourceManifest(
            version=1,
            canonical_id=cid,
            source_url="https://example.com",
            source_type="confluence",
            materialized_path=materialized_path,
            sync_attachments=False,
            target_path=target_path,
        ),
    )


class TestRuntimeStateV23:
    def test_save_and_load_round_trip_uses_runtime_db(self, tmp_path: Path) -> None:
        _write_manifest(tmp_path, "confluence:123", target_path="area", materialized_path="area/c123-page.md")

        state = SyncState()
        state.sources["confluence:123"] = SourceState(
            canonical_id="confluence:123",
            source_url="https://example.com",
            source_type="confluence",
            last_checked_utc="2026-01-01T00:00:00Z",
            last_changed_utc="2026-01-01T00:00:00Z",
            current_interval_secs=3600,
            content_hash="abc123",
            metadata_fingerprint="42",
        )

        save_state(tmp_path, state)
        loaded = load_state(tmp_path)

        assert "confluence:123" in loaded.sources
        assert loaded.sources["confluence:123"].content_hash == "abc123"
        assert state_module.RUNTIME_DB_FILE.exists()
        assert not (tmp_path / ".sync-state.sqlite").exists()
        assert not state_module.RUNTIME_DB_FILE.is_relative_to(tmp_path)

    def test_load_missing_db_returns_current_schema_version(self, tmp_path: Path) -> None:
        loaded = load_state(tmp_path)
        assert loaded.sources == {}
        assert loaded.version == RUNTIME_DB_SCHEMA_VERSION

    def test_daemon_status_is_json_file(self, tmp_path: Path) -> None:
        write_daemon_status(tmp_path, pid=1234, status="starting")
        write_daemon_status(tmp_path, pid=1234, status="ready")

        data = json.loads(state_module.DAEMON_STATUS_FILE.read_text(encoding="utf-8"))
        loaded = read_daemon_status(tmp_path)

        assert data["pid"] == 1234
        assert data["status"] == "ready"
        assert loaded is not None
        assert loaded["status"] == "ready"


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
            "brain_sync.sidecar.write_regen_meta",
            side_effect=AssertionError("portable state should not be rewritten"),
        ):
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

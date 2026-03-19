"""Tests for manifest-authoritative load_state() merge logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.source_state import SourceState, SyncState, load_state, save_state
from brain_sync.brain.manifest import (
    MANIFEST_VERSION,
    SourceManifest,
    ensure_manifest_dir,
    write_source_manifest,
)
from brain_sync.runtime.repository import _has_sync_progress

pytestmark = pytest.mark.unit

CONFLUENCE_URL = "https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"
CONFLUENCE_URL_2 = "https://example.atlassian.net/wiki/spaces/TEAM/pages/67890/Other"
CONFLUENCE_CID_2 = "confluence:67890"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / ".brain-sync" / "sources").mkdir(parents=True)
    (root / ".brain-sync" / "brain.json").write_text('{"version": 1}\n', encoding="utf-8")
    from brain_sync.runtime.repository import _connect

    conn = _connect(root)
    conn.close()
    return root


def _write_manifest(root: Path, cid: str, url: str, **kwargs: object) -> None:
    data: dict[str, object] = {
        "version": MANIFEST_VERSION,
        "canonical_id": cid,
        "source_url": url,
        "source_type": "confluence",
        "sync_attachments": kwargs.get("sync_attachments", False),
        "knowledge_path": kwargs.get("knowledge_path", "area/c12345-page.md"),
        "knowledge_state": kwargs.get("knowledge_state", "materialized"),
        "content_hash": kwargs.get("content_hash", "sha256:abc123"),
        "remote_fingerprint": kwargs.get("remote_fingerprint", "fp123"),
        "materialized_utc": kwargs.get("materialized_utc", "2026-03-14T09:00:00+00:00"),
        "missing_since_utc": kwargs.get("missing_since_utc"),
    }
    if data["knowledge_state"] == "awaiting":
        data["content_hash"] = None
        data["remote_fingerprint"] = None
        data["materialized_utc"] = None
    write_source_manifest(root, SourceManifest(**data))


class TestLoadStateMerge:
    def test_merges_manifest_truth_with_runtime_polling(self, brain: Path) -> None:
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, knowledge_path="eng/c12345-page.md")

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            knowledge_path="eng/c12345-page.md",
            knowledge_state="materialized",
            last_checked_utc="2026-03-14T10:00:00+00:00",
            next_check_utc="2026-03-14T11:00:00+00:00",
            interval_seconds=3600,
        )
        save_state(brain, state)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.knowledge_path == "eng/c12345-page.md"
        assert ss.knowledge_state == "materialized"
        assert ss.content_hash == "sha256:abc123"
        assert ss.remote_fingerprint == "fp123"
        assert ss.last_checked_utc == "2026-03-14T10:00:00+00:00"
        assert ss.next_check_utc == "2026-03-14T11:00:00+00:00"

    def test_manifest_only_source_no_db(self, brain: Path) -> None:
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, knowledge_path="area/c12345-page.md")

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.knowledge_path == "area/c12345-page.md"
        assert ss.target_path == "area"
        assert ss.last_checked_utc is None

    def test_missing_sources_are_excluded(self, brain: Path) -> None:
        ensure_manifest_dir(brain)
        _write_manifest(
            brain,
            CONFLUENCE_CID,
            CONFLUENCE_URL,
            knowledge_state="missing",
            missing_since_utc="2026-03-14T12:00:00+00:00",
        )

        loaded = load_state(brain)
        assert CONFLUENCE_CID not in loaded.sources

    def test_db_orphan_is_ignored(self, brain: Path) -> None:
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID_2, CONFLUENCE_URL_2, knowledge_path="other/c67890-page.md")

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            knowledge_path="ghost/c12345-page.md",
            knowledge_state="materialized",
            last_checked_utc="2026-03-14T10:00:00+00:00",
        )
        save_state(brain, state)

        loaded = load_state(brain)
        assert CONFLUENCE_CID not in loaded.sources
        assert CONFLUENCE_CID_2 in loaded.sources

    def test_target_path_is_derived_from_knowledge_path(self, brain: Path) -> None:
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, knowledge_path="eng/arch/c12345-page.md")

        loaded = load_state(brain)
        assert loaded.sources[CONFLUENCE_CID].target_path == "eng/arch"


class TestHasSyncProgress:
    def test_no_progress(self) -> None:
        ss = SourceState(canonical_id="c:1", source_url="u", source_type="t")
        assert _has_sync_progress(ss) is False

    def test_has_last_checked(self) -> None:
        ss = SourceState(canonical_id="c:1", source_url="u", source_type="t", last_checked_utc="2026-01-01")
        assert _has_sync_progress(ss) is True

    def test_has_next_check(self) -> None:
        ss = SourceState(canonical_id="c:1", source_url="u", source_type="t", next_check_utc="2026-01-01")
        assert _has_sync_progress(ss) is True

    def test_portable_fields_do_not_trigger_runtime_persistence(self) -> None:
        ss = SourceState(
            canonical_id="c:1",
            source_url="u",
            source_type="t",
            knowledge_path="area/c1.md",
            knowledge_state="materialized",
            content_hash="sha256:abc",
            remote_fingerprint="fp",
            materialized_utc="2026-03-14T10:00:00+00:00",
        )
        assert _has_sync_progress(ss) is False


class TestSaveStateProgressGuard:
    def test_no_progress_source_not_inserted_into_db(self, brain: Path) -> None:
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL)

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            knowledge_path="area/c12345-page.md",
            knowledge_state="materialized",
        )
        save_state(brain, state)

        from brain_sync.runtime.repository import load_sync_progress

        assert CONFLUENCE_CID not in load_sync_progress(brain)

    def test_polling_progress_is_inserted_into_db(self, brain: Path) -> None:
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL)

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            knowledge_path="area/c12345-page.md",
            knowledge_state="materialized",
            last_checked_utc="2026-03-14T10:00:00+00:00",
            next_check_utc="2026-03-14T11:00:00+00:00",
            interval_seconds=3600,
        )
        save_state(brain, state)

        from brain_sync.runtime.repository import load_sync_progress

        db_sources = load_sync_progress(brain)
        assert CONFLUENCE_CID in db_sources
        assert db_sources[CONFLUENCE_CID].last_checked_utc == "2026-03-14T10:00:00+00:00"

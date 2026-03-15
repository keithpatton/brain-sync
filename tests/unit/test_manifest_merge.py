"""Tests for manifest-authoritative load_state() merge logic."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.manifest import (
    MANIFEST_VERSION,
    SourceManifest,
    ensure_manifest_dir,
    write_source_manifest,
)
from brain_sync.pipeline import extract_source_id
from brain_sync.state import (
    SourceState,
    SyncState,
    _has_sync_progress,
    load_state,
    save_state,
)

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
    from brain_sync.state import _connect

    conn = _connect(root)
    conn.close()
    return root


def _write_manifest(root: Path, cid: str, url: str, **kwargs) -> None:
    write_source_manifest(
        root,
        SourceManifest(
            manifest_version=MANIFEST_VERSION,
            canonical_id=cid,
            source_url=url,
            source_type="confluence",
            materialized_path=kwargs.get("materialized_path", ""),
            fetch_children=kwargs.get("fetch_children", False),
            sync_attachments=kwargs.get("sync_attachments", False),
            target_path=kwargs.get("target_path", ""),
            child_path=kwargs.get("child_path"),
            status=kwargs.get("status", "active"),
            sync_hint=kwargs.get("sync_hint"),
        ),
    )


class TestLoadStateMerge:
    def test_merges_manifest_intent_with_db_progress(self, brain: Path):
        """Manifest provides intent fields, DB provides progress fields."""
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, target_path="eng", fetch_children=True)

        # Save progress in DB
        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            last_checked_utc="2026-03-14T10:00:00",
            content_hash="abc123",
            target_path="eng",
        )
        save_state(brain, state)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        # Durable intent from manifest
        assert ss.target_path == "eng"
        # Progress from DB
        assert ss.last_checked_utc == "2026-03-14T10:00:00"
        assert ss.content_hash == "abc123"

    def test_manifest_only_source_no_db(self, brain: Path):
        """Manifest-only source (no DB row) → empty progress, triggers immediate schedule."""
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, target_path="area")

        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.target_path == "area"
        assert ss.last_checked_utc is None
        assert ss.content_hash is None

    def test_db_orphan_excluded_when_manifests_exist(self, brain: Path):
        """DB-only source (no manifest) is excluded when manifests exist."""
        ensure_manifest_dir(brain)
        # Create a different manifest so the dir is non-empty (prevents bootstrap)
        _write_manifest(brain, CONFLUENCE_CID_2, CONFLUENCE_URL_2, target_path="other")

        # Only in DB, not in manifests
        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            last_checked_utc="2026-03-14T10:00:00",
        )
        save_state(brain, state)

        loaded = load_state(brain)
        assert CONFLUENCE_CID not in loaded.sources
        # The manifested source is present
        assert CONFLUENCE_CID_2 in loaded.sources

    def test_manifest_wins_for_intent_fields(self, brain: Path):
        """When manifest and DB disagree on intent fields, manifest wins."""
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, target_path="new-area", sync_attachments=True)

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="old-area",
            sync_attachments=False,
            last_checked_utc="2026-03-14T10:00:00",
        )
        save_state(brain, state)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.target_path == "new-area"
        assert ss.sync_attachments is True

    def test_db_wins_for_progress_fields(self, brain: Path):
        """DB progress fields override empty manifest-only state."""
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, target_path="area")

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            last_checked_utc="2026-03-14T10:00:00",
            content_hash="abc",
            metadata_fingerprint="fp123",
            next_check_utc="2026-03-14T11:00:00",
            interval_seconds=3600,
        )
        save_state(brain, state)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.last_checked_utc == "2026-03-14T10:00:00"
        assert ss.content_hash == "abc"
        assert ss.metadata_fingerprint == "fp123"
        assert ss.next_check_utc == "2026-03-14T11:00:00"
        assert ss.interval_seconds == 3600

    def test_target_path_from_manifest_field(self, brain: Path):
        """Explicit target_path field in manifest is used."""
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, target_path="explicit/path")

        loaded = load_state(brain)
        assert loaded.sources[CONFLUENCE_CID].target_path == "explicit/path"

    def test_target_path_derived_from_materialized_path(self, brain: Path):
        """When target_path is empty, derive from materialized_path parent."""
        ensure_manifest_dir(brain)
        _write_manifest(
            brain,
            CONFLUENCE_CID,
            CONFLUENCE_URL,
            materialized_path="eng/arch/c12345-page.md",
            target_path="",  # no explicit target
        )

        loaded = load_state(brain)
        assert loaded.sources[CONFLUENCE_CID].target_path == "eng/arch"

    def test_target_path_for_knowledge_root_file(self, brain: Path):
        """File at knowledge root: materialized_path has no parent dir → target_path is empty."""
        ensure_manifest_dir(brain)
        _write_manifest(
            brain,
            CONFLUENCE_CID,
            CONFLUENCE_URL,
            materialized_path="c12345-page.md",
            target_path="",
        )

        loaded = load_state(brain)
        assert loaded.sources[CONFLUENCE_CID].target_path == ""

    def test_empty_materialized_with_explicit_target(self, brain: Path):
        """Empty materialized_path + explicit target_path → target_path preserved."""
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, target_path="desired/area")

        loaded = load_state(brain)
        assert loaded.sources[CONFLUENCE_CID].target_path == "desired/area"

    def test_missing_status_excluded(self, brain: Path):
        """Missing-status manifests are excluded from load_state() results."""
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, status="missing", target_path="area")

        loaded = load_state(brain)
        assert CONFLUENCE_CID not in loaded.sources


class TestExtractSourceId:
    def test_extracts_cid_from_header(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text(
            "<!-- brain-sync-source: confluence:12345 -->\n<!-- brain-sync-managed: local edits -->\n\n# Title\n"
        )
        assert extract_source_id(f) == "confluence:12345"

    def test_returns_none_for_no_header(self, tmp_path: Path):
        f = tmp_path / "test.md"
        f.write_text("# Regular markdown\nNo header here.\n")
        assert extract_source_id(f) is None

    def test_returns_none_for_missing_file(self, tmp_path: Path):
        f = tmp_path / "nonexistent.md"
        assert extract_source_id(f) is None


class TestHasSyncProgress:
    def test_no_progress(self):
        ss = SourceState(canonical_id="c:1", source_url="u", source_type="t")
        assert _has_sync_progress(ss) is False

    def test_has_last_checked(self):
        ss = SourceState(canonical_id="c:1", source_url="u", source_type="t", last_checked_utc="2026-01-01")
        assert _has_sync_progress(ss) is True

    def test_has_content_hash(self):
        ss = SourceState(canonical_id="c:1", source_url="u", source_type="t", content_hash="abc")
        assert _has_sync_progress(ss) is True

    def test_has_metadata_fingerprint(self):
        ss = SourceState(canonical_id="c:1", source_url="u", source_type="t", metadata_fingerprint="fp")
        assert _has_sync_progress(ss) is True

    def test_has_next_check(self):
        ss = SourceState(canonical_id="c:1", source_url="u", source_type="t", next_check_utc="2026-01-01")
        assert _has_sync_progress(ss) is True


class TestSaveStateProgressGuard:
    def test_no_progress_source_not_inserted_into_db(self, brain: Path):
        """save_state() skips INSERT for sources with no sync progress."""
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, target_path="area")

        # Save a no-progress source — should NOT create a DB row
        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
        )
        save_state(brain, state)

        # Verify no row exists in DB
        from brain_sync.state import _load_db_sync_progress

        db_sources = _load_db_sync_progress(brain)
        assert CONFLUENCE_CID not in db_sources

    def test_progress_source_inserted_into_db(self, brain: Path):
        """save_state() inserts sources that have real sync progress."""
        ensure_manifest_dir(brain)
        _write_manifest(brain, CONFLUENCE_CID, CONFLUENCE_URL, target_path="area")

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
            last_checked_utc="2026-03-14T10:00:00",
            content_hash="abc123",
        )
        save_state(brain, state)

        from brain_sync.state import _load_db_sync_progress

        db_sources = _load_db_sync_progress(brain)
        assert CONFLUENCE_CID in db_sources
        assert db_sources[CONFLUENCE_CID].content_hash == "abc123"

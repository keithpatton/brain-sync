"""Integration tests for manifest-authoritative read path."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.source_state import SourceState, load_state, save_state
from brain_sync.application.sources import (
    add_source,
    list_sources,
    reconcile_sources,
)
from brain_sync.brain.fileops import atomic_write_bytes
from brain_sync.brain.manifest import (
    SyncHint,
    mark_manifest_missing,
    read_source_manifest,
    write_source_manifest,
)
from brain_sync.brain.tree import normalize_path
from brain_sync.sync.pipeline import prepend_managed_header
from brain_sync.sync.watcher import FolderMove, mirror_folder_move

pytestmark = pytest.mark.integration

CONFLUENCE_URL = "https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"
CONFLUENCE_URL_2 = "https://example.atlassian.net/wiki/spaces/TEAM/pages/67890/Other"
CONFLUENCE_CID_2 = "confluence:67890"


def _long_relative_path(root: Path, filename: str, *, min_length: int = 280) -> Path:
    parts: list[str] = []
    index = 0
    while len(str(root / Path(*parts) / filename)) <= min_length:
        parts.append(f"segment-{index:02d}-with-extra-length-for-windows")
        index += 1
    return Path(*parts) / filename


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    return root


def _create_synced_file(brain: Path, cid: str, area: str, filename: str, body: str = "content") -> Path:
    """Create a file with managed header as if synced by the pipeline."""
    d = brain / "knowledge" / area
    d.mkdir(parents=True, exist_ok=True)
    f = d / filename
    md = prepend_managed_header(cid, body)
    f.write_text(md, encoding="utf-8")
    return f


class TestSeedFromHint:
    def test_matching_file_seeds_at_normal_cadence(self, brain: Path):
        """Sync hint matches local file → seeded with content_hash and next_check_utc."""
        from brain_sync.brain.fileops import content_hash

        body = "# Test Page\n\nContent here.\n"
        body_hash = content_hash(body.encode("utf-8"))

        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        # Simulate a synced file by writing managed-header file + updating manifest
        _create_synced_file(brain, CONFLUENCE_CID, "area", "c12345-test-page.md", body)
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "area/c12345-test-page.md"
        m.sync_hint = SyncHint(content_hash=body_hash, last_synced_utc="2026-03-14T10:00:00+00:00")
        write_source_manifest(brain, m)

        # Delete DB to force seed-from-hint path
        db_path = brain / ".sync-state.sqlite"
        db_path.unlink(missing_ok=True)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.content_hash == body_hash
        assert ss.last_checked_utc == "2026-03-14T10:00:00+00:00"
        assert ss.next_check_utc is not None
        assert ss.interval_seconds == 1800

    def test_mismatched_file_empty_progress(self, brain: Path):
        """Sync hint doesn't match local file → empty progress (schedule immediate)."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        _create_synced_file(brain, CONFLUENCE_CID, "area", "c12345-test-page.md", "different content")
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "area/c12345-test-page.md"
        m.sync_hint = SyncHint(content_hash="wrong_hash", last_synced_utc="2026-03-14T10:00:00")
        write_source_manifest(brain, m)

        db_path = brain / ".sync-state.sqlite"
        db_path.unlink(missing_ok=True)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.content_hash is None
        assert ss.next_check_utc is None

    def test_missing_file_empty_progress(self, brain: Path):
        """Sync hint but file doesn't exist → empty progress."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "area/c12345-test-page.md"
        m.sync_hint = SyncHint(content_hash="abc", last_synced_utc="2026-03-14T10:00:00")
        write_source_manifest(brain, m)

        db_path = brain / ".sync-state.sqlite"
        db_path.unlink(missing_ok=True)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.content_hash is None

    def test_empty_materialized_path_no_file_read(self, brain: Path):
        """Empty materialized_path → seed_from_hint skips file read."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        # materialized_path is already "" from add_source
        m.sync_hint = SyncHint(content_hash="abc", last_synced_utc="2026-03-14T10:00:00")
        write_source_manifest(brain, m)

        db_path = brain / ".sync-state.sqlite"
        db_path.unlink(missing_ok=True)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.content_hash is None  # No file read attempted


class TestReconcileManifestReadPath:
    def test_moved_file_found_via_identity_header(self, brain: Path):
        """Tier-2: file moved but has identity header → found."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old")
        _create_synced_file(brain, CONFLUENCE_CID, "old", "c12345-test-page.md")
        # Update manifest materialized_path to simulate a synced source
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "old/c12345-test-page.md"
        write_source_manifest(brain, m)

        # Move file to new location (rename breaks tier-1 match)
        (brain / "knowledge" / "old" / "c12345-test-page.md").rename(brain / "knowledge" / "old" / "renamed-page.md")

        result = reconcile_sources(root=brain)
        # File found via identity header in same dir
        assert result.not_found == []

    def test_moved_to_different_dir_and_renamed_found_via_header(self, brain: Path):
        """Tier-2: file moved to different dir AND renamed (no prefix) → found via header scan."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old")
        _create_synced_file(brain, CONFLUENCE_CID, "old", "c12345-test-page.md")
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "old/c12345-test-page.md"
        write_source_manifest(brain, m)

        # Move to a completely different directory AND remove the canonical prefix
        new_dir = brain / "knowledge" / "new-area" / "sub"
        new_dir.mkdir(parents=True)
        (brain / "knowledge" / "old" / "c12345-test-page.md").rename(new_dir / "renamed-page.md")

        result = reconcile_sources(root=brain)
        # File found via identity header scan across all of knowledge/
        assert result.not_found == []
        assert result.marked_missing == []

    def test_two_stage_missing_first_marks(self, brain: Path):
        """First reconcile marks missing; file still exists in manifest."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "area/c12345-test-page.md"
        write_source_manifest(brain, m)
        # File doesn't exist on disk

        result = reconcile_sources(root=brain)
        assert CONFLUENCE_CID in result.marked_missing
        # Manifest still exists
        m2 = read_source_manifest(brain, CONFLUENCE_CID)
        assert m2 is not None
        assert m2.status == "missing"

    def test_two_stage_missing_second_deletes(self, brain: Path):
        """Second reconcile of already-missing source → deletes manifest."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "area/c12345-test-page.md"
        write_source_manifest(brain, m)

        # First reconcile marks missing
        reconcile_sources(root=brain)
        # Second reconcile deletes
        result = reconcile_sources(root=brain)
        assert CONFLUENCE_CID in result.deleted
        assert read_source_manifest(brain, CONFLUENCE_CID) is None

    def test_reappearing_file_clears_missing(self, brain: Path):
        """File reappears during grace period → missing status cleared."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "area/c12345-test-page.md"
        write_source_manifest(brain, m)

        # Mark missing
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        # Now create the file
        _create_synced_file(brain, CONFLUENCE_CID, "area", "c12345-test-page.md")

        result = reconcile_sources(root=brain)
        assert CONFLUENCE_CID in result.reappeared
        m2 = read_source_manifest(brain, CONFLUENCE_CID)
        assert m2 is not None
        assert m2.status == "active"

    def test_unmaterialized_source_skipped(self, brain: Path):
        """Active source with empty materialized_path and no file → unchanged (not missing)."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")

        result = reconcile_sources(root=brain)
        assert result.unchanged == 1
        assert result.not_found == []
        assert result.marked_missing == []

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_materialized_overlong_path_is_not_marked_missing(self, brain: Path):
        rel = _long_relative_path(brain / "knowledge", "c12345-test-page.md")
        target_path = normalize_path(rel.parent)
        add_source(root=brain, url=CONFLUENCE_URL, target_path=target_path)

        content = prepend_managed_header(CONFLUENCE_CID, "content")
        atomic_write_bytes(brain / "knowledge" / rel, content.encode("utf-8"))

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.materialized_path = normalize_path(rel)
        write_source_manifest(brain, manifest)

        result = reconcile_sources(root=brain)

        assert result.marked_missing == []
        assert result.not_found == []
        assert result.unchanged == 1

    def test_orphan_db_rows_pruned(self, brain: Path):
        """DB rows with no corresponding manifest are pruned during reconcile."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        # Add a source only in DB (no manifest)
        state = load_state(brain)
        state.sources[CONFLUENCE_CID_2] = SourceState(
            canonical_id=CONFLUENCE_CID_2,
            source_url=CONFLUENCE_URL_2,
            source_type="confluence",
            last_checked_utc="2026-03-14T10:00:00",
        )
        save_state(brain, state)

        result = reconcile_sources(root=brain)
        assert result.orphan_rows_pruned == 1

    def test_list_sources_manifest_authoritative(self, brain: Path):
        """list_sources returns manifest-authoritative data."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="eng")
        sources = list_sources(root=brain)
        assert len(sources) == 1
        assert sources[0].canonical_id == CONFLUENCE_CID
        assert sources[0].target_path == "eng"

    def test_list_sources_after_db_delete(self, brain: Path):
        """list_sources still works after DB deletion."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="eng")
        (brain / ".sync-state.sqlite").unlink(missing_ok=True)

        sources = list_sources(root=brain)
        assert len(sources) == 1
        assert sources[0].canonical_id == CONFLUENCE_CID
        assert sources[0].target_path == "eng"

    def test_missing_source_not_in_list(self, brain: Path):
        """Missing-status source doesn't appear in list_sources."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        sources = list_sources(root=brain)
        assert len(sources) == 0


class TestMirrorFolderMoveManifests:
    def test_skips_unmaterialized(self, brain: Path):
        """mirror_folder_move skips manifests with empty materialized_path."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-dir")
        # manifest has materialized_path=""

        k_old = brain / "knowledge" / "old-dir"
        k_old.mkdir(parents=True, exist_ok=True)
        k_new = brain / "knowledge" / "new-dir"

        move = FolderMove(src=k_old.resolve(), dest=k_new.resolve())
        mirror_folder_move(brain, move)

        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        # target_path updated (it matched old-dir)
        assert m.target_path == "new-dir"
        # materialized_path still empty (unmaterialized)
        assert m.materialized_path == ""

    def test_updates_materialized_and_target(self, brain: Path):
        """mirror_folder_move updates both manifest fields when file is materialized."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-dir")
        _create_synced_file(brain, CONFLUENCE_CID, "old-dir", "c12345-test-page.md")
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "old-dir/c12345-test-page.md"
        write_source_manifest(brain, m)

        k_old = (brain / "knowledge" / "old-dir").resolve()
        k_new = brain / "knowledge" / "new-dir"
        import shutil

        shutil.move(str(k_old), str(k_new))

        move = FolderMove(src=k_old, dest=k_new.resolve())
        mirror_folder_move(brain, move)

        m2 = read_source_manifest(brain, CONFLUENCE_CID)
        assert m2 is not None
        assert m2.materialized_path == "new-dir/c12345-test-page.md"
        assert m2.target_path == "new-dir"

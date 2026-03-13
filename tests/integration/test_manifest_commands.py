"""Integration tests: source commands write manifests alongside DB."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.commands.sources import (
    add_source,
    move_source,
    reconcile_sources,
    remove_source,
    update_source,
)
from brain_sync.manifest import read_all_source_manifests, read_source_manifest
from brain_sync.state import _connect, load_state

pytestmark = pytest.mark.integration

CONFLUENCE_URL = "https://acme.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    """Create a brain with .brain-sync/sources/ and SQLite initialized."""
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / "insights").mkdir()
    (root / ".brain-sync" / "sources").mkdir(parents=True)
    conn = _connect(root)
    conn.close()
    return root


class TestAddSourceWritesManifest:
    def test_creates_manifest_on_add(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        assert manifest.canonical_id == CONFLUENCE_CID
        assert manifest.source_url == CONFLUENCE_URL
        assert manifest.source_type == "confluence"
        assert manifest.sync_attachments is False
        assert manifest.status == "active"

    def test_manifest_and_db_both_created(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        manifest = read_source_manifest(brain, result.canonical_id)
        state = load_state(brain)
        assert manifest is not None
        assert result.canonical_id in state.sources

    def test_add_with_flags(self, brain: Path):
        result = add_source(
            brain,
            url=CONFLUENCE_URL,
            target_path="area",
            fetch_children=True,
            sync_attachments=True,
            child_path="children",
        )
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        assert manifest.fetch_children is True
        assert manifest.sync_attachments is True
        assert manifest.child_path == "children"


class TestRemoveSourceDeletesManifest:
    def test_removes_manifest_on_remove(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        remove_source(brain, source=result.canonical_id, delete_files=False)
        assert read_source_manifest(brain, result.canonical_id) is None

    def test_removes_manifest_with_file_delete(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        # Create a fake synced file
        area = brain / "knowledge" / "area"
        area.mkdir(parents=True, exist_ok=True)
        (area / "c12345-test-page.md").write_text("# test\n")
        remove_source(brain, source=result.canonical_id, delete_files=True)
        assert read_source_manifest(brain, result.canonical_id) is None


class TestMoveSourceUpdatesManifest:
    def test_updates_manifest_path(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="old-area")
        move_source(brain, source=result.canonical_id, to_path="new-area")
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        # No synced file exists yet — materialized_path stays empty until first sync
        assert manifest.materialized_path == ""

    def test_updates_manifest_with_file_path(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="old-area")
        # Create a synced file at the old location
        old_dir = brain / "knowledge" / "old-area"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "c12345-test-page.md").write_text("# test\n")

        move_source(brain, source=result.canonical_id, to_path="new-area")
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        # File was moved, so manifest stores full file path
        assert manifest.materialized_path == "new-area/c12345-test-page.md"


class TestUpdateSourceUpdatesManifest:
    def test_updates_flags_in_manifest(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        update_source(brain, source=result.canonical_id, sync_attachments=True)
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        assert manifest.sync_attachments is True

    def test_updates_child_path(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        update_source(brain, source=result.canonical_id, child_path="kids")
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        assert manifest.child_path == "kids"


class TestReconcileBootstrapsMigration:
    def test_bootstraps_manifests_from_db(self, brain: Path):
        """When DB has sources but no manifests, reconcile exports them."""
        # Simulate a pre-Phase-2 brain: source in DB with progress, no manifests
        from brain_sync.state import SourceState, SyncState, save_state

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
            last_checked_utc="2026-01-01T00:00:00",
        )
        save_state(brain, state)
        # Ensure no manifests exist (delete dir if add_source created it)
        import shutil

        manifest_dir = brain / ".brain-sync" / "sources"
        if manifest_dir.exists():
            shutil.rmtree(manifest_dir)
        assert read_all_source_manifests(brain) == {}

        reconcile_sources(brain)

        manifests = read_all_source_manifests(brain)
        assert len(manifests) == 1
        assert CONFLUENCE_CID in manifests
        m = manifests[CONFLUENCE_CID]
        assert m.source_url == CONFLUENCE_URL
        assert m.source_type == "confluence"

    def test_does_not_bootstrap_when_manifests_exist(self, brain: Path):
        """If manifests already exist, bootstrap is a no-op."""
        add_source(brain, url=CONFLUENCE_URL, target_path="area")
        # Manifest was created by add_source — reconcile should not touch it
        original = read_source_manifest(brain, CONFLUENCE_CID)
        reconcile_sources(brain)
        after = read_source_manifest(brain, CONFLUENCE_CID)
        assert original is not None
        assert after is not None
        assert original.canonical_id == after.canonical_id


class TestReconcileUpdatesManifestPath:
    def test_reconcile_updates_manifest_on_move(self, brain: Path):
        """When a synced file is moved on disk, reconcile updates the manifest."""
        result = add_source(brain, url=CONFLUENCE_URL, target_path="old-area")
        # Create file at old location
        old_dir = brain / "knowledge" / "old-area"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "c12345-test-page.md").write_text("# test\n")

        # Move file to new location
        new_dir = brain / "knowledge" / "new-area"
        new_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "c12345-test-page.md").rename(new_dir / "c12345-test-page.md")

        reconcile_result = reconcile_sources(brain)
        assert len(reconcile_result.updated) == 1

        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        assert manifest.materialized_path == "new-area/c12345-test-page.md"

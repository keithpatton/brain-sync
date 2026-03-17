"""Integration tests: source commands write manifests alongside DB."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.source_state import load_state
from brain_sync.application.sources import (
    InvalidChildDiscoveryRequestError,
    add_source,
    move_source,
    reconcile_sources,
    remove_source,
    update_source,
)
from brain_sync.brain.manifest import read_all_source_manifests, read_source_manifest
from brain_sync.runtime.child_requests import load_child_discovery_request
from brain_sync.runtime.repository import _connect

pytestmark = pytest.mark.integration

CONFLUENCE_URL = "https://acme.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    """Create a valid v23 brain with runtime DB initialized."""
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
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
        request = load_child_discovery_request(brain, result.canonical_id)
        assert manifest is not None
        assert manifest.sync_attachments is True
        assert not hasattr(manifest, "fetch_children")
        assert not hasattr(manifest, "child_path")
        assert request is not None
        assert request.fetch_children is True
        assert request.child_path == "children"

    def test_add_rejects_child_path_without_fetch_children(self, brain: Path):
        with pytest.raises(InvalidChildDiscoveryRequestError):
            add_source(
                brain,
                url=CONFLUENCE_URL,
                target_path="area",
                child_path="children",
            )


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

    def test_updates_child_path_for_pending_request(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area", fetch_children=True, child_path="children")
        update_source(brain, source=result.canonical_id, child_path="kids")
        manifest = read_source_manifest(brain, result.canonical_id)
        request = load_child_discovery_request(brain, result.canonical_id)
        assert manifest is not None
        assert not hasattr(manifest, "child_path")
        assert request is not None
        assert request.fetch_children is True
        assert request.child_path == "kids"

    def test_update_rejects_child_path_without_pending_request(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")

        with pytest.raises(InvalidChildDiscoveryRequestError):
            update_source(brain, source=result.canonical_id, child_path="kids")

    def test_update_clears_pending_child_request_when_fetch_children_is_disabled(self, brain: Path):
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area", fetch_children=True, child_path="children")

        update_source(brain, source=result.canonical_id, fetch_children=False)

        assert load_child_discovery_request(brain, result.canonical_id) is None


class TestReconcileBootstrapsMigration:
    def test_no_bootstrap_from_sync_cache_in_v21(self, brain: Path):
        """In v21, sync_cache has no intent — bootstrap from DB produces nothing."""
        from brain_sync.application.source_state import SourceState, SyncState, save_state

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
            last_checked_utc="2026-01-01T00:00:00",
        )
        save_state(brain, state)
        import shutil

        manifest_dir = brain / ".brain-sync" / "sources"
        if manifest_dir.exists():
            shutil.rmtree(manifest_dir)
        manifest_dir.mkdir(parents=True)
        assert read_all_source_manifests(brain) == {}

        reconcile_sources(brain)

        # v21: sync_cache has no intent fields, bootstrap can't create manifests
        manifests = read_all_source_manifests(brain)
        assert len(manifests) == 0

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

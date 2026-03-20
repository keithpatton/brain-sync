"""Integration tests for manifest-authoritative source lifecycle behavior."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.source_state import SourceState, load_state, save_state
from brain_sync.application.sources import add_source, list_sources, reconcile_sources
from brain_sync.application.sync_events import apply_folder_move
from brain_sync.brain.fileops import atomic_write_bytes
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import mark_manifest_missing, read_source_manifest, write_source_manifest
from brain_sync.brain.tree import normalize_path
from brain_sync.runtime.repository import (
    acquire_source_lifecycle_lease,
    load_child_discovery_request,
    load_source_lifecycle_runtime,
    load_sync_progress,
)
from brain_sync.sync.watcher import FolderMove

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
    directory = brain / "knowledge" / area
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_text(prepend_managed_header(cid, body), encoding="utf-8")
    return path


def _set_materialized_manifest(brain: Path, knowledge_path: str) -> None:
    manifest = read_source_manifest(brain, CONFLUENCE_CID)
    assert manifest is not None
    manifest.knowledge_state = "materialized"
    manifest.knowledge_path = knowledge_path
    manifest.content_hash = "sha256:abc"
    manifest.remote_fingerprint = "rev-1"
    manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
    write_source_manifest(brain, manifest)


class TestReconcileManifestReadPath:
    def test_moved_to_different_dir_and_renamed_found_via_header(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old")
        _create_synced_file(brain, CONFLUENCE_CID, "old", "c12345-test-page.md")
        _set_materialized_manifest(brain, "old/c12345-test-page.md")

        new_dir = brain / "knowledge" / "new-area" / "sub"
        new_dir.mkdir(parents=True)
        (brain / "knowledge" / "old" / "c12345-test-page.md").rename(new_dir / "renamed-page.md")

        result = reconcile_sources(root=brain)

        assert result.not_found == []
        assert result.marked_missing == []
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_path == "new-area/sub/renamed-page.md"
        assert manifest.knowledge_state == "stale"

    def test_two_stage_missing_first_marks(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        _set_materialized_manifest(brain, "area/c12345-test-page.md")

        result = reconcile_sources(root=brain)
        assert CONFLUENCE_CID in result.marked_missing
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "missing"
        runtime_state = load_source_lifecycle_runtime(brain, CONFLUENCE_CID)
        assert runtime_state is not None
        assert runtime_state.missing_confirmation_count == 1

    def test_non_finalizing_reconcile_preserves_missing_grace_period(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        _set_materialized_manifest(brain, "area/c12345-test-page.md")

        first = reconcile_sources(root=brain, finalize_missing=False)
        second = reconcile_sources(root=brain, finalize_missing=False)

        assert CONFLUENCE_CID in first.marked_missing
        assert second.deleted == []
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "missing"

    def test_second_missing_confirmation_stays_non_destructive(self, brain: Path) -> None:
        add_source(
            root=brain,
            url=CONFLUENCE_URL,
            target_path="area",
            fetch_children=True,
            sync_attachments=True,
            child_path="children",
        )
        _set_materialized_manifest(brain, "area/c12345-test-page.md")
        attachment_dir = brain / "knowledge" / "area" / ".brain-sync" / "attachments" / "c12345"
        attachment_dir.mkdir(parents=True)
        (attachment_dir / "a789.png").write_bytes(b"png")

        reconcile_sources(root=brain)
        reconcile_sources(root=brain)

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "missing"
        runtime_state = load_source_lifecycle_runtime(brain, CONFLUENCE_CID)
        assert runtime_state is not None
        assert runtime_state.missing_confirmation_count >= 2
        assert CONFLUENCE_CID not in load_sync_progress(brain)
        assert load_child_discovery_request(brain, CONFLUENCE_CID) is not None
        assert attachment_dir.exists()

    def test_missing_source_retains_attachments_even_if_manifest_target_path_is_stale(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-area", sync_attachments=True)
        _set_materialized_manifest(brain, "old-area/c12345-test-page.md")
        moved_attachment_dir = brain / "knowledge" / "new-area" / ".brain-sync" / "attachments" / "c12345"
        moved_attachment_dir.mkdir(parents=True)
        (moved_attachment_dir / "a789.png").write_bytes(b"png")

        reconcile_sources(root=brain)
        result = reconcile_sources(root=brain)

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "missing"
        assert not result.deleted
        assert moved_attachment_dir.exists()

    def test_reappearing_file_clears_missing_and_marks_stale(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        _set_materialized_manifest(brain, "area/c12345-test-page.md")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        _create_synced_file(brain, CONFLUENCE_CID, "area", "c12345-test-page.md")

        result = reconcile_sources(root=brain)
        assert CONFLUENCE_CID in result.reappeared
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "stale"
        assert manifest.missing_since_utc is None
        assert load_source_lifecycle_runtime(brain, CONFLUENCE_CID) is None

    def test_awaiting_source_is_not_marked_missing(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")

        result = reconcile_sources(root=brain)
        assert result.unchanged == 1
        assert result.not_found == []
        assert result.marked_missing == []
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "awaiting"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_materialized_overlong_path_is_not_marked_missing(self, brain: Path) -> None:
        rel = _long_relative_path(brain / "knowledge", "c12345-test-page.md")
        target_path = normalize_path(rel.parent)
        add_source(root=brain, url=CONFLUENCE_URL, target_path=target_path)

        content = prepend_managed_header(CONFLUENCE_CID, "content")
        atomic_write_bytes(brain / "knowledge" / rel, content.encode("utf-8"))
        _set_materialized_manifest(brain, normalize_path(rel))

        result = reconcile_sources(root=brain)

        assert result.marked_missing == []
        assert result.not_found == []
        assert result.unchanged == 1

    def test_orphan_db_rows_pruned(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        state = load_state(brain)
        state.sources[CONFLUENCE_CID_2] = SourceState(
            canonical_id=CONFLUENCE_CID_2,
            source_url=CONFLUENCE_URL_2,
            source_type="confluence",
            next_check_utc="2026-03-19T11:00:00+00:00",
        )
        save_state(brain, state)

        result = reconcile_sources(root=brain)
        assert result.orphan_rows_pruned == 1
        assert CONFLUENCE_CID_2 not in load_sync_progress(brain)

    def test_reconcile_preserves_active_non_missing_lifecycle_lease_rows(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        _create_synced_file(brain, CONFLUENCE_CID, "area", "c12345-test-page.md")
        _set_materialized_manifest(brain, "area/c12345-test-page.md")

        acquired, _ = acquire_source_lifecycle_lease(
            brain,
            CONFLUENCE_CID,
            "move-owner",
            lease_expires_utc="2099-01-01T00:00:00+00:00",
        )
        assert acquired is True

        result = reconcile_sources(root=brain)

        assert result.unchanged == 1
        runtime_state = load_source_lifecycle_runtime(brain, CONFLUENCE_CID)
        assert runtime_state is not None
        assert runtime_state.lease_owner == "move-owner"
        assert runtime_state.lease_expires_utc == "2099-01-01T00:00:00+00:00"

    def test_list_sources_manifest_authoritative(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="eng")
        sources = list_sources(root=brain)
        assert len(sources) == 1
        assert sources[0].canonical_id == CONFLUENCE_CID
        assert sources[0].target_path == "eng"

    def test_missing_source_not_in_list(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        sources = list_sources(root=brain)
        assert len(sources) == 1
        assert sources[0].knowledge_state == "missing"


class TestApplyFolderMoveManifests:
    def test_updates_awaiting_anchor_without_materializing(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-dir")

        k_old = brain / "knowledge" / "old-dir"
        k_old.mkdir(parents=True, exist_ok=True)
        k_new = brain / "knowledge" / "new-dir"
        import shutil

        shutil.move(str(k_old), str(k_new))
        move = FolderMove(src=k_old.resolve(), dest=k_new.resolve())
        apply_folder_move(brain, move=move)

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_path == "new-dir/c12345.md"
        assert manifest.knowledge_state == "awaiting"

    def test_updates_materialized_path_and_marks_stale(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-dir")
        _create_synced_file(brain, CONFLUENCE_CID, "old-dir", "c12345-test-page.md")
        _set_materialized_manifest(brain, "old-dir/c12345-test-page.md")

        k_old = (brain / "knowledge" / "old-dir").resolve()
        k_new = brain / "knowledge" / "new-dir"
        import shutil

        shutil.move(str(k_old), str(k_new))

        move = FolderMove(src=k_old, dest=k_new.resolve())
        apply_folder_move(brain, move=move)

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_path == "new-dir/c12345-test-page.md"
        assert manifest.knowledge_state == "stale"

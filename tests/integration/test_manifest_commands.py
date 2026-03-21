"""Integration tests for source commands against Brain Format 1.1 manifests.

`target_path` appears here because the command surface still accepts that
placement input for compatibility. In new tests, prefer `knowledge_path` when
asserting portable manifest/state semantics.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.doctor import doctor
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
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import (
    read_all_source_manifests,
    read_source_manifest,
    write_source_manifest,
)
from brain_sync.runtime.child_requests import load_child_discovery_request
from brain_sync.runtime.repository import _connect

pytestmark = pytest.mark.integration

CONFLUENCE_URL = "https://acme.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    conn = _connect(root)
    conn.close()
    return root


class TestAddSourceWritesManifest:
    def test_creates_awaiting_manifest_on_add(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        assert manifest.canonical_id == CONFLUENCE_CID
        assert manifest.source_url == CONFLUENCE_URL
        assert manifest.source_type == "confluence"
        assert manifest.sync_attachments is False
        assert manifest.knowledge_state == "awaiting"
        assert manifest.knowledge_path == "area/c12345.md"

    def test_manifest_and_state_both_created(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        manifest = read_source_manifest(brain, result.canonical_id)
        state = load_state(brain)
        assert manifest is not None
        assert result.canonical_id in state.sources

    def test_add_with_flags(self, brain: Path) -> None:
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
        assert request is not None
        assert request.fetch_children is True
        assert request.child_path == "children"

    def test_add_rejects_child_path_without_fetch_children(self, brain: Path) -> None:
        with pytest.raises(InvalidChildDiscoveryRequestError):
            add_source(brain, url=CONFLUENCE_URL, target_path="area", child_path="children")


class TestMoveSourceUpdatesManifest:
    def test_updates_awaiting_anchor(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="old-area")
        move_source(brain, source=result.canonical_id, to_path="new-area")
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        assert manifest.knowledge_path == "new-area/c12345.md"
        assert manifest.knowledge_state == "awaiting"

    def test_updates_materialized_path_and_marks_stale(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="old-area")
        old_dir = brain / "knowledge" / "old-area"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "c12345-test-page.md").write_text(prepend_managed_header(CONFLUENCE_CID, "# test"), encoding="utf-8")

        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "old-area/c12345-test-page.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        write_source_manifest(brain, manifest)

        move_source(brain, source=result.canonical_id, to_path="new-area")
        moved = read_source_manifest(brain, result.canonical_id)
        assert moved is not None
        assert moved.knowledge_path == "new-area/c12345-test-page.md"
        assert moved.knowledge_state == "stale"


class TestUpdateSourceUpdatesManifest:
    def test_updates_flags_in_manifest(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        update_source(brain, source=result.canonical_id, sync_attachments=True)
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        assert manifest.sync_attachments is True


class TestReconcileBehavior:
    def test_reconcile_does_not_bootstrap_from_runtime_only_rows(self, brain: Path) -> None:
        from brain_sync.application.source_state import SourceState, SyncState, save_state

        runtime_only = SyncState(
            sources={
                CONFLUENCE_CID: SourceState(
                    canonical_id=CONFLUENCE_CID,
                    source_url=CONFLUENCE_URL,
                    source_type="confluence",
                    next_check_utc="2026-03-19T11:00:00+00:00",
                )
            }
        )
        save_state(brain, runtime_only)
        manifest_dir = brain / ".brain-sync" / "sources"
        for path in manifest_dir.glob("*.json"):
            path.unlink()
        assert read_all_source_manifests(brain) == {}

        reconcile_sources(brain)

        assert read_all_source_manifests(brain) == {}

    def test_reconcile_updates_manifest_on_move(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="old-area")
        old_dir = brain / "knowledge" / "old-area"
        old_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "c12345-test-page.md").write_text(prepend_managed_header(CONFLUENCE_CID, "# test"), encoding="utf-8")
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "old-area/c12345-test-page.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        write_source_manifest(brain, manifest)

        new_dir = brain / "knowledge" / "new-area"
        new_dir.mkdir(parents=True, exist_ok=True)
        (old_dir / "c12345-test-page.md").rename(new_dir / "c12345-test-page.md")

        reconcile_result = reconcile_sources(brain)
        assert len(reconcile_result.updated) == 1

        moved = read_source_manifest(brain, result.canonical_id)
        assert moved is not None
        assert moved.knowledge_path == "new-area/c12345-test-page.md"
        assert moved.knowledge_state == "stale"


class TestRemoveSourceDeletesManifest:
    def test_removes_manifest_on_remove(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area")
        remove_source(brain, source=result.canonical_id, delete_files=False)
        assert read_source_manifest(brain, result.canonical_id) is None

    def test_remove_without_delete_files_removes_managed_source_content_cleanly(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area", sync_attachments=True)
        doc_path = brain / "knowledge" / "area" / "c12345-test-page.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(
            prepend_managed_header(CONFLUENCE_CID, "# test", source_type="confluence", source_url=CONFLUENCE_URL),
            encoding="utf-8",
        )
        att_dir = brain / "knowledge" / "area" / ".brain-sync" / "attachments" / "c12345"
        att_dir.mkdir(parents=True)
        (att_dir / "a789.png").write_bytes(b"png")

        remove_source(brain, source=result.canonical_id, delete_files=False)

        assert read_source_manifest(brain, result.canonical_id) is None
        assert not doc_path.exists()
        assert not att_dir.exists()
        result = doctor(brain)
        assert not [finding for finding in result.findings if finding.check == "unregistered_synced_files"]
        assert not [finding for finding in result.findings if finding.check == "orphan_attachments"]

    def test_remove_deletes_prefix_rediscovered_markdown(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="old-area")
        manifest = read_source_manifest(brain, result.canonical_id)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "old-area/c12345-test-page.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        write_source_manifest(brain, manifest)

        moved = brain / "knowledge" / "new-area" / "c12345-renamed.md"
        moved.parent.mkdir(parents=True, exist_ok=True)
        moved.write_text("# Prefix-only rediscovered file\n", encoding="utf-8")

        remove_source(brain, source=result.canonical_id, delete_files=False)

        assert read_source_manifest(brain, result.canonical_id) is None
        assert not moved.exists()

    def test_remove_does_not_prune_empty_area_directory(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="project/area", sync_attachments=True)
        doc_path = brain / "knowledge" / "project" / "area" / "c12345-test-page.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(
            prepend_managed_header(CONFLUENCE_CID, "# test", source_type="confluence", source_url=CONFLUENCE_URL),
            encoding="utf-8",
        )
        att_dir = brain / "knowledge" / "project" / "area" / ".brain-sync" / "attachments" / "c12345"
        att_dir.mkdir(parents=True)
        (att_dir / "a789.png").write_bytes(b"png")

        remove_source(brain, source=result.canonical_id, delete_files=False)

        assert (brain / "knowledge" / "project" / "area").is_dir()

    def test_remove_does_not_delete_legacy_sync_context_leftovers(self, brain: Path) -> None:
        result = add_source(brain, url=CONFLUENCE_URL, target_path="area", sync_attachments=True)
        doc_path = brain / "knowledge" / "area" / "c12345-test-page.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(
            prepend_managed_header(CONFLUENCE_CID, "# test", source_type="confluence", source_url=CONFLUENCE_URL),
            encoding="utf-8",
        )
        att_dir = brain / "knowledge" / "area" / ".brain-sync" / "attachments" / "c12345"
        att_dir.mkdir(parents=True)
        (att_dir / "a789.png").write_bytes(b"png")
        legacy_dir = brain / "knowledge" / "area" / "_sync-context" / "attachments"
        legacy_dir.mkdir(parents=True)
        legacy_file = legacy_dir / "other-source.bin"
        legacy_file.write_bytes(b"legacy")

        remove_source(brain, source=result.canonical_id, delete_files=False)

        assert read_source_manifest(brain, result.canonical_id) is None
        assert not doc_path.exists()
        assert not att_dir.exists()
        assert legacy_file.exists()
        assert legacy_file.read_bytes() == b"legacy"

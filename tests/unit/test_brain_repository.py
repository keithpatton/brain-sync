from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from brain_sync.brain_repository import BrainRepository, BrainRepositoryInvariantError
from brain_sync.managed_markdown import prepend_managed_header
from brain_sync.manifest import MANIFEST_VERSION, SourceManifest, read_source_manifest, write_source_manifest

pytestmark = pytest.mark.unit


def _manifest(
    canonical_id: str,
    *,
    materialized_path: str = "",
    target_path: str = "area",
    status: str = "active",
) -> SourceManifest:
    page_id = canonical_id.split(":", 1)[1]
    return SourceManifest(
        version=MANIFEST_VERSION,
        canonical_id=canonical_id,
        source_url=f"https://acme.atlassian.net/wiki/spaces/ENG/pages/{page_id}",
        source_type="confluence",
        materialized_path=materialized_path,
        sync_attachments=False,
        target_path=target_path,
        status=status,
    )


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    (root / "knowledge").mkdir(parents=True)
    (root / ".brain-sync" / "sources").mkdir(parents=True)
    return root


class TestResolveSourceFile:
    def test_returns_unmaterialized_for_active_manifest_without_file(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        manifest = _manifest("confluence:12345")

        resolution = repository.resolve_source_file(manifest)

        assert resolution.resolution == "unmaterialized"
        assert resolution.path is None

    def test_prefers_identity_index_for_moved_managed_file(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        manifest = _manifest("confluence:12345", materialized_path="area/c12345-test-page.md")
        moved = brain / "knowledge" / "other" / "c12345-test-page.md"
        moved.parent.mkdir(parents=True)
        moved.write_text(
            prepend_managed_header(
                "confluence:12345",
                "# Test Page\n",
                source_type="confluence",
                source_url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345",
            ),
            encoding="utf-8",
        )

        resolution = repository.resolve_source_file(
            manifest,
            identity_index={"confluence:12345": Path("other/c12345-test-page.md")},
        )

        assert resolution.resolution == "identity"
        assert resolution.path == moved

    def test_falls_back_to_prefix_rediscovery_for_unmanaged_move(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        manifest = _manifest("confluence:12345", materialized_path="area/c12345-test-page.md")
        moved = brain / "knowledge" / "other" / "c12345-test-page.md"
        moved.parent.mkdir(parents=True)
        moved.write_text("# Test Page\n", encoding="utf-8")

        resolution = repository.resolve_source_file(manifest)

        assert resolution.resolution == "prefix"
        assert resolution.path == moved


class TestManifestUpdates:
    def test_apply_folder_move_updates_target_and_materialized_paths(self, brain: Path) -> None:
        manifest = _manifest(
            "confluence:12345",
            materialized_path="old-area/c12345-test-page.md",
            target_path="old-area",
        )
        write_source_manifest(brain, manifest)

        repository = BrainRepository(brain)
        updates = repository.apply_folder_move_to_manifests("old-area", "new-area")

        assert len(updates) == 1
        assert updates[0].old_target_path == "old-area"
        assert updates[0].new_target_path == "new-area"

        updated = read_source_manifest(brain, "confluence:12345")
        assert updated is not None
        assert updated.target_path == "new-area"
        assert updated.materialized_path == "new-area/c12345-test-page.md"

    def test_sync_manifest_to_found_path_raises_for_file_outside_knowledge_root(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        manifest = _manifest("confluence:12345", materialized_path="area/c12345-test-page.md")
        write_source_manifest(brain, manifest)
        outside = brain.parent / "outside.md"
        outside.write_text("# Outside\n", encoding="utf-8")

        with pytest.raises(BrainRepositoryInvariantError, match="outside knowledge root"):
            repository.sync_manifest_to_found_path("confluence:12345", outside)


class TestStrictMutationGuards:
    def test_rewrite_managed_identity_raises_for_missing_file(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        missing = brain / "knowledge" / "area" / "missing.md"

        with pytest.raises(BrainRepositoryInvariantError, match="expected an existing file"):
            repository.rewrite_managed_identity(
                missing,
                canonical_id="confluence:12345",
                source_type="confluence",
                source_url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345",
            )

    def test_append_journal_entry_raises_for_parent_traversal(self, brain: Path) -> None:
        repository = BrainRepository(brain)

        with pytest.raises(BrainRepositoryInvariantError, match="must stay within the knowledge tree"):
            repository.append_journal_entry("../outside", "Entry")

    def test_remove_source_owned_files_raises_for_parent_traversal(self, brain: Path) -> None:
        repository = BrainRepository(brain)

        with pytest.raises(BrainRepositoryInvariantError, match="must stay within the knowledge tree"):
            repository.remove_source_owned_files("../outside", "confluence:12345")

    def test_remove_attachment_dir_raises_outside_knowledge_root(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        outside = brain.parent / "attachments" / "c12345"
        outside.mkdir(parents=True)

        with pytest.raises(BrainRepositoryInvariantError, match="outside knowledge root"):
            repository.remove_attachment_dir(outside)

    def test_remove_attachment_dir_raises_for_non_managed_directory(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        non_managed = brain / "knowledge" / "area" / "attachments" / "c12345"
        non_managed.mkdir(parents=True)

        with pytest.raises(BrainRepositoryInvariantError, match="not a managed attachment directory"):
            repository.remove_attachment_dir(non_managed)


class TestJournalAppend:
    def test_append_journal_entry_allows_root_knowledge_area(self, brain: Path) -> None:
        repository = BrainRepository(brain)

        journal = repository.append_journal_entry("", "Root entry.", timestamp=datetime(2026, 3, 17, 8, 15))

        assert journal == brain / "knowledge" / ".brain-sync" / "insights" / "journal" / "2026-03" / "2026-03-17.md"
        assert "Root entry." in journal.read_text(encoding="utf-8")

    def test_append_journal_entry_keeps_prior_entries(self, brain: Path) -> None:
        repository = BrainRepository(brain)

        first = repository.append_journal_entry(
            "area",
            "First entry.",
            timestamp=datetime(2026, 3, 17, 9, 30),
        )
        second = repository.append_journal_entry(
            "area",
            "Second entry.",
            timestamp=datetime(2026, 3, 17, 10, 45),
        )

        assert first == second
        content = first.read_text(encoding="utf-8")
        assert "First entry." in content
        assert "Second entry." in content
        assert content.count("## ") == 2


class TestAttachmentCleanup:
    def test_iter_orphan_attachment_dirs_returns_unregistered_source_dirs(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        registered = _manifest("confluence:12345")
        write_source_manifest(brain, registered)

        registered_dir = brain / "knowledge" / "area" / ".brain-sync" / "attachments" / "c12345"
        orphan_dir = brain / "knowledge" / "area" / ".brain-sync" / "attachments" / "c99999"
        registered_dir.mkdir(parents=True)
        orphan_dir.mkdir(parents=True)

        orphans = repository.iter_orphan_attachment_dirs({"confluence:12345": registered})

        assert orphans == [orphan_dir]

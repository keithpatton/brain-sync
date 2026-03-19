from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from brain_sync.brain.layout import area_insights_dir, area_journal_dir
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import MANIFEST_VERSION, SourceManifest, read_source_manifest, write_source_manifest
from brain_sync.brain.repository import BrainRepository, BrainRepositoryInvariantError, PortableBrainLockError

pytestmark = pytest.mark.unit


def _manifest(
    canonical_id: str,
    *,
    knowledge_path: str = "area/c12345-test-page.md",
    knowledge_state: str = "materialized",
) -> SourceManifest:
    page_id = canonical_id.split(":", 1)[1]
    kwargs = {
        "version": MANIFEST_VERSION,
        "canonical_id": canonical_id,
        "source_url": f"https://acme.atlassian.net/wiki/spaces/ENG/pages/{page_id}",
        "source_type": "confluence",
        "sync_attachments": False,
        "knowledge_path": knowledge_path,
        "knowledge_state": knowledge_state,
    }
    if knowledge_state in {"materialized", "stale"}:
        kwargs.update(
            {
                "content_hash": "sha256:abc",
                "remote_fingerprint": "rev-1",
                "materialized_utc": "2026-03-19T09:00:00+00:00",
            }
        )
    elif knowledge_state == "missing":
        kwargs.update(
            {
                "missing_since_utc": "2026-03-19T10:00:00+00:00",
                "content_hash": "sha256:abc",
                "remote_fingerprint": "rev-1",
                "materialized_utc": "2026-03-19T09:00:00+00:00",
            }
        )
    return SourceManifest(**kwargs)


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    (root / "knowledge").mkdir(parents=True)
    (root / ".brain-sync" / "sources").mkdir(parents=True)
    return root


class TestResolveSourceFile:
    def test_returns_unmaterialized_for_awaiting_manifest_without_file(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        manifest = _manifest("confluence:12345", knowledge_state="awaiting", knowledge_path="area/c12345.md")

        resolution = repository.resolve_source_file(manifest)

        assert resolution.resolution == "unmaterialized"
        assert resolution.path is None

    def test_prefers_identity_index_for_moved_managed_file(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        manifest = _manifest("confluence:12345")
        moved = brain / "knowledge" / "other" / "renamed-page.md"
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
            identity_index={"confluence:12345": Path("other/renamed-page.md")},
        )

        assert resolution.resolution == "identity"
        assert resolution.path == moved

    def test_falls_back_to_prefix_rediscovery_for_unmanaged_move(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        manifest = _manifest("confluence:12345")
        moved = brain / "knowledge" / "other" / "c12345-test-page.md"
        moved.parent.mkdir(parents=True)
        moved.write_text("# Test Page\n", encoding="utf-8")

        resolution = repository.resolve_source_file(manifest)

        assert resolution.resolution == "prefix"
        assert resolution.path == moved


class TestManifestUpdates:
    def test_apply_folder_move_updates_knowledge_path_and_marks_stale(self, brain: Path) -> None:
        manifest = _manifest("confluence:12345", knowledge_path="old-area/c12345-test-page.md")
        write_source_manifest(brain, manifest)

        repository = BrainRepository(brain)
        updates = repository.apply_folder_move_to_manifests("old-area", "new-area")

        assert len(updates) == 1
        assert updates[0].old_target_path == "old-area"
        assert updates[0].new_target_path == "new-area"
        assert updates[0].knowledge_path == "new-area/c12345-test-page.md"

        updated = read_source_manifest(brain, "confluence:12345")
        assert updated is not None
        assert updated.knowledge_path == "new-area/c12345-test-page.md"
        assert updated.knowledge_state == "stale"

    def test_apply_folder_move_keeps_awaiting_state(self, brain: Path) -> None:
        manifest = _manifest("confluence:12345", knowledge_path="old-area/c12345.md", knowledge_state="awaiting")
        write_source_manifest(brain, manifest)

        repository = BrainRepository(brain)
        repository.apply_folder_move_to_manifests("old-area", "new-area")

        updated = read_source_manifest(brain, "confluence:12345")
        assert updated is not None
        assert updated.knowledge_path == "new-area/c12345.md"
        assert updated.knowledge_state == "awaiting"

    def test_sync_manifest_to_found_path_marks_rediscovered_source_stale(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        write_source_manifest(brain, _manifest("confluence:12345"))
        moved = brain / "knowledge" / "other" / "renamed-page.md"
        moved.parent.mkdir(parents=True)
        moved.write_text(prepend_managed_header("confluence:12345", "# Test"), encoding="utf-8")

        knowledge_path, target_path = repository.sync_manifest_to_found_path("confluence:12345", moved)

        assert knowledge_path == "other/renamed-page.md"
        assert target_path == "other"
        updated = read_source_manifest(brain, "confluence:12345")
        assert updated is not None
        assert updated.knowledge_path == "other/renamed-page.md"
        assert updated.knowledge_state == "stale"

    def test_sync_manifest_to_found_path_clears_missing_and_marks_stale(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        write_source_manifest(
            brain,
            _manifest("confluence:12345", knowledge_state="missing"),
        )
        rediscovered = brain / "knowledge" / "area" / "c12345-test-page.md"
        rediscovered.parent.mkdir(parents=True)
        rediscovered.write_text(prepend_managed_header("confluence:12345", "# Test"), encoding="utf-8")

        repository.sync_manifest_to_found_path("confluence:12345", rediscovered)

        updated = read_source_manifest(brain, "confluence:12345")
        assert updated is not None
        assert updated.knowledge_state == "stale"
        assert updated.missing_since_utc is None

    def test_sync_manifest_to_found_path_raises_for_file_outside_knowledge_root(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        write_source_manifest(brain, _manifest("confluence:12345"))
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

        assert journal == brain / "knowledge" / ".brain-sync" / "journal" / "2026-03" / "2026-03-17.md"
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

    def test_append_journal_entry_heals_legacy_layout_before_write(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        legacy = area_insights_dir(brain, "area") / "journal" / "2026-03" / "2026-03-17.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("## 08:00\n\nLegacy entry.", encoding="utf-8")

        journal = repository.append_journal_entry("area", "New entry.", timestamp=datetime(2026, 3, 17, 9, 15))

        assert journal == area_journal_dir(brain, "area") / "2026-03" / "2026-03-17.md"
        assert not legacy.exists()
        content = journal.read_text(encoding="utf-8")
        assert "Legacy entry." in content
        assert "New entry." in content


class TestLegacyJournalHealing:
    def test_heal_legacy_journal_layout_merges_unique_blocks_and_removes_legacy_tree(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        legacy = area_insights_dir(brain, "area") / "journal" / "2026-03" / "2026-03-17.md"
        target = area_journal_dir(brain, "area") / "2026-03" / "2026-03-17.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("## 09:00\n\nTarget entry.", encoding="utf-8")
        legacy.write_text("## 09:00\n\nTarget entry.\n\n## 10:30\n\nLegacy-only entry.", encoding="utf-8")

        changed = repository.heal_legacy_journal_layout("area")

        assert changed is True
        assert not (area_insights_dir(brain, "area") / "journal").exists()
        assert target.read_text(encoding="utf-8") == ("## 09:00\n\nTarget entry.\n\n## 10:30\n\nLegacy-only entry.")

    def test_heal_legacy_journal_layout_is_idempotent(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        legacy = area_insights_dir(brain, "area") / "journal" / "2026-03" / "2026-03-17.md"
        target = area_journal_dir(brain, "area") / "2026-03" / "2026-03-17.md"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("## 09:00\n\nTarget entry.", encoding="utf-8")
        legacy.write_text("## 09:00\n\nTarget entry.", encoding="utf-8")

        assert repository.heal_legacy_journal_layout("area") is True
        healed = target.read_text(encoding="utf-8")

        assert repository.heal_legacy_journal_layout("area") is False
        assert target.read_text(encoding="utf-8") == healed


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


class TestSourceOwnedRemoval:
    def test_remove_source_owned_files_deletes_prefix_rediscovered_file_and_keeps_empty_area_dir(
        self,
        brain: Path,
    ) -> None:
        repository = BrainRepository(brain)
        manifest = _manifest("confluence:12345", knowledge_path="old-area/c12345-test-page.md")
        write_source_manifest(brain, manifest)

        moved = brain / "knowledge" / "new-area" / "c12345-renamed.md"
        moved.parent.mkdir(parents=True, exist_ok=True)
        moved.write_text("# Detached but still prefixed\n", encoding="utf-8")
        attachment_dir = moved.parent / ".brain-sync" / "attachments" / "c12345"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        (attachment_dir / "a789.png").write_bytes(b"png")

        deleted = repository.remove_source_owned_files("old-area", "confluence:12345")

        assert deleted is True
        assert not moved.exists()
        assert not attachment_dir.exists()
        assert (brain / "knowledge" / "new-area").is_dir()


class TestFilesystemLockContention:
    def test_write_summary_raises_classified_lock_error_without_changing_file(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        summary_path = brain / "knowledge" / "area" / ".brain-sync" / "insights" / "summary.md"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text("existing summary", encoding="utf-8")

        error = PermissionError(13, "Access is denied", str(summary_path))
        error.winerror = 5  # type: ignore[attr-defined]

        with patch("brain_sync.brain.repository.atomic_write_bytes", side_effect=error):
            with pytest.raises(PortableBrainLockError, match="write_summary blocked by filesystem lock"):
                repository.write_summary("area", "new summary")

        assert summary_path.read_text(encoding="utf-8") == "existing summary"

    def test_save_portable_insight_state_raises_classified_lock_error(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        sidecar_path = brain / "knowledge" / "area" / ".brain-sync" / "insights" / "insight-state.json"

        error = PermissionError(13, "Access is denied", str(sidecar_path))
        error.winerror = 5  # type: ignore[attr-defined]

        with patch("brain_sync.brain.repository.sidecar_store.write_regen_meta", side_effect=error):
            with pytest.raises(PortableBrainLockError, match="save_portable_insight_state blocked by filesystem lock"):
                repository.save_portable_insight_state("area", content_hash="abc123")

        assert not sidecar_path.exists()

    def test_materialize_markdown_keeps_success_when_duplicate_cleanup_hits_lock(self, brain: Path) -> None:
        repository = BrainRepository(brain)
        canonical_id = "confluence:12345"
        write_source_manifest(brain, _manifest(canonical_id))

        target_dir = brain / "knowledge" / "area"
        target_dir.mkdir(parents=True, exist_ok=True)
        duplicate = target_dir / "duplicate.md"
        duplicate.write_text(prepend_managed_header(canonical_id, "Old body"), encoding="utf-8")

        original_unlink = Path.unlink
        error = PermissionError(13, "Access is denied", str(duplicate))
        error.winerror = 5  # type: ignore[attr-defined]

        def blocked_duplicate_unlink(path: Path, *args, **kwargs):
            if path == duplicate:
                raise error
            return original_unlink(path, *args, **kwargs)

        with patch("pathlib.Path.unlink", new=blocked_duplicate_unlink):
            result = repository.materialize_markdown(
                knowledge_path="area",
                filename="fresh.md",
                canonical_id=canonical_id,
                markdown="New body",
                source_type="confluence",
                source_url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345",
                content_hash="abc123",
                remote_fingerprint="rev-2",
                materialized_utc="2026-03-18T00:00:00+00:00",
            )

        target = target_dir / "fresh.md"
        assert target.exists()
        assert "New body" in target.read_text(encoding="utf-8")
        assert duplicate.exists()
        assert result.changed is True
        assert result.duplicate_files_removed == ()

"""Unit tests for startup knowledge-tree reconciliation."""

from __future__ import annotations

import pytest

from brain_sync.reconcile import reconcile_knowledge_tree
from brain_sync.state import (
    InsightState,
    _connect,
    load_insight_state,
    save_insight_state,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path):
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / "insights").mkdir()
    conn = _connect(root)
    conn.close()
    return root


def _write_knowledge_file(root, rel_path: str, content: str = "# Doc\n\nContent."):
    p = root / "knowledge" / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _write_insight_summary(root, knowledge_path: str, content: str = "summary"):
    p = root / "insights" / knowledge_path / "summary.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


class TestNoChanges:
    def test_no_changes(self, brain):
        """FS and DB have same paths, same content hashes — empty result."""
        _write_knowledge_file(brain, "area/doc.md")
        # Trigger classify to get the real hash, then save it
        from brain_sync.regen import classify_folder_change

        _, content_hash, structure_hash = classify_folder_change(brain, "area")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area",
                content_hash=content_hash,
                structure_hash=structure_hash,
                regen_status="idle",
            ),
        )

        result = reconcile_knowledge_tree(brain)
        assert result.orphans_cleaned == []
        assert result.content_changed == []
        assert result.enqueued_paths == []


class TestOrphanDbRowsCleaned:
    def test_orphan_db_rows_cleaned(self, brain):
        """DB has area-a, FS only has area-b → area-a cleaned, area-b enqueued."""
        save_insight_state(
            brain,
            InsightState(knowledge_path="area-a", content_hash="abc", regen_status="idle"),
        )
        _write_knowledge_file(brain, "area-b/doc.md")

        result = reconcile_knowledge_tree(brain)
        assert "area-a" in result.orphans_cleaned
        assert "area-b" in result.enqueued_paths
        assert load_insight_state(brain, "area-a") is None


class TestOrphanInsightsDirDeleted:
    def test_orphan_insights_dir_deleted(self, brain):
        """Orphan DB row + orphan insights/ dir — both removed."""
        save_insight_state(
            brain,
            InsightState(knowledge_path="gone", content_hash="abc", regen_status="idle"),
        )
        _write_insight_summary(brain, "gone")

        result = reconcile_knowledge_tree(brain)
        assert "gone" in result.orphans_cleaned
        assert not (brain / "insights" / "gone").exists()


class TestNewFolderNotEnqueuedWithoutOrphans:
    def test_new_folder_not_enqueued_without_orphans(self, brain):
        """FS has extra area-b, no orphans, no insights — NOT enqueued."""
        _write_knowledge_file(brain, "area-a/doc.md")
        _write_knowledge_file(brain, "area-b/doc.md")
        # Track area-a in DB with correct hash
        from brain_sync.regen import classify_folder_change

        _, ch, sh = classify_folder_change(brain, "area-a")
        save_insight_state(
            brain,
            InsightState(knowledge_path="area-a", content_hash=ch, structure_hash=sh, regen_status="idle"),
        )

        result = reconcile_knowledge_tree(brain)
        assert result.orphans_cleaned == []
        assert "area-b" not in result.enqueued_paths


class TestNewFolderEnqueuedWithExistingInsights:
    def test_new_folder_enqueued_with_existing_insights(self, brain):
        """No DB row for area-b, but insights/area-b exists — enqueued (Rule 1)."""
        _write_knowledge_file(brain, "area-b/doc.md")
        _write_insight_summary(brain, "area-b")

        result = reconcile_knowledge_tree(brain)
        assert "area-b" in result.enqueued_paths


class TestSubtreeMove:
    def test_subtree_move(self, brain):
        """DB has eng/api, FS has platform/api — orphan cleaned, platform/api enqueued."""
        save_insight_state(
            brain,
            InsightState(knowledge_path="eng/api", content_hash="abc", regen_status="idle"),
        )
        _write_knowledge_file(brain, "platform/api/doc.md")

        result = reconcile_knowledge_tree(brain)
        assert "eng/api" in result.orphans_cleaned
        assert "platform/api" in result.enqueued_paths


class TestTreeReplace:
    def test_tree_replace(self, brain):
        """DB has old-area, FS has new-area — orphan cleaned, new-area enqueued."""
        save_insight_state(
            brain,
            InsightState(knowledge_path="old-area", content_hash="abc", regen_status="idle"),
        )
        _write_knowledge_file(brain, "new-area/fresh.md")

        result = reconcile_knowledge_tree(brain)
        assert "old-area" in result.orphans_cleaned
        assert "new-area" in result.enqueued_paths


class TestEmptyBrain:
    def test_empty_brain(self, brain):
        """No DB rows, no FS paths — no-op."""
        result = reconcile_knowledge_tree(brain)
        assert result.orphans_cleaned == []
        assert result.content_changed == []
        assert result.enqueued_paths == []


class TestStableBrainNoChurn:
    def test_stable_brain_no_churn(self, brain):
        """FS and DB match, extra untracked folder, no orphans — nothing enqueued."""
        _write_knowledge_file(brain, "tracked/doc.md")
        _write_knowledge_file(brain, "untracked/doc.md")
        from brain_sync.regen import classify_folder_change

        _, ch, sh = classify_folder_change(brain, "tracked")
        save_insight_state(
            brain,
            InsightState(knowledge_path="tracked", content_hash=ch, structure_hash=sh, regen_status="idle"),
        )

        result = reconcile_knowledge_tree(brain)
        assert result.orphans_cleaned == []
        assert "untracked" not in result.enqueued_paths


class TestOfflineFileAdditionDetected:
    def test_offline_file_addition_detected(self, brain):
        """Tracked folder with extra file → content hash mismatch."""
        _write_knowledge_file(brain, "area/existing.md")
        from brain_sync.regen import classify_folder_change

        _, ch, sh = classify_folder_change(brain, "area")
        save_insight_state(
            brain,
            InsightState(knowledge_path="area", content_hash=ch, structure_hash=sh, regen_status="idle"),
        )
        # Add a new file offline
        _write_knowledge_file(brain, "area/new-topic.md", "# New\n\nNew content.")

        result = reconcile_knowledge_tree(brain)
        assert "area" in result.content_changed


class TestOfflineFileDeletionDetected:
    def test_offline_file_deletion_detected(self, brain):
        """Tracked folder with file removed → content hash mismatch."""
        _write_knowledge_file(brain, "area/keep.md")
        _write_knowledge_file(brain, "area/remove.md")
        from brain_sync.regen import classify_folder_change

        _, ch, sh = classify_folder_change(brain, "area")
        save_insight_state(
            brain,
            InsightState(knowledge_path="area", content_hash=ch, structure_hash=sh, regen_status="idle"),
        )
        # Remove a file offline
        (brain / "knowledge" / "area" / "remove.md").unlink()

        result = reconcile_knowledge_tree(brain)
        assert "area" in result.content_changed


class TestTrackedFolderUnchanged:
    def test_tracked_folder_unchanged(self, brain):
        """Tracked folder, same content hash — NOT in content_changed."""
        _write_knowledge_file(brain, "area/doc.md")
        from brain_sync.regen import classify_folder_change

        _, ch, sh = classify_folder_change(brain, "area")
        save_insight_state(
            brain,
            InsightState(knowledge_path="area", content_hash=ch, structure_hash=sh, regen_status="idle"),
        )

        result = reconcile_knowledge_tree(brain)
        assert "area" not in result.content_changed


class TestRootPathFileAddition:
    def test_root_level_file_addition_detected(self, brain):
        """Files directly under knowledge/ (root path '') are hash-checked."""
        _write_knowledge_file(brain, "root-doc.md", "# Root\n\nRoot content.")
        from brain_sync.regen import classify_folder_change

        _, ch, sh = classify_folder_change(brain, "")
        save_insight_state(
            brain,
            InsightState(knowledge_path="", content_hash=ch, structure_hash=sh, regen_status="idle"),
        )
        # Add a file offline at the root level
        _write_knowledge_file(brain, "new-root-doc.md", "# New\n\nNew root content.")

        result = reconcile_knowledge_tree(brain)
        assert "" in result.content_changed

    def test_root_level_unchanged(self, brain):
        """Root path with same content hash — NOT in content_changed."""
        _write_knowledge_file(brain, "root-doc.md", "# Root\n\nRoot content.")
        from brain_sync.regen import classify_folder_change

        _, ch, sh = classify_folder_change(brain, "")
        save_insight_state(
            brain,
            InsightState(knowledge_path="", content_hash=ch, structure_hash=sh, regen_status="idle"),
        )

        result = reconcile_knowledge_tree(brain)
        assert "" not in result.content_changed

    def test_root_level_no_db_row_no_enqueue(self, brain):
        """Root files exist but no DB row — nothing to reconcile (never regenerated)."""
        _write_knowledge_file(brain, "root-doc.md", "# Root\n\nContent.")

        result = reconcile_knowledge_tree(brain)
        assert "" not in result.content_changed
        assert "" not in result.enqueued_paths

    def test_root_level_last_file_deleted(self, brain):
        """Deleting the last root-level file when a root DB row exists → detected."""
        _write_knowledge_file(brain, "only-file.md", "# Only\n\nContent.")
        from brain_sync.regen import classify_folder_change

        _, ch, sh = classify_folder_change(brain, "")
        save_insight_state(
            brain,
            InsightState(knowledge_path="", content_hash=ch, structure_hash=sh, regen_status="idle"),
        )
        # Delete the only root-level file offline
        (brain / "knowledge" / "only-file.md").unlink()

        result = reconcile_knowledge_tree(brain)
        assert "" in result.content_changed

    def test_root_db_row_with_child_dirs_only(self, brain):
        """Root DB row exists with child dirs but no direct files — still checked."""
        _write_knowledge_file(brain, "area/doc.md", "# Doc\n\nContent.")
        from brain_sync.regen import classify_folder_change

        _, ch, sh = classify_folder_change(brain, "")
        save_insight_state(
            brain,
            InsightState(knowledge_path="", content_hash=ch, structure_hash=sh, regen_status="idle"),
        )
        # Add a new child dir offline — root hash changes due to new child summary
        _write_knowledge_file(brain, "new-area/doc.md", "# New\n\nContent.")

        result = reconcile_knowledge_tree(brain)
        assert "" in result.content_changed

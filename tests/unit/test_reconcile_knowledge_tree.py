from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.reconcile import reconcile_knowledge_tree
from brain_sync.state import InsightState, _connect, load_insight_state, save_insight_state

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    (root / "knowledge").mkdir(parents=True)
    conn = _connect(root)
    conn.close()
    return root


def _write_knowledge_file(root: Path, rel_path: str, content: str = "# Doc\n\nContent.") -> None:
    path = root / "knowledge" / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_summary(root: Path, knowledge_path: str, content: str = "summary") -> None:
    if knowledge_path:
        path = root / "knowledge" / knowledge_path / ".brain-sync" / "insights" / "summary.md"
    else:
        path = root / "knowledge" / ".brain-sync" / "insights" / "summary.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestNoChanges:
    def test_no_changes(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area/doc.md")
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


class TestOrphanStateCleanup:
    def test_orphan_state_row_is_removed(self, brain: Path) -> None:
        orphan_insights = brain / "knowledge" / "gone" / ".brain-sync" / "insights"
        orphan_insights.mkdir(parents=True)
        (orphan_insights / "summary.md").write_text("summary", encoding="utf-8")
        save_insight_state(brain, InsightState(knowledge_path="gone", content_hash="abc", regen_status="idle"))

        # Simulate the knowledge area being deleted while managed artifacts remain.
        (brain / "knowledge" / "gone" / "placeholder.txt").write_text("x", encoding="utf-8")
        (brain / "knowledge" / "gone" / "placeholder.txt").unlink()

        result = reconcile_knowledge_tree(brain)

        assert "gone" in result.orphans_cleaned
        assert load_insight_state(brain, "gone") is None

    def test_orphan_cleanup_enqueues_new_folder_when_state_disrupted(self, brain: Path) -> None:
        save_insight_state(brain, InsightState(knowledge_path="area-a", content_hash="abc", regen_status="idle"))
        _write_knowledge_file(brain, "area-b/doc.md")

        result = reconcile_knowledge_tree(brain)

        assert "area-a" in result.orphans_cleaned
        assert "area-b" in result.enqueued_paths


class TestUntrackedFolderEvidence:
    def test_untracked_folder_without_managed_evidence_is_not_enqueued(self, brain: Path) -> None:
        _write_knowledge_file(brain, "tracked/doc.md")
        _write_knowledge_file(brain, "untracked/doc.md")
        from brain_sync.regen import classify_folder_change

        _, content_hash, structure_hash = classify_folder_change(brain, "tracked")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="tracked",
                content_hash=content_hash,
                structure_hash=structure_hash,
                regen_status="idle",
            ),
        )

        result = reconcile_knowledge_tree(brain)

        assert "untracked" not in result.enqueued_paths

    def test_untracked_folder_with_colocated_summary_is_enqueued(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area-b/doc.md")
        _write_summary(brain, "area-b")

        result = reconcile_knowledge_tree(brain)

        assert "area-b" in result.enqueued_paths


class TestHashDriftDetection:
    def test_offline_file_addition_detected(self, brain: Path) -> None:
        _write_knowledge_file(brain, "area/existing.md")
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
        _write_knowledge_file(brain, "area/new-topic.md")

        result = reconcile_knowledge_tree(brain)

        assert "area" in result.content_changed

    def test_root_level_file_addition_detected(self, brain: Path) -> None:
        _write_knowledge_file(brain, "root-doc.md")
        from brain_sync.regen import classify_folder_change

        _, content_hash, structure_hash = classify_folder_change(brain, "")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="",
                content_hash=content_hash,
                structure_hash=structure_hash,
                regen_status="idle",
            ),
        )
        _write_knowledge_file(brain, "new-root-doc.md")

        result = reconcile_knowledge_tree(brain)

        assert "" in result.content_changed

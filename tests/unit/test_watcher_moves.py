"""Tests for watcher folder move mirroring."""

from __future__ import annotations

import pytest

from brain_sync.state import (
    InsightState,
    SourceState,
    SyncState,
    _connect,
    load_insight_state,
    load_state,
    save_insight_state,
    save_state,
)
from brain_sync.watcher import FolderMove, mirror_folder_move

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


class TestMirrorFolderMove:
    def test_mirrors_insights_folder(self, brain):
        """Folder rename in knowledge/ mirrors to insights/."""
        # Setup
        k_old = brain / "knowledge" / "old-name"
        k_old.mkdir()
        (k_old / "doc.md").write_text("content", encoding="utf-8")

        i_old = brain / "insights" / "old-name"
        i_old.mkdir()
        (i_old / "summary.md").write_text("summary", encoding="utf-8")

        k_new = brain / "knowledge" / "new-name"

        move = FolderMove(src=k_old.resolve(), dest=k_new.resolve())
        mirror_folder_move(brain, move)

        # Insights should have moved
        assert not (brain / "insights" / "old-name").exists()
        assert (brain / "insights" / "new-name" / "summary.md").exists()

    def test_updates_insight_state_path(self, brain):
        """insight_state DB rows updated after move."""
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="old-name",
                content_hash="abc",
                regen_status="idle",
            ),
        )
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="old-name/sub",
                content_hash="def",
                regen_status="idle",
            ),
        )

        k_old = brain / "knowledge" / "old-name"
        k_old.mkdir()
        k_new = brain / "knowledge" / "new-name"

        move = FolderMove(src=k_old.resolve(), dest=k_new.resolve())
        mirror_folder_move(brain, move)

        assert load_insight_state(brain, "old-name") is None
        assert load_insight_state(brain, "new-name") is not None
        assert load_insight_state(brain, "new-name/sub") is not None

    def test_updates_source_target_paths(self, brain):
        """Source target_paths updated after move."""
        state = SyncState()
        state.sources["test:123"] = SourceState(
            canonical_id="test:123",
            source_url="https://example.com/page",
            source_type="confluence",
            target_path="old-name",
        )
        state.sources["test:456"] = SourceState(
            canonical_id="test:456",
            source_url="https://example.com/page2",
            source_type="confluence",
            target_path="old-name/sub",
        )
        save_state(brain, state)

        k_old = brain / "knowledge" / "old-name"
        k_old.mkdir()
        k_new = brain / "knowledge" / "new-name"

        move = FolderMove(src=k_old.resolve(), dest=k_new.resolve())
        mirror_folder_move(brain, move)

        loaded = load_state(brain)
        assert loaded.sources["test:123"].target_path == "new-name"
        assert loaded.sources["test:456"].target_path == "new-name/sub"

    def test_no_insights_to_mirror(self, brain):
        """Move succeeds even when there are no insights to mirror."""
        k_old = brain / "knowledge" / "old-name"
        k_old.mkdir()
        k_new = brain / "knowledge" / "new-name"

        move = FolderMove(src=k_old.resolve(), dest=k_new.resolve())
        mirror_folder_move(brain, move)  # Should not raise

    def test_nested_folder_move(self, brain):
        """Nested folder renames mirror correctly."""
        k_old = brain / "knowledge" / "parent" / "old-child"
        k_old.mkdir(parents=True)

        i_old = brain / "insights" / "parent" / "old-child"
        i_old.mkdir(parents=True)
        (i_old / "summary.md").write_text("child summary", encoding="utf-8")

        save_insight_state(
            brain,
            InsightState(
                knowledge_path="parent/old-child",
                content_hash="abc",
            ),
        )

        k_new = brain / "knowledge" / "parent" / "new-child"

        move = FolderMove(src=k_old.resolve(), dest=k_new.resolve())
        mirror_folder_move(brain, move)

        assert (brain / "insights" / "parent" / "new-child" / "summary.md").exists()
        assert load_insight_state(brain, "parent/new-child") is not None
        assert load_insight_state(brain, "parent/old-child") is None

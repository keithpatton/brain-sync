"""Tests for watcher folder move mirroring."""

from __future__ import annotations

import queue

import pytest
from watchdog.events import DirMovedEvent

from brain_sync.state import (
    InsightState,
    _connect,
    load_insight_state,
    save_insight_state,
)
from brain_sync.watcher import FolderMove, KnowledgeEventHandler, mirror_folder_move

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
        """Source target_paths updated in manifests after move."""
        from brain_sync.manifest import (
            MANIFEST_VERSION,
            SourceManifest,
            ensure_manifest_dir,
            read_source_manifest,
            write_source_manifest,
        )

        ensure_manifest_dir(brain)
        for cid, url, tp in [
            ("test:123", "https://example.com/page", "old-name"),
            ("test:456", "https://example.com/page2", "old-name/sub"),
        ]:
            write_source_manifest(
                brain,
                SourceManifest(
                    manifest_version=MANIFEST_VERSION,
                    canonical_id=cid,
                    source_url=url,
                    source_type="confluence",
                    materialized_path="",
                    fetch_children=False,
                    sync_attachments=False,
                    target_path=tp,
                ),
            )

        k_old = brain / "knowledge" / "old-name"
        k_old.mkdir()
        k_new = brain / "knowledge" / "new-name"

        move = FolderMove(src=k_old.resolve(), dest=k_new.resolve())
        mirror_folder_move(brain, move)

        m1 = read_source_manifest(brain, "test:123")
        m2 = read_source_manifest(brain, "test:456")
        assert m1 is not None
        assert m2 is not None
        assert m1.target_path == "new-name"
        assert m2.target_path == "new-name/sub"

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


class TestOnMovedPreservesRawPaths:
    """on_moved() must not resolve() DirMovedEvent paths (case-only rename fix)."""

    def test_on_moved_preserves_raw_paths(self, brain):
        event_q: queue.Queue = queue.Queue()
        move_q: queue.Queue = queue.Queue()
        knowledge_root = brain / "knowledge"

        handler = KnowledgeEventHandler(event_q, move_q, knowledge_root)

        # Simulate a case-only rename event with different casing
        src = str(knowledge_root / "MyArea")
        dest = str(knowledge_root / "myarea")
        event = DirMovedEvent(src, dest)

        handler.on_moved(event)

        assert not move_q.empty()
        move = move_q.get_nowait()
        # Paths should preserve original casing, not be resolve()-d
        assert move.src.name == "MyArea"
        assert move.dest.name == "myarea"

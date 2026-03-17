from __future__ import annotations

import queue
import shutil
from pathlib import Path

import pytest
from watchdog.events import DirMovedEvent

from brain_sync.application.insights import load_insight_state, save_insight_state
from brain_sync.brain.manifest import (
    MANIFEST_VERSION,
    SourceManifest,
    ensure_manifest_dir,
    read_source_manifest,
    write_source_manifest,
)
from brain_sync.runtime.repository import InsightState, _connect
from brain_sync.sync.watcher import FolderMove, KnowledgeEventHandler, mirror_folder_move

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    (root / "knowledge").mkdir(parents=True)
    (root / ".brain-sync" / "brain.json").parent.mkdir(parents=True, exist_ok=True)
    (root / ".brain-sync" / "brain.json").write_text('{"version": 1}\n', encoding="utf-8")
    conn = _connect(root)
    conn.close()
    return root


class TestMirrorFolderMove:
    def test_updates_colocated_summary_paths_by_real_fs_move(self, brain: Path) -> None:
        old_dir = brain / "knowledge" / "old-name"
        old_dir.mkdir(parents=True)
        (old_dir / ".brain-sync" / "insights").mkdir(parents=True)
        (old_dir / ".brain-sync" / "insights" / "summary.md").write_text("summary", encoding="utf-8")

        new_dir = brain / "knowledge" / "new-name"
        shutil.move(str(old_dir), str(new_dir))

        mirror_folder_move(brain, FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()))

        assert not (brain / "knowledge" / "old-name").exists()
        assert (brain / "knowledge" / "new-name" / ".brain-sync" / "insights" / "summary.md").exists()

    def test_updates_insight_state_path(self, brain: Path) -> None:
        old_dir = brain / "knowledge" / "old-name"
        (old_dir / ".brain-sync" / "insights").mkdir(parents=True)
        save_insight_state(brain, InsightState(knowledge_path="old-name", content_hash="abc", regen_status="idle"))
        save_insight_state(brain, InsightState(knowledge_path="old-name/sub", content_hash="def", regen_status="idle"))

        new_dir = brain / "knowledge" / "new-name"
        shutil.move(str(old_dir), str(new_dir))

        mirror_folder_move(brain, FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()))

        assert load_insight_state(brain, "old-name") is None
        assert load_insight_state(brain, "new-name") is not None
        assert load_insight_state(brain, "new-name/sub") is not None

    def test_updates_source_target_paths_in_manifests(self, brain: Path) -> None:
        ensure_manifest_dir(brain)
        for cid, url, target_path in [
            ("confluence:123", "https://example.com/123", "old-name"),
            ("confluence:456", "https://example.com/456", "old-name/sub"),
        ]:
            write_source_manifest(
                brain,
                SourceManifest(
                    version=MANIFEST_VERSION,
                    canonical_id=cid,
                    source_url=url,
                    source_type="confluence",
                    materialized_path="",
                    sync_attachments=False,
                    target_path=target_path,
                ),
            )

        old_dir = brain / "knowledge" / "old-name"
        old_dir.mkdir(parents=True)
        new_dir = brain / "knowledge" / "new-name"
        shutil.move(str(old_dir), str(new_dir))

        mirror_folder_move(brain, FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()))

        m1 = read_source_manifest(brain, "confluence:123")
        m2 = read_source_manifest(brain, "confluence:456")

        assert m1 is not None and m1.target_path == "new-name"
        assert m2 is not None and m2.target_path == "new-name/sub"

    def test_noop_when_move_not_within_knowledge(self, brain: Path) -> None:
        outside_src = brain.parent / "outside-old"
        outside_dest = brain.parent / "outside-new"
        outside_src.mkdir()

        mirror_folder_move(brain, FolderMove(src=outside_src.resolve(), dest=outside_dest.resolve()))

        assert outside_src.exists()


class TestOnMovedPreservesRawPaths:
    def test_on_moved_preserves_raw_paths(self, brain: Path) -> None:
        event_q: queue.Queue = queue.Queue()
        move_q: queue.Queue = queue.Queue()
        knowledge_root = brain / "knowledge"
        handler = KnowledgeEventHandler(event_q, move_q, knowledge_root)

        src = str(knowledge_root / "MyArea")
        dest = str(knowledge_root / "myarea")
        event = DirMovedEvent(src, dest)

        handler.on_moved(event)

        move = move_q.get_nowait()
        assert move.src.name == "MyArea"
        assert move.dest.name == "myarea"

from __future__ import annotations

import queue
import shutil
import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from watchdog.events import DirMovedEvent

from brain_sync.application.init import init_brain
from brain_sync.application.insights import InsightState, load_insight_state, save_insight_state
from brain_sync.application.sync_events import apply_folder_move
from brain_sync.brain.manifest import MANIFEST_VERSION, SourceManifest, read_source_manifest, write_source_manifest
from brain_sync.brain.repository import BrainRepository
from brain_sync.runtime.repository import acquire_source_lifecycle_lease, clear_source_lifecycle_lease
from brain_sync.sync.watcher import FolderMove, KnowledgeEventHandler

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    init_brain(root)
    return root


def _start_lease_attempt(root: Path, canonical_id: str, owner_id: str) -> tuple[threading.Event, threading.Thread]:
    finished = threading.Event()

    def _runner() -> None:
        try:
            acquire_source_lifecycle_lease(
                root,
                canonical_id,
                owner_id,
                lease_expires_utc="2099-01-01T00:00:00+00:00",
            )
        finally:
            finished.set()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return finished, thread


class TestApplyFolderMove:
    def test_updates_colocated_summary_paths_by_real_fs_move(self, brain: Path) -> None:
        old_dir = brain / "knowledge" / "old-name"
        old_dir.mkdir(parents=True)
        (old_dir / ".brain-sync" / "insights").mkdir(parents=True)
        (old_dir / ".brain-sync" / "insights" / "summary.md").write_text("summary", encoding="utf-8")

        new_dir = brain / "knowledge" / "new-name"
        shutil.move(str(old_dir), str(new_dir))

        apply_folder_move(brain, move=FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()))

        assert not (brain / "knowledge" / "old-name").exists()
        assert (brain / "knowledge" / "new-name" / ".brain-sync" / "insights" / "summary.md").exists()

    def test_updates_insight_state_path(self, brain: Path) -> None:
        old_dir = brain / "knowledge" / "old-name"
        (old_dir / ".brain-sync" / "insights").mkdir(parents=True)
        save_insight_state(brain, InsightState(knowledge_path="old-name", content_hash="abc", regen_status="idle"))
        save_insight_state(brain, InsightState(knowledge_path="old-name/sub", content_hash="def", regen_status="idle"))

        new_dir = brain / "knowledge" / "new-name"
        shutil.move(str(old_dir), str(new_dir))

        apply_folder_move(brain, move=FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()))

        assert load_insight_state(brain, "old-name") is None
        assert load_insight_state(brain, "new-name") is not None
        assert load_insight_state(brain, "new-name/sub") is not None

    def test_updates_source_knowledge_paths_in_manifests(self, brain: Path) -> None:
        for cid, url, knowledge_path, state in [
            ("confluence:123", "https://example.com/123", "old-name/c123.md", "materialized"),
            ("confluence:456", "https://example.com/456", "old-name/sub/c456.md", "awaiting"),
        ]:
            manifest_kwargs = {
                "version": MANIFEST_VERSION,
                "canonical_id": cid,
                "source_url": url,
                "source_type": "confluence",
                "sync_attachments": False,
                "knowledge_path": knowledge_path,
                "knowledge_state": state,
            }
            if state == "materialized":
                manifest_kwargs.update(
                    {
                        "content_hash": "sha256:abc",
                        "remote_fingerprint": "rev-1",
                        "materialized_utc": "2026-03-19T09:00:00+00:00",
                    }
                )
            write_source_manifest(brain, SourceManifest(**manifest_kwargs))

        old_dir = brain / "knowledge" / "old-name"
        old_dir.mkdir(parents=True)
        new_dir = brain / "knowledge" / "new-name"
        shutil.move(str(old_dir), str(new_dir))

        apply_folder_move(brain, move=FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()))

        m1 = read_source_manifest(brain, "confluence:123")
        m2 = read_source_manifest(brain, "confluence:456")

        assert m1 is not None and m1.knowledge_path == "new-name/c123.md"
        assert m1.knowledge_state == "stale"
        assert m2 is not None and m2.knowledge_path == "new-name/sub/c456.md"
        assert m2.knowledge_state == "awaiting"

    def test_noop_when_move_not_within_knowledge(self, brain: Path) -> None:
        outside_src = brain.parent / "outside-old"
        outside_dest = brain.parent / "outside-new"
        outside_src.mkdir()

        apply_folder_move(brain, move=FolderMove(src=outside_src.resolve(), dest=outside_dest.resolve()))

        assert outside_src.exists()

    def test_skips_leased_sources_individually(self, brain: Path) -> None:
        write_source_manifest(
            brain,
            SourceManifest(
                version=MANIFEST_VERSION,
                canonical_id="confluence:123",
                source_url="https://example.com/123",
                source_type="confluence",
                sync_attachments=False,
                knowledge_path="old-name/c123.md",
                knowledge_state="awaiting",
            ),
        )
        write_source_manifest(
            brain,
            SourceManifest(
                version=MANIFEST_VERSION,
                canonical_id="confluence:456",
                source_url="https://example.com/456",
                source_type="confluence",
                sync_attachments=False,
                knowledge_path="old-name/c456.md",
                knowledge_state="awaiting",
            ),
        )

        old_dir = brain / "knowledge" / "old-name"
        old_dir.mkdir(parents=True)
        new_dir = brain / "knowledge" / "new-name"
        shutil.move(str(old_dir), str(new_dir))

        acquired, _existing = acquire_source_lifecycle_lease(
            brain,
            "confluence:123",
            "move-owner",
            lease_expires_utc="2099-01-01T00:00:00+00:00",
        )
        assert acquired is True

        apply_folder_move(brain, move=FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()))

        leased = read_source_manifest(brain, "confluence:123")
        free = read_source_manifest(brain, "confluence:456")

        assert leased is not None
        assert leased.knowledge_path == "old-name/c123.md"
        assert free is not None
        assert free.knowledge_path == "new-name/c456.md"

    def test_last_moment_lease_takeover_waits_until_folder_move_commit_finishes(self, brain: Path) -> None:
        write_source_manifest(
            brain,
            SourceManifest(
                version=MANIFEST_VERSION,
                canonical_id="confluence:123",
                source_url="https://example.com/123",
                source_type="confluence",
                sync_attachments=False,
                knowledge_path="old-name/c123.md",
                knowledge_state="materialized",
                content_hash="sha256:abc",
                remote_fingerprint="rev-1",
                materialized_utc="2026-03-19T09:00:00+00:00",
            ),
        )

        old_dir = brain / "knowledge" / "old-name"
        old_dir.mkdir(parents=True)
        new_dir = brain / "knowledge" / "new-name"
        shutil.move(str(old_dir), str(new_dir))

        original_apply_folder_move = BrainRepository.apply_folder_move_to_manifest
        move_owner = "move-owner"
        finished: threading.Event | None = None
        thread: threading.Thread | None = None

        def _gated_apply_folder_move(self, canonical_id: str, src_rel: str, dest_rel: str) -> None:
            nonlocal finished, thread
            finished, thread = _start_lease_attempt(brain, canonical_id, move_owner)
            assert finished.wait(0.2) is False
            original_apply_folder_move(self, canonical_id, src_rel, dest_rel)

        with patch(
            "brain_sync.brain.repository.BrainRepository.apply_folder_move_to_manifest",
            new=_gated_apply_folder_move,
        ):
            apply_folder_move(brain, move=FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()))

        assert finished is not None and thread is not None
        assert finished.wait(2.0) is True
        thread.join(timeout=2.0)

        moved = read_source_manifest(brain, "confluence:123")
        assert moved is not None
        assert moved.knowledge_path == "new-name/c123.md"
        clear_source_lifecycle_lease(brain, "confluence:123", owner_id=move_owner)


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

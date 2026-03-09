from __future__ import annotations

import logging
import queue
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import (
    DirMovedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

from brain_sync.fileops import EXCLUDED_DIRS
from brain_sync.fs_utils import normalize_path

log = logging.getLogger(__name__)

DEBOUNCE_SECS = 30.0

# Patterns to ignore (OneDrive temp files, Office lock files, etc.)
IGNORE_PATTERNS = re.compile(
    r"(\.~lock|~\$|\.tmp$|\.temp$|\.partial$|\.download$|desktop\.ini$)",
    re.IGNORECASE,
)


@dataclass
class FolderMove:
    """A detected folder rename/move within knowledge/."""

    src: Path
    dest: Path


def _should_ignore(path: Path, knowledge_root: Path) -> bool:
    """Check if a path should be ignored by the watcher."""
    name = path.name
    if IGNORE_PATTERNS.search(name):
        return True
    # Ignore excluded directories (e.g. _sync-context/ managed by sync engine)
    try:
        rel = path.relative_to(knowledge_root)
        parts = rel.parts
        if any(part in EXCLUDED_DIRS for part in parts):
            return True
    except ValueError:
        pass
    return False


class KnowledgeEventHandler(FileSystemEventHandler):
    def __init__(
        self,
        event_queue: queue.Queue[Path],
        move_queue: queue.Queue[FolderMove],
        knowledge_root: Path,
    ) -> None:
        super().__init__()
        self._queue = event_queue
        self._move_queue = move_queue
        self._knowledge_root = knowledge_root

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if _should_ignore(path, self._knowledge_root):
            return
        # Invalidate global context cache if change is in _core/
        try:
            rel = path.relative_to(self._knowledge_root)
            if rel.parts and rel.parts[0] == "_core":
                from brain_sync.regen import invalidate_global_context_cache

                invalidate_global_context_cache()
        except ValueError:
            pass
        self._queue.put(path.resolve())

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        if isinstance(event, DirMovedEvent):
            src = Path(str(event.src_path)).resolve()
            dest = Path(str(event.dest_path)).resolve()
            if not _should_ignore(src, self._knowledge_root) and not _should_ignore(dest, self._knowledge_root):
                self._move_queue.put(FolderMove(src=src, dest=dest))
        elif isinstance(event, FileMovedEvent):
            # Treat file moves as a change in the destination folder
            dest = Path(str(event.dest_path))
            if not _should_ignore(dest, self._knowledge_root):
                self._queue.put(dest.resolve())


def mirror_folder_move(root: Path, move: FolderMove) -> None:
    """Mirror a knowledge/ folder rename into insights/ and update DB state."""
    knowledge_root = root / "knowledge"
    insights_root = root / "insights"

    try:
        src_rel = move.src.relative_to(knowledge_root)
        dest_rel = move.dest.relative_to(knowledge_root)
    except ValueError:
        log.debug("Move not within knowledge/: %s -> %s", move.src, move.dest)
        return

    src_rel_str = normalize_path(src_rel)
    dest_rel_str = normalize_path(dest_rel)

    insights_src = insights_root / src_rel
    insights_dest = insights_root / dest_rel

    if insights_src.is_dir():
        insights_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(insights_src), str(insights_dest))
        log.info("Mirrored insights move: %s -> %s", src_rel_str, dest_rel_str)
    else:
        log.debug("No insights to mirror for: %s", src_rel_str)

    # Update insight_state paths in DB
    try:
        from brain_sync.state import load_all_insight_states, update_insight_path

        all_states = load_all_insight_states(root)
        for istate in all_states:
            if istate.knowledge_path == src_rel_str or istate.knowledge_path.startswith(src_rel_str + "/"):
                new_path = dest_rel_str + istate.knowledge_path[len(src_rel_str) :]
                update_insight_path(root, istate.knowledge_path, new_path)
                log.debug("Updated insight_state: %s -> %s", istate.knowledge_path, new_path)
    except Exception as e:
        log.warning("Failed to update insight_state after move: %s", e)

    # Update sources target_path directly in DB
    try:
        from brain_sync.state import load_state, update_source_target_path

        state = load_state(root)
        for ss in state.sources.values():
            if ss.target_path == src_rel_str or ss.target_path.startswith(src_rel_str + "/"):
                new_tp = dest_rel_str + ss.target_path[len(src_rel_str) :]
                log.info("Updated source target_path: %s -> %s", ss.target_path, new_tp)
                update_source_target_path(root, ss.canonical_id, new_tp)
    except Exception as e:
        log.warning("Failed to update source target_paths after move: %s", e)


class KnowledgeWatcher:
    """Watch knowledge/ folder for file changes, with debounce."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.knowledge_root = root / "knowledge"
        self.event_queue: queue.Queue[Path] = queue.Queue()
        self.move_queue: queue.Queue[FolderMove] = queue.Queue()
        self._observer = Observer()
        self._pending: dict[Path, float] = {}

    def start(self) -> None:
        if not self.knowledge_root.exists():
            log.warning("knowledge/ directory does not exist at %s, watcher inactive", self.knowledge_root)
            return
        handler = KnowledgeEventHandler(self.event_queue, self.move_queue, self.knowledge_root)
        self._observer.schedule(handler, str(self.knowledge_root), recursive=True)
        self._observer.daemon = True
        self._observer.start()
        log.info("Watching %s for knowledge changes", self.knowledge_root)

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=5)

    def drain_moves(self) -> list[FolderMove]:
        """Drain any folder move events. These are processed immediately (no debounce)."""
        moves: list[FolderMove] = []
        while True:
            try:
                moves.append(self.move_queue.get_nowait())
            except queue.Empty:
                break
        return moves

    def drain_events(self) -> set[Path]:
        """Drain queued events, apply debounce, return paths ready to process.

        Returns the set of containing folders (not individual files) that had
        changes, after the debounce window has elapsed.
        """
        now = time.monotonic()

        while True:
            try:
                path = self.event_queue.get_nowait()
                # Group by containing folder
                folder = path.parent
                self._pending[folder] = now + DEBOUNCE_SECS
            except queue.Empty:
                break

        ready: set[Path] = set()
        still_pending: dict[Path, float] = {}
        for folder, fire_at in self._pending.items():
            if now >= fire_at:
                ready.add(folder)
            else:
                still_pending[folder] = fire_at
        self._pending = still_pending

        return ready

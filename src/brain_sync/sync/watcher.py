from __future__ import annotations

import logging
import queue
import re
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

from brain_sync.brain.fileops import EXCLUDED_DIRS, path_exists

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
    # Ignore excluded directories (e.g. _attachments/ managed by sync engine)
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
        self._queue.put(path.resolve())

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        if isinstance(event, DirMovedEvent):
            # Do NOT resolve() — on case-insensitive filesystems, resolve()
            # canonicalises casing, which erases case-only renames.
            src = Path(str(event.src_path))
            dest = Path(str(event.dest_path))
            if not _should_ignore(src, self._knowledge_root) and not _should_ignore(dest, self._knowledge_root):
                self._move_queue.put(FolderMove(src=src, dest=dest))
        elif isinstance(event, FileMovedEvent):
            # Treat file moves as a change in the destination folder
            dest = Path(str(event.dest_path))
            if not _should_ignore(dest, self._knowledge_root):
                self._queue.put(dest.resolve())


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
        if not path_exists(self.knowledge_root):
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

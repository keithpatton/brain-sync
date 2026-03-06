from __future__ import annotations

import logging
import queue
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from brain_sync.manifest import MANIFEST_FILENAME

log = logging.getLogger(__name__)

DEBOUNCE_SECS = 1.0


class ManifestEventHandler(FileSystemEventHandler):
    def __init__(self, event_queue: queue.Queue[Path]) -> None:
        super().__init__()
        self._queue = event_queue

    def _handle(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(str(event.src_path))
        if path.name == MANIFEST_FILENAME:
            self._queue.put(path.resolve())

    def on_created(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        self._handle(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._handle(event)


class ManifestWatcher:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.event_queue: queue.Queue[Path] = queue.Queue()
        self._observer = Observer()
        self._pending: dict[Path, float] = {}

    def start(self) -> None:
        handler = ManifestEventHandler(self.event_queue)
        self._observer.schedule(handler, str(self.root), recursive=True)
        self._observer.daemon = True
        self._observer.start()
        log.info("Watching %s for manifest changes", self.root)

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join(timeout=5)

    def drain_events(self) -> set[Path]:
        """Drain queued events, apply debounce, return paths ready to process."""
        now = time.monotonic()

        while True:
            try:
                path = self.event_queue.get_nowait()
                self._pending[path] = now + DEBOUNCE_SECS
            except queue.Empty:
                break

        ready: set[Path] = set()
        still_pending: dict[Path, float] = {}
        for path, fire_at in self._pending.items():
            if now >= fire_at:
                ready.add(path)
            else:
                still_pending[path] = fire_at
        self._pending = still_pending

        return ready

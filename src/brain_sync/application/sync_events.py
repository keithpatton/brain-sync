"""Application-facing wrappers for sync-owned lifecycle side effects."""

from __future__ import annotations

from pathlib import Path

from brain_sync.application.regen import invalidate_global_context_cache
from brain_sync.sync.lifecycle import (
    FolderChangeOutcome,
    apply_folder_move,
    enqueue_regen_path,
)
from brain_sync.sync.lifecycle import (
    handle_watcher_folder_change as sync_handle_watcher_folder_change,
)

__all__ = [
    "FolderChangeOutcome",
    "apply_folder_move",
    "enqueue_regen_path",
    "handle_watcher_folder_change",
    "invalidate_global_context_cache",
]


def handle_watcher_folder_change(root: Path, *, knowledge_path: str, enqueue) -> FolderChangeOutcome:
    if knowledge_path == "_core":
        invalidate_global_context_cache()
    return sync_handle_watcher_folder_change(root, knowledge_path=knowledge_path, enqueue=enqueue)

"""Application-owned watcher, reconcile, and source-change policy."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from brain_sync.application.query_index import invalidate_area_index
from brain_sync.application.regen import classify_folder_change, invalidate_global_context_cache
from brain_sync.brain.repository import BrainRepository
from brain_sync.brain.tree import normalize_path
from brain_sync.runtime.repository import (
    mark_knowledge_paths_dirty,
    record_operational_event,
    rename_knowledge_path_prefix,
)
from brain_sync.sync.watcher import FolderMove

__all__ = [
    "FolderChangeOutcome",
    "apply_folder_move",
    "enqueue_regen_path",
    "handle_watcher_folder_change",
]


@dataclass(frozen=True)
class FolderChangeOutcome:
    knowledge_path: str
    action: str


def _touch_core_context(knowledge_path: str) -> None:
    if knowledge_path == "_core" or knowledge_path.startswith("_core/"):
        invalidate_global_context_cache()


def _parent_path(knowledge_path: str) -> str:
    if not knowledge_path:
        return ""
    parts = knowledge_path.rsplit("/", 1)
    return parts[0] if len(parts) > 1 else ""


def enqueue_regen_path(
    root: Path,
    *,
    knowledge_path: str,
    enqueue: Callable[[str], None],
    reason: str,
    canonical_id: str | None = None,
) -> None:
    enqueue(knowledge_path)
    mark_knowledge_paths_dirty(root, [knowledge_path], reason=reason)
    invalidate_area_index(root, knowledge_paths=[knowledge_path], reason=reason)
    _touch_core_context(knowledge_path)
    record_operational_event(
        event_type="regen.enqueued",
        canonical_id=canonical_id,
        knowledge_path=knowledge_path,
        outcome=reason,
    )


def handle_watcher_folder_change(
    root: Path,
    *,
    knowledge_path: str,
    enqueue: Callable[[str], None],
) -> FolderChangeOutcome:
    change, _, new_structure_hash = classify_folder_change(root, knowledge_path)
    if change.change_type == "none":
        return FolderChangeOutcome(knowledge_path=knowledge_path, action="ignored")

    if change.structural:
        record_operational_event(
            event_type="watcher.structure_observed",
            knowledge_path=knowledge_path,
            outcome="enqueued",
            details={"new_structure_hash": new_structure_hash},
        )
        enqueue_regen_path(root, knowledge_path=knowledge_path, enqueue=enqueue, reason="structure_only")
        return FolderChangeOutcome(knowledge_path=knowledge_path, action="structure_enqueued")

    enqueue_regen_path(root, knowledge_path=knowledge_path, enqueue=enqueue, reason="watcher_change")
    return FolderChangeOutcome(knowledge_path=knowledge_path, action="enqueued")


def apply_folder_move(
    root: Path,
    *,
    move: FolderMove,
    enqueue: Callable[[str], None] | None = None,
) -> None:
    """Apply portable and runtime consequences of a knowledge-folder move."""
    knowledge_root = root / "knowledge"
    repository = BrainRepository(root)

    try:
        src_rel = normalize_path(move.src.relative_to(knowledge_root))
        dest_rel = normalize_path(move.dest.relative_to(knowledge_root))
    except ValueError:
        return

    record_operational_event(
        event_type="watcher.move_observed",
        knowledge_path=dest_rel,
        outcome="observed",
        details={"src": src_rel, "dest": dest_rel},
    )
    rename_knowledge_path_prefix(root, src_rel, dest_rel)
    repository.apply_folder_move_to_manifests(src_rel, dest_rel)
    impacted_paths = {
        src_rel,
        dest_rel,
        _parent_path(src_rel),
        _parent_path(dest_rel),
    }
    invalidate_area_index(root, knowledge_paths=sorted(impacted_paths), reason="folder_move")
    _touch_core_context(src_rel)
    _touch_core_context(dest_rel)
    record_operational_event(
        event_type="watcher.move_applied",
        knowledge_path=dest_rel,
        outcome="applied",
        details={"src": src_rel, "dest": dest_rel},
    )
    if enqueue is not None:
        enqueue_regen_path(root, knowledge_path=dest_rel, enqueue=enqueue, reason="folder_move")
        src_parent = _parent_path(src_rel)
        dest_parent = _parent_path(dest_rel)
        if src_parent != dest_parent:
            enqueue_regen_path(root, knowledge_path=src_parent, enqueue=enqueue, reason="folder_move")

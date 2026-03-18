"""Application-owned area-index lifecycle helpers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from brain_sync.query.area_index import AreaIndex
from brain_sync.runtime.repository import (
    clear_invalidation_token,
    load_invalidation_token,
    record_operational_event,
)
from brain_sync.runtime.repository import (
    invalidate_area_index as invalidate_area_index_runtime,
)

__all__ = ["AreaIndex", "invalidate_area_index", "load_area_index"]


def load_area_index(root: Path, current: AreaIndex | None = None) -> AreaIndex:
    """Return a usable area index, rebuilding only when needed."""
    token = load_invalidation_token(root, "area_index")
    if current is not None and not current.is_stale(token.generation, dirty=token.dirty):
        return current
    rebuilt = AreaIndex.build(root, generation=token.generation)
    clear_invalidation_token(root, "area_index")
    record_operational_event(
        event_type="query.index.rebuilt",
        outcome="rebuilt",
        details={"generation": token.generation},
    )
    return rebuilt


def invalidate_area_index(
    root: Path,
    current: AreaIndex | None = None,
    *,
    knowledge_paths: Iterable[str] = (),
    reason: str = "knowledge_changed",
) -> AreaIndex | None:
    """Mark the runtime area-index token dirty after a known knowledge-tree mutation."""
    invalidate_area_index_runtime(root, knowledge_paths, reason=reason)
    if current is not None:
        current.mark_stale()
    return current

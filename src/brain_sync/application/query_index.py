"""Application-owned area-index lifecycle helpers."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from brain_sync.query.area_index import AreaIndex
from brain_sync.runtime.repository import record_brain_operational_event

__all__ = ["AreaIndex", "invalidate_area_index", "load_area_index"]


def load_area_index(root: Path, current: AreaIndex | None = None) -> AreaIndex:
    """Return a usable area index, rebuilding when portable state changed."""
    if current is not None and not current.is_stale(root):
        return current
    rebuilt = AreaIndex.build(root)
    record_brain_operational_event(
        root,
        event_type="query.index.rebuilt",
        outcome="rebuilt",
    )
    return rebuilt


def invalidate_area_index(
    root: Path,
    current: AreaIndex | None = None,
    *,
    knowledge_paths: Iterable[str] = (),
    reason: str = "knowledge_changed",
) -> AreaIndex | None:
    """Mark the current in-memory area index stale and record an event."""
    normalized_paths = [str(path).replace("\\", "/").rstrip("/") for path in knowledge_paths]
    normalized_paths = ["" if path == "." else path for path in normalized_paths]
    record_brain_operational_event(
        root,
        event_type="query.index.invalidated",
        knowledge_path=normalized_paths[0] if len(normalized_paths) == 1 else None,
        outcome=reason,
        details={"knowledge_paths": normalized_paths},
    )
    if current is not None:
        current.mark_stale()
    return current

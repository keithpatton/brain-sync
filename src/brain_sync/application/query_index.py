"""Application-owned area-index lifecycle helpers."""

from __future__ import annotations

from pathlib import Path

from brain_sync.query.area_index import AreaIndex

__all__ = ["AreaIndex", "invalidate_area_index", "load_area_index"]


def load_area_index(root: Path, current: AreaIndex | None = None) -> AreaIndex:
    """Return a usable area index, rebuilding only when needed."""
    if current is not None and not current.is_stale(root):
        return current
    return AreaIndex.build(root)


def invalidate_area_index(current: AreaIndex | None) -> AreaIndex | None:
    """Mark a cached area index stale after a known knowledge-tree mutation."""
    if current is not None:
        current.mark_stale()
    return current

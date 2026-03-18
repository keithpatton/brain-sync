"""Wave-topology helpers for regen scheduling.

Owns path-parent relations and dirty-propagation rules used by the regen
engine and queue. Does not own prompt assembly or LLM execution.
"""

from __future__ import annotations

PROPAGATES_UP = frozenset(
    {
        "regenerated",
        "skipped_no_content",
        "cleaned_up",
        "skipped_rename",
    }
)


def parent_path(path: str) -> str:
    """Return the parent of a knowledge path, or "" for root-level paths."""
    if not path:
        return ""
    parts = path.rsplit("/", 1)
    return parts[0] if len(parts) > 1 else ""


def compute_waves(paths: list[str]) -> list[list[str]]:
    """Compute depth-ordered waves from leaf paths including all ancestors."""
    if not paths:
        return []

    by_depth: dict[int, set[str]] = {}
    for path in paths:
        current = path
        while True:
            depth = 0 if not current else len(current.split("/"))
            by_depth.setdefault(depth, set()).add(current)
            if not current:
                break
            current = parent_path(current)

    return [sorted(by_depth[depth]) for depth in sorted(by_depth, reverse=True)]

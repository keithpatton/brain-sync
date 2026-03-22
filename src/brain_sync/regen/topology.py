"""Wave-topology helpers for regen scheduling.

Owns path-parent relations and dirty-propagation rules used by the regen
engine and queue. Does not own prompt assembly or LLM execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ParentDirtyReason = Literal[
    "child_summary_changed",
    "child_input_removed",
    "parent_structure_changed",
]


@dataclass(frozen=True)
class PropagationRule:
    """Authoritative parent-invalidation rule for one regen outcome."""

    parent_input_changed: bool
    propagate_upward: bool
    dirty_reason: ParentDirtyReason | None
    explanation: str


PROPAGATION_RULES: dict[str, PropagationRule] = {
    "regenerated": PropagationRule(
        parent_input_changed=True,
        propagate_upward=True,
        dirty_reason="child_summary_changed",
        explanation="child summary changed on disk",
    ),
    "skipped_no_content": PropagationRule(
        parent_input_changed=True,
        propagate_upward=True,
        dirty_reason="child_input_removed",
        explanation="child summary/input disappeared",
    ),
    "cleaned_up": PropagationRule(
        parent_input_changed=True,
        propagate_upward=True,
        dirty_reason="child_input_removed",
        explanation="child summary/input disappeared",
    ),
    "skipped_rename": PropagationRule(
        parent_input_changed=False,
        propagate_upward=False,
        dirty_reason=None,
        explanation="local structure changed but no parent-visible input changed here",
    ),
    "skipped_unchanged": PropagationRule(
        parent_input_changed=False,
        propagate_upward=False,
        dirty_reason=None,
        explanation="no parent input changed",
    ),
    "skipped_similarity": PropagationRule(
        parent_input_changed=False,
        propagate_upward=False,
        dirty_reason=None,
        explanation="summary on disk unchanged",
    ),
    "skipped_backfill": PropagationRule(
        parent_input_changed=False,
        propagate_upward=False,
        dirty_reason=None,
        explanation="metadata only; no on-disk input changed",
    ),
    "failed": PropagationRule(
        parent_input_changed=False,
        propagate_upward=False,
        dirty_reason=None,
        explanation="failed work must not dirty parent by default",
    ),
}

PROPAGATES_UP = frozenset(action for action, rule in PROPAGATION_RULES.items() if rule.propagate_upward)


def propagation_rule(action: str) -> PropagationRule:
    """Return the authoritative propagation rule for *action*."""

    return PROPAGATION_RULES.get(
        action,
        PropagationRule(
            parent_input_changed=False,
            propagate_upward=False,
            dirty_reason=None,
            explanation="unknown action defaults to no propagation",
        ),
    )


def propagates_up(action: str) -> bool:
    """Return whether *action* should dirty and process the parent."""

    return propagation_rule(action).propagate_upward


def parent_dirty_reason(action: str) -> ParentDirtyReason | None:
    """Return the parent-dirty reason for *action*, if any."""

    return propagation_rule(action).dirty_reason


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

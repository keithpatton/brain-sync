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
QueueStrategy = Literal["single_path_walk_up", "wave_batch"]


@dataclass(frozen=True)
class PropagationRule:
    """Authoritative parent-invalidation rule for one regen outcome."""

    parent_input_changed: bool
    propagate_upward: bool
    dirty_reason: ParentDirtyReason | None
    explanation: str


@dataclass(frozen=True)
class QueueBatchDecision:
    """Explicit scheduler decision for one queue-ready batch."""

    strategy: QueueStrategy
    ready_paths: tuple[str, ...]
    scheduled_paths: tuple[str, ...]
    waves: tuple[tuple[str, ...], ...]
    reason: str


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


def walk_up_chain(path: str, *, max_depth: int = 10) -> tuple[str, ...]:
    """Return the bounded leaf-to-root chain for single-path walk-up."""

    current = path
    chain: list[str] = []
    for _ in range(max_depth):
        chain.append(current)
        if not current:
            break
        current = parent_path(current)
    return tuple(chain)


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


def decide_queue_batch(ready_paths: list[str], *, max_depth: int = 10) -> QueueBatchDecision:
    """Choose the explicit queue scheduling strategy for one ready snapshot."""

    unique_ready = tuple(dict.fromkeys(ready_paths))
    if len(unique_ready) == 1:
        scheduled_paths = walk_up_chain(unique_ready[0], max_depth=max_depth)
        return QueueBatchDecision(
            strategy="single_path_walk_up",
            ready_paths=unique_ready,
            scheduled_paths=scheduled_paths,
            waves=(),
            reason="one dirty seed is ready, so keep the bounded immediate walk-up special case",
        )

    waves = tuple(tuple(wave) for wave in compute_waves(list(unique_ready)))
    return QueueBatchDecision(
        strategy="wave_batch",
        ready_paths=unique_ready,
        scheduled_paths=tuple(path for wave in waves for path in wave),
        waves=waves,
        reason="multiple ready seeds share ancestor dedupe, so use one explicit wave batch",
    )

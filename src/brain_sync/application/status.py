"""Application-owned status and usage reporting workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brain_sync.application.insights import load_all_insight_states
from brain_sync.application.sources import list_sources
from brain_sync.runtime.config import active_brain_root
from brain_sync.runtime.token_tracking import get_usage_summary as load_usage_summary

__all__ = ["StatusSummary", "UsageSummary", "build_status_summary", "get_usage_summary"]

UsageRow = dict[str, int | str]


@dataclass(frozen=True)
class UsageSummary:
    days: int
    total_input: int
    total_output: int
    total_tokens: int
    total_invocations: int
    by_operation: list[UsageRow]
    by_day: list[UsageRow]


@dataclass(frozen=True)
class StatusSummary:
    source_count: int
    insight_states_by_status: dict[str, int]
    usage: UsageSummary
    usage_available: bool = True


def _runtime_usage_available(root: Path | None) -> bool:
    if root is None:
        return True
    active_root = active_brain_root()
    if active_root is None:
        return False
    return root.resolve() == active_root.resolve()


def _empty_usage_summary(days: int) -> UsageSummary:
    return UsageSummary(
        days=days,
        total_input=0,
        total_output=0,
        total_tokens=0,
        total_invocations=0,
        by_operation=[],
        by_day=[],
    )


def build_status_summary(root: Path, *, usage_days: int = 7) -> StatusSummary:
    sources = list_sources(root=root)
    states = load_all_insight_states(root)
    by_status: dict[str, int] = {}
    for state in states:
        by_status[state.regen_status] = by_status.get(state.regen_status, 0) + 1
    usage_available = _runtime_usage_available(root)
    return StatusSummary(
        source_count=len(sources),
        insight_states_by_status=by_status,
        usage=get_usage_summary(root, days=usage_days),
        usage_available=usage_available,
    )


def get_usage_summary(root: Path | None = None, *, days: int = 7) -> UsageSummary:
    """Return token telemetry for the active runtime tied to *root*.

    Token usage lives in the config-dir runtime DB. If an explicit root does
    not match the active runtime root, return an empty summary rather than
    mixing another brain's portable state with active-runtime telemetry.
    """
    if not _runtime_usage_available(root):
        return _empty_usage_summary(days)
    raw = load_usage_summary(days=days)
    return UsageSummary(
        days=days,
        total_input=raw["total_input"],
        total_output=raw["total_output"],
        total_tokens=raw["total_tokens"],
        total_invocations=raw["total_invocations"],
        by_operation=raw["by_operation"],
        by_day=raw["by_day"],
    )

"""Diagnostic reporting over existing REGEN runtime event surfaces.

Builds compact reports from the runtime operational-event trail and token
telemetry without introducing a new runtime table. This module explains REGEN
decisions and cost using the durable surfaces approved for Phase 5.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from brain_sync.runtime.operational_events import OperationalEventType
from brain_sync.runtime.repository import load_operational_events, load_token_events

_REGEN_EVENT_TYPES = {
    OperationalEventType.REGEN_STARTED.value,
    OperationalEventType.REGEN_COMPLETED.value,
    OperationalEventType.REGEN_FAILED.value,
}
_SEMANTIC_EVENTS_SURFACE = "operational" + "_events"
_NO_CALL_EVALUATION_OUTCOMES = {"missing_path", "no_content", "unchanged", "structure_only", "metadata_backfill"}


def _event_details(details_json: str | None) -> dict[str, Any]:
    if not details_json:
        return {}
    loaded = json.loads(details_json)
    return loaded if isinstance(loaded, dict) else {}


def _clear_latest_no_call_prompt_fields(report: dict[str, Any]) -> None:
    """Reset latest-run prompt and chunk metadata for no-call terminal outcomes."""

    report["prompt_budget_class"] = None
    report["component_tokens"] = {}
    report["deferred_file_count"] = 0
    report["deferred_files"] = []
    report["omitted_child_summary_count"] = 0
    report["omitted_child_summaries"] = []
    report["chunk_count"] = 0
    report["chunked_file_count"] = 0
    report["chunked_files"] = []


def build_regen_diagnostic_report(root: Path, *, session_id: str | None = None) -> dict[str, Any]:
    """Aggregate REGEN observability into one compact report."""

    events = [
        event
        for event in load_operational_events(root)
        if event.event_type in _REGEN_EVENT_TYPES and (session_id is None or event.session_id == session_id)
    ]
    token_rows = load_token_events(root, session_id=session_id, operation_type="regen")

    path_reports: dict[str, dict[str, Any]] = {}
    outcome_counts: Counter[str] = Counter()
    terminal_reason_coverage = 0
    prompt_component_coverage = 0

    def ensure_path_report(knowledge_path: str) -> dict[str, Any]:
        return path_reports.setdefault(
            knowledge_path,
            {
                "knowledge_path": knowledge_path,
                "run_reason": None,
                "evaluation_outcome": None,
                "prompt_budget_class": None,
                "component_tokens": {},
                "deferred_file_count": 0,
                "deferred_files": [],
                "omitted_child_summary_count": 0,
                "omitted_child_summaries": [],
                "latest_event_type": None,
                "latest_outcome": None,
                "latest_reason": None,
                "phase": None,
                "propagates_up": None,
                "parent_input_changed": None,
                "propagation_reason": None,
                "propagation_explanation": None,
                "journal_written": None,
                "summary_written": None,
                "chunk_count": 0,
                "chunked_file_count": 0,
                "chunked_files": [],
                "terminal_event_count": 0,
                "token_cost": {
                    "invocations": 0,
                    "chunk_invocations": 0,
                    "final_invocations": 0,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "duration_ms_total": 0,
                    "chunk_input_tokens": 0,
                    "chunk_output_tokens": 0,
                    "chunk_total_tokens": 0,
                    "final_input_tokens": 0,
                    "final_output_tokens": 0,
                    "final_total_tokens": 0,
                },
            },
        )

    for event in events:
        if event.knowledge_path is None:
            continue
        details = _event_details(event.details_json)
        report = ensure_path_report(event.knowledge_path)
        report["latest_event_type"] = event.event_type

        if event.event_type == OperationalEventType.REGEN_STARTED.value:
            report["run_reason"] = details.get("reason")
            report["evaluation_outcome"] = details.get("evaluation_outcome")
            report["prompt_budget_class"] = details.get("prompt_budget_class")
            report["component_tokens"] = details.get("component_tokens") or {}
            report["deferred_file_count"] = int(details.get("deferred_file_count") or 0)
            report["deferred_files"] = list(details.get("deferred_files") or [])
            report["omitted_child_summary_count"] = int(details.get("omitted_child_summary_count") or 0)
            report["omitted_child_summaries"] = list(details.get("omitted_child_summaries") or [])
            if report["run_reason"] and report["component_tokens"]:
                prompt_component_coverage += 1
            continue

        if event.outcome is not None:
            outcome_counts[event.outcome] += 1
        latest_evaluation_outcome = details.get("evaluation_outcome")
        latest_reason = details.get("reason")
        report["latest_outcome"] = event.outcome
        report["latest_reason"] = latest_reason
        if latest_reason is not None and latest_evaluation_outcome in _NO_CALL_EVALUATION_OUTCOMES:
            report["run_reason"] = latest_reason
        if latest_evaluation_outcome is not None:
            report["evaluation_outcome"] = latest_evaluation_outcome
        if latest_evaluation_outcome in _NO_CALL_EVALUATION_OUTCOMES:
            _clear_latest_no_call_prompt_fields(report)
        report["phase"] = details.get("phase")
        report["propagates_up"] = details.get("propagates_up")
        report["parent_input_changed"] = details.get("parent_input_changed")
        report["propagation_reason"] = details.get("propagation_reason")
        report["propagation_explanation"] = details.get("propagation_explanation")
        report["journal_written"] = details.get("journal_written")
        report["summary_written"] = details.get("summary_written")
        if latest_evaluation_outcome not in _NO_CALL_EVALUATION_OUTCOMES:
            report["chunk_count"] = int(details.get("chunk_count") or report["chunk_count"] or 0)
            report["chunked_file_count"] = int(details.get("chunked_file_count") or report["chunked_file_count"] or 0)
            report["chunked_files"] = list(details.get("chunked_files") or report["chunked_files"] or [])
        report["terminal_event_count"] = int(report["terminal_event_count"]) + 1
        if latest_reason is not None:
            terminal_reason_coverage += 1

    token_cost_by_path: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "invocations": 0,
            "chunk_invocations": 0,
            "final_invocations": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "duration_ms_total": 0,
            "chunk_input_tokens": 0,
            "chunk_output_tokens": 0,
            "chunk_total_tokens": 0,
            "final_input_tokens": 0,
            "final_output_tokens": 0,
            "final_total_tokens": 0,
        }
    )

    for row in token_rows:
        if row.resource_id is None:
            continue
        bucket = token_cost_by_path[row.resource_id]
        bucket["invocations"] += 1
        bucket["input_tokens"] += row.input_tokens or 0
        bucket["output_tokens"] += row.output_tokens or 0
        bucket["total_tokens"] += row.total_tokens or 0
        bucket["duration_ms_total"] += row.duration_ms or 0
        if row.is_chunk:
            bucket["chunk_invocations"] += 1
            bucket["chunk_input_tokens"] += row.input_tokens or 0
            bucket["chunk_output_tokens"] += row.output_tokens or 0
            bucket["chunk_total_tokens"] += row.total_tokens or 0
        else:
            bucket["final_invocations"] += 1
            bucket["final_input_tokens"] += row.input_tokens or 0
            bucket["final_output_tokens"] += row.output_tokens or 0
            bucket["final_total_tokens"] += row.total_tokens or 0

    for knowledge_path, cost in token_cost_by_path.items():
        ensure_path_report(knowledge_path)["token_cost"] = dict(cost)

    high_churn_paths = sorted(
        (
            {
                "knowledge_path": report["knowledge_path"],
                "terminal_event_count": report["terminal_event_count"],
                "latest_outcome": report["latest_outcome"],
                "latest_reason": report["latest_reason"],
            }
            for report in path_reports.values()
            if int(report["terminal_event_count"]) > 1
        ),
        key=lambda item: (-int(item["terminal_event_count"]), str(item["knowledge_path"])),
    )

    total_terminal_events = sum(int(report["terminal_event_count"]) for report in path_reports.values())

    return {
        "observability_contract": {
            "semantic_events_surface": _SEMANTIC_EVENTS_SURFACE,
            "cost_surface": "token_events",
            "coordination_surface": "regen_locks",
            "logs_authoritative": False,
        },
        "session_id": session_id,
        "total_regen_events": len(events),
        "total_terminal_events": total_terminal_events,
        "terminal_reason_coverage_count": terminal_reason_coverage,
        "prompt_component_coverage_count": prompt_component_coverage,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "path_reports": [path_reports[key] for key in sorted(path_reports)],
        "high_churn_paths": high_churn_paths,
        "comparison_ready_keys": [
            "outcome_counts",
            "path_reports[].component_tokens",
            "path_reports[].token_cost",
            "path_reports[].propagates_up",
            "high_churn_paths",
        ],
    }


__all__ = ["build_regen_diagnostic_report"]

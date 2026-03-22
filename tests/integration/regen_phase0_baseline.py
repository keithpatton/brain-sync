"""Phase 0 REGEN baseline corpus and measurement harness."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.insights import InsightState, save_insight_state
from brain_sync.brain.fileops import read_text
from brain_sync.brain.layout import area_summary_path
from brain_sync.llm import capabilities_for_model
from brain_sync.llm.base import LlmResult
from brain_sync.regen.engine import (
    CHUNK_TARGET_CHARS,
    MAX_PROMPT_TOKENS,
    _build_prompt,
    _collect_child_summaries,
    _get_child_dirs,
    regen_path,
    regen_single_folder,
)
from brain_sync.regen.topology import PROPAGATES_UP
from brain_sync.runtime.operational_events import OperationalEventType
from brain_sync.runtime.repository import _connect, load_operational_events
from tests.harness.isolation import apply_in_process_isolation, layout_for_base_dir

_ANCHOR_RE = re.compile(r"ANCHOR:\s*([a-z0-9][a-z0-9-]*)")
_TOKEN_MEASUREMENT_SCOPE = {
    "kind": "application_prompt_body_only",
    "input_token_formula": "len(prompt)//4",
    "included_prompt_parts": [
        "packaged regen instructions assembled into the main prompt body",
        "_core global context assembled by regen",
        "direct file content or chunk summaries assembled by regen",
        "child summaries when present",
        "existing summary when present",
    ],
    "excluded_prompt_parts": [
        "backend system prompt",
        "backend tools or invocation framing outside the assembled prompt body",
        "provider-specific transport overhead or billed-token adjustments",
    ],
}


@dataclass(frozen=True)
class Phase0Corpus:
    small_leaf: str
    large_leaf: str
    wide_parent: str
    rename_leaf: str
    backfill_leaf: str
    backfill_parent: str

    @property
    def required_shapes(self) -> dict[str, str]:
        return {
            "small_leaf_area": self.small_leaf,
            "large_leaf_area": self.large_leaf,
            "parent_with_many_children": self.wide_parent,
            "_core_area": "_core",
            "rename_only_area": self.rename_leaf,
            "metadata_backfill_area": self.backfill_leaf,
        }


class Phase0EvalBackend:
    """Deterministic evaluation backend for Phase 0 corpus runs.

    The backend echoes explicit `ANCHOR:` markers from the prompt into the
    generated summary. This gives Phase 0 a factual-loss harness: if later
    prompt assembly or chunking drops those anchors, the generated summary
    drops them too.

    Token telemetry in this harness is intentionally prompt-body-only:
    `input_tokens` is recorded as `len(prompt)//4` and excludes backend-owned
    system-prompt content, tool framing, and provider-specific billed-token
    overhead.
    """

    def __init__(self, latency_ms: int = 2) -> None:
        self.latency_ms = latency_ms
        self.call_count = 0
        self.prompts: list[dict[str, Any]] = []

    async def invoke(
        self,
        prompt: str,
        cwd: Path,
        timeout: int = 300,
        model: str = "",
        effort: str = "",
        max_turns: int = 6,
        system_prompt: str | None = None,
        tools: str | None = None,
        is_chunk: bool = False,
    ) -> LlmResult:
        # This deterministic harness measures only the application-assembled
        # prompt body. Backend-owned system-prompt content and invocation
        # framing are intentionally excluded from `input_tokens`.
        del cwd, timeout, model, effort, max_turns, system_prompt, tools

        self.call_count += 1
        anchors = _extract_anchors(prompt)
        knowledge_path = _extract_knowledge_path(prompt)
        started = time.monotonic()
        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000)
        duration_ms = max(1, int((time.monotonic() - started) * 1000))

        if is_chunk:
            if anchors:
                output = "Chunk anchors:\n" + "\n".join(f"ANCHOR: {anchor}" for anchor in anchors)
            else:
                output = "Chunk anchors:\nANCHOR: none"
        else:
            summary_lines = [
                "# Evaluation Summary",
                "",
                "Observed anchors:",
            ]
            if anchors:
                summary_lines.extend(f"- {anchor}" for anchor in anchors)
            else:
                summary_lines.append("- no-anchors-found")
            journal_text = "Anchors journal: " + (", ".join(anchors[:8]) if anchors else "none")
            output = (
                "<summary>\n"
                + "\n".join(summary_lines)
                + "\n</summary>\n"
                + "<journal>\n"
                + journal_text
                + "\n</journal>"
            )

        self.prompts.append(
            {
                "knowledge_path": knowledge_path,
                "is_chunk": is_chunk,
                "anchors": anchors,
                "prompt_chars": len(prompt),
            }
        )
        return LlmResult(
            success=True,
            output=output,
            input_tokens=len(prompt) // 4,
            output_tokens=len(output) // 4,
            num_turns=1,
            duration_ms=duration_ms,
            prompt_text=prompt,
        )


def materialize_phase0_corpus(root: Path) -> Phase0Corpus:
    """Create the fictional Phase 0 corpus under a fresh brain root."""
    init_brain(root)

    _write_text(
        root / "knowledge" / "_core" / "mission.md",
        """# Mission

ANCHOR: core-mission
ANCHOR: core-guardrail

The fictional portfolio favors durable summaries over volatile chatter.
""",
    )
    _write_text(
        root / "knowledge" / "_core" / "glossary.md",
        """# Glossary

ANCHOR: core-glossary

- control loop: a repeatable review-and-refine cycle
- checkpoint: a durable handoff state
""",
    )

    _write_text(
        root / "knowledge" / "product" / "atlas" / "brief.md",
        """# Atlas Brief

ANCHOR: atlas-goal
ANCHOR: atlas-risk

Atlas is a fictional initiative focused on reducing redundant regeneration.
""",
    )
    _write_text(
        root / "knowledge" / "product" / "atlas" / "status.md",
        """# Atlas Status

ANCHOR: atlas-status

The current review gate remains manual between plan phases.
""",
    )

    _write_text(
        root / "knowledge" / "research" / "annual" / "report.md",
        _large_markdown(),
    )

    _write_text(
        root / "knowledge" / "programs" / "ops" / "overview.md",
        """# Operations Program

ANCHOR: ops-overview

This parent area synthesizes multiple fictional workstreams.
""",
    )
    for index in range(1, 9):
        child_name = f"child-{index:02d}"
        _write_text(
            root / "knowledge" / "programs" / "ops" / child_name / "notes.md",
            f"""# {child_name}

ANCHOR: {child_name}-signal

{child_name} captures one fictional sub-area for the wide-parent baseline.
""",
        )
        _write_text(
            area_summary_path(root, f"programs/ops/{child_name}"),
            _seeded_child_summary(child_name),
        )

    _write_text(
        root / "knowledge" / "operations" / "overview.md",
        """# Operations Overview

ANCHOR: operations-overview

The rename scenario should not require ancestor semantic churn.
""",
    )
    _write_text(
        root / "knowledge" / "operations" / "rename-demo" / "team-map.md",
        """# Team Map

ANCHOR: rename-signal

Only the filename changes in the rename scenario.
""",
    )

    _write_text(
        root / "knowledge" / "legacy" / "overview.md",
        """# Legacy Overview

ANCHOR: legacy-overview

The backfill scenario models metadata-only churn.
""",
    )
    _write_text(
        root / "knowledge" / "legacy" / "metadata" / "reference.md",
        """# Metadata Reference

ANCHOR: legacy-reference

This area stands in for pre-structure-hash managed state.
""",
    )
    _write_text(
        area_summary_path(root, "legacy/metadata"),
        """# Existing Legacy Summary

Previous generated meaning for the metadata-only backfill path.
""",
    )
    save_insight_state(
        root,
        InsightState(
            knowledge_path="legacy/metadata",
            content_hash="legacy-content-hash",
            summary_hash="legacy-summary-hash",
            structure_hash=None,
            regen_status="idle",
        ),
    )

    return Phase0Corpus(
        small_leaf="product/atlas",
        large_leaf="research/annual",
        wide_parent="programs/ops",
        rename_leaf="operations/rename-demo",
        backfill_leaf="legacy/metadata",
        backfill_parent="legacy",
    )


async def collect_phase0_baseline(root: Path) -> dict[str, Any]:
    """Run the Phase 0 baseline on the fictional corpus and return evidence."""
    corpus = materialize_phase0_corpus(root)
    backend = Phase0EvalBackend()

    await regen_single_folder(root, "_core", backend=backend, session_id="phase0-core-initial")
    await regen_single_folder(root, corpus.small_leaf, backend=backend, session_id="phase0-small-initial")
    await regen_single_folder(root, corpus.large_leaf, backend=backend, session_id="phase0-large-initial")
    await regen_single_folder(root, corpus.wide_parent, backend=backend, session_id="phase0-wide-initial")
    await regen_single_folder(root, corpus.rename_leaf, backend=backend, session_id="phase0-rename-initial")
    await regen_single_folder(root, "operations", backend=backend, session_id="phase0-operations-prime")
    await regen_single_folder(root, corpus.backfill_parent, backend=backend, session_id="phase0-legacy-prime")
    await regen_single_folder(root, "", backend=backend, session_id="phase0-root-prime")

    component_metrics = {
        "_core": _estimate_prompt_components(root, "_core"),
        corpus.small_leaf: _estimate_prompt_components(root, corpus.small_leaf),
        corpus.large_leaf: _estimate_prompt_components(root, corpus.large_leaf),
        corpus.wide_parent: _estimate_prompt_components(root, corpus.wide_parent),
    }

    unchanged_count = await regen_path(
        root,
        corpus.small_leaf,
        backend=backend,
        session_id="phase0-walkup-unchanged",
    )

    rename_dir = root / "knowledge" / corpus.rename_leaf
    (rename_dir / "team-map.md").rename(rename_dir / "team-structure.md")
    rename_count = await regen_path(
        root,
        corpus.rename_leaf,
        backend=backend,
        session_id="phase0-walkup-rename",
    )

    backfill_count = await regen_path(
        root,
        corpus.backfill_leaf,
        backend=backend,
        session_id="phase0-walkup-backfill",
    )

    token_rows = _load_token_rows(root)
    events = load_operational_events(root, event_type=OperationalEventType.REGEN_COMPLETED)
    phase0_sessions = {
        "phase0-core-initial",
        "phase0-small-initial",
        "phase0-large-initial",
        "phase0-wide-initial",
        "phase0-rename-initial",
        "phase0-walkup-unchanged",
        "phase0-walkup-rename",
        "phase0-walkup-backfill",
    }
    phase0_events = [event for event in events if event.session_id in phase0_sessions]
    skip_frequency = Counter(
        event.outcome for event in phase0_events if event.outcome and event.outcome.startswith("skipped_")
    )

    token_usage_per_node = _aggregate_token_usage(token_rows)
    latency_per_node_ms = {
        resource_id: values["duration_ms_total"] for resource_id, values in token_usage_per_node.items()
    }

    prompt_tokens_by_case = {
        knowledge_path: metrics["total_prompt_tokens"] for knowledge_path, metrics in component_metrics.items()
    }

    ancestor_cases = {
        "small_leaf_unchanged": _walkup_case_summary(phase0_events, "phase0-walkup-unchanged", unchanged_count),
        "rename_walkup": _walkup_case_summary(phase0_events, "phase0-walkup-rename", rename_count),
        "backfill_walkup": _walkup_case_summary(phase0_events, "phase0-walkup-backfill", backfill_count),
    }
    ancestor_frequency = {
        "cases": len(ancestor_cases),
        "continued_to_parent": sum(1 for case in ancestor_cases.values() if case["ancestor_event_count"] > 0),
        "rate": round(
            sum(1 for case in ancestor_cases.values() if case["ancestor_event_count"] > 0) / len(ancestor_cases),
            2,
        ),
        "cases_by_name": ancestor_cases,
    }

    chunked_nodes = sorted(
        resource_id for resource_id, values in token_usage_per_node.items() if values["chunk_invocations"] > 0
    )
    non_chunked_nodes = sorted(
        resource_id for resource_id, values in token_usage_per_node.items() if values["chunk_invocations"] == 0
    )

    quality_checks = {
        "_core": _summary_contains_anchors(
            root,
            "_core",
            ["core-mission", "core-guardrail", "core-glossary"],
        ),
        corpus.small_leaf: _summary_contains_anchors(
            root,
            corpus.small_leaf,
            ["atlas-goal", "atlas-risk", "atlas-status"],
        ),
        corpus.large_leaf: _summary_contains_anchors(
            root,
            corpus.large_leaf,
            ["annual-anchor-00", "annual-anchor-12", "annual-anchor-24"],
        ),
        corpus.wide_parent: _summary_contains_anchors(
            root,
            corpus.wide_parent,
            ["child-01-signal", "child-08-signal"],
        ),
    }

    findings = {
        "main_cost_drivers": [
            _top_component_line(component_metrics),
            _top_token_usage_line(token_usage_per_node),
        ],
        "false_positive_drivers": [
            "leaf-only rename walk-up now stops at the renamed area instead of evaluating an unchanged parent",
            "metadata-only backfill now stops at the backfilled area in both walk-up and wave execution",
        ],
        "product_calls": [
            (
                "parent-visible folder renames now rely on explicit move/reconcile enqueue paths "
                "instead of generic skipped_rename walk-up"
            ),
            (
                "the wide-parent case shows child summaries still dominate variable prompt "
                "cost after direct-file packing, while the instructions block remains a "
                "stable fixed cost"
            ),
        ],
    }

    return {
        "corpus": {
            "required_shapes": corpus.required_shapes,
            "paths": {
                "small_leaf": corpus.small_leaf,
                "large_leaf": corpus.large_leaf,
                "wide_parent": corpus.wide_parent,
                "rename_leaf": corpus.rename_leaf,
                "backfill_leaf": corpus.backfill_leaf,
                "backfill_parent": corpus.backfill_parent,
                "_core": "_core",
            },
        },
        "baseline": {
            "token_measurement_scope": _TOKEN_MEASUREMENT_SCOPE,
            "token_usage_per_node": token_usage_per_node,
            "chunked_run_count": len(chunked_nodes),
            "chunked_nodes": chunked_nodes,
            "non_chunked_run_count": len(non_chunked_nodes),
            "non_chunked_nodes": non_chunked_nodes,
            "prompt_size_by_major_component": component_metrics,
            "prompt_tokens_by_case": prompt_tokens_by_case,
            "latency_per_node_ms": latency_per_node_ms,
            "skip_reason_frequency": dict(skip_frequency),
            "ancestor_propagation_frequency": ancestor_frequency,
        },
        "quality_harness": {
            "anchor_checks": quality_checks,
            "all_passed": all(case["ok"] for case in quality_checks.values()),
        },
        "findings": findings,
        "current_contract": {
            "legacy_prompt_override_tokens": MAX_PROMPT_TOKENS,
            "chunk_target_chars": CHUNK_TARGET_CHARS,
            "propagates_up": sorted(PROPAGATES_UP),
        },
    }


def run_phase0_baseline() -> dict[str, Any]:
    """Run the baseline in a standalone isolated temp environment."""
    with tempfile.TemporaryDirectory(prefix="brain-sync-phase0-") as td:
        base = Path(td)
        layout = layout_for_base_dir(base, config_dir_name="config")
        layout.config_dir.mkdir(parents=True, exist_ok=True)
        layout.home_dir.mkdir(parents=True, exist_ok=True)
        root = base / "brain"
        root.mkdir()
        with pytest.MonkeyPatch.context() as monkeypatch:
            apply_in_process_isolation(monkeypatch, layout=layout)
            monkeypatch.setenv("BRAIN_SYNC_LLM_BACKEND", "fake")
            return asyncio.run(collect_phase0_baseline(root))


def main() -> None:
    print(json.dumps(run_phase0_baseline(), indent=2, sort_keys=True))


def _estimate_prompt_components(root: Path, knowledge_path: str) -> dict[str, Any]:
    knowledge_dir = root / "knowledge" / knowledge_path if knowledge_path else root / "knowledge"
    child_dirs = _get_child_dirs(knowledge_dir)
    child_summaries = _collect_child_summaries(root, knowledge_path, child_dirs)
    prompt_result = _build_prompt(
        knowledge_path,
        knowledge_dir,
        child_summaries,
        area_summary_path(root, knowledge_path).parent,
        root,
        capabilities=capabilities_for_model("claude-sonnet-4-6"),
    )
    diagnostics = prompt_result.diagnostics
    assert diagnostics is not None
    return {
        "prompt_budget_class": diagnostics.prompt_budget_class,
        "capability_max_prompt_tokens": diagnostics.capability_max_prompt_tokens,
        "effective_prompt_tokens": diagnostics.effective_prompt_tokens,
        "instructions_tokens": diagnostics.component_tokens["instructions"],
        "global_context_tokens": diagnostics.component_tokens["global_context"],
        "direct_files_tokens": diagnostics.component_tokens["direct_files"],
        "child_summaries_tokens": diagnostics.component_tokens["child_summaries"],
        "existing_summary_tokens": diagnostics.component_tokens["existing_summary"],
        "scaffold_tokens": diagnostics.component_tokens.get("scaffold", 0),
        "total_prompt_tokens": diagnostics.component_tokens["total"],
        "deferred_file_count": len(diagnostics.deferred_files),
        "omitted_child_summary_count": len(diagnostics.omitted_child_summaries),
    }


def _aggregate_token_usage(token_rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Aggregate prompt-body token telemetry emitted by the baseline backend."""

    by_node: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "invocations": 0,
            "chunk_invocations": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "duration_ms_total": 0,
        }
    )
    for row in token_rows:
        resource_id = row["resource_id"]
        if not resource_id:
            continue
        bucket = by_node[resource_id]
        bucket["invocations"] += 1
        bucket["chunk_invocations"] += int(row["is_chunk"])
        bucket["input_tokens"] += row["input_tokens"] or 0
        bucket["output_tokens"] += row["output_tokens"] or 0
        bucket["total_tokens"] += row["total_tokens"] or 0
        bucket["duration_ms_total"] += row["duration_ms"] or 0
    return dict(sorted(by_node.items()))


def _walkup_case_summary(events: list[Any], session_id: str, regenerated_count: int) -> dict[str, Any]:
    session_events = [event for event in events if event.session_id == session_id]
    ordered_paths = [event.knowledge_path or "" for event in session_events]
    return {
        "session_id": session_id,
        "outcomes": [event.outcome for event in session_events],
        "ordered_paths": ordered_paths,
        "ancestor_event_count": max(0, len(session_events) - 1),
        "leaf_outcome": session_events[0].outcome if session_events else None,
        "regenerated_count": regenerated_count,
    }


def _summary_contains_anchors(root: Path, knowledge_path: str, anchors: list[str]) -> dict[str, Any]:
    summary = read_text(area_summary_path(root, knowledge_path), encoding="utf-8")
    missing = [anchor for anchor in anchors if anchor not in summary]
    return {
        "ok": not missing,
        "anchors": anchors,
        "missing": missing,
    }


def _top_component_line(component_metrics: dict[str, dict[str, Any]]) -> str:
    ranked = []
    for knowledge_path, metrics in component_metrics.items():
        component_name, tokens = max(
            (
                ("instructions", metrics["instructions_tokens"]),
                ("global_context", metrics["global_context_tokens"]),
                ("direct_files", metrics["direct_files_tokens"]),
                ("child_summaries", metrics["child_summaries_tokens"]),
                ("existing_summary", metrics["existing_summary_tokens"]),
            ),
            key=lambda pair: pair[1],
        )
        ranked.append((tokens, knowledge_path, component_name))
    tokens, knowledge_path, component_name = max(ranked)
    return f"{knowledge_path}: largest prompt component was {component_name} at ~{tokens} tokens"


def _top_token_usage_line(token_usage_per_node: dict[str, dict[str, int]]) -> str:
    knowledge_path, values = max(token_usage_per_node.items(), key=lambda item: item[1]["total_tokens"])
    return (
        f"{knowledge_path}: highest token burn was {values['total_tokens']} tokens "
        f"across {values['invocations']} LLM invocations"
    )


def _extract_anchors(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(1) for match in _ANCHOR_RE.finditer(text)))


def _extract_knowledge_path(prompt: str) -> str | None:
    marker = "You are regenerating the insight summary for knowledge area:"
    for line in prompt.splitlines():
        if marker in line:
            value = line.split(marker, 1)[1].strip()
            return "" if value == "(root)" else value
    return None


def _large_markdown() -> str:
    blocks = ["# Annual Research Report", "", "ANCHOR: annual-anchor-00", ""]
    for index in range(1, 26):
        blocks.extend(
            [
                f"## Section {index:02d}",
                f"ANCHOR: annual-anchor-{index:02d}",
                (
                    "This fictional long-form section describes evaluation baselines, "
                    "durable checkpoints, and prompt-budget pressure in repeated detail. "
                )
                * 140,
                "",
            ]
        )
    return "\n".join(blocks)


def _seeded_child_summary(child_name: str) -> str:
    return f"# {child_name} Summary\n\nANCHOR: {child_name}-signal\n\n" + (
        "This fictional child summary remains intentionally verbose for parent prompt pressure. " * 40
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _load_token_rows(root: Path) -> list[dict[str, Any]]:
    conn = _connect(root)
    try:
        rows = conn.execute(
            "SELECT session_id, resource_id, is_chunk, input_tokens, output_tokens, total_tokens, duration_ms "
            "FROM token_events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "session_id": row[0],
            "resource_id": row[1],
            "is_chunk": bool(row[2]),
            "input_tokens": row[3],
            "output_tokens": row[4],
            "total_tokens": row[5],
            "duration_ms": row[6],
        }
        for row in rows
    ]


if __name__ == "__main__":
    main()

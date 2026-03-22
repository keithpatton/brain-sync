"""Integration proof for the Phase 0 REGEN baseline harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.integration.regen_phase0_baseline import collect_phase0_baseline

pytestmark = pytest.mark.integration


async def test_phase0_baseline_harness_covers_required_corpus_and_metrics(brain: Path) -> None:
    baseline = await collect_phase0_baseline(brain)

    required_shapes = baseline["corpus"]["required_shapes"]
    assert set(required_shapes) == {
        "small_leaf_area",
        "large_leaf_area",
        "parent_with_many_children",
        "_core_area",
        "rename_only_area",
        "metadata_backfill_area",
    }

    metrics = baseline["baseline"]
    token_scope = metrics["token_measurement_scope"]
    assert token_scope["kind"] == "application_prompt_body_only"
    assert token_scope["input_token_formula"] == "len(prompt)//4"
    assert "backend system prompt" in token_scope["excluded_prompt_parts"]
    assert "provider-specific transport overhead or billed-token adjustments" in token_scope["excluded_prompt_parts"]
    assert "direct file content or chunk summaries assembled by regen" in token_scope["included_prompt_parts"]
    assert metrics["non_chunked_run_count"] >= 3
    assert metrics["skip_reason_frequency"]["skipped_unchanged"] >= 1
    assert metrics["skip_reason_frequency"]["skipped_rename"] >= 1
    assert metrics["skip_reason_frequency"]["skipped_backfill"] >= 1

    ancestor_cases = metrics["ancestor_propagation_frequency"]["cases_by_name"]
    assert ancestor_cases["small_leaf_unchanged"]["ancestor_event_count"] == 0
    assert ancestor_cases["rename_walkup"]["ancestor_event_count"] == 0
    assert ancestor_cases["backfill_walkup"]["ancestor_event_count"] == 0
    assert ancestor_cases["rename_walkup"]["leaf_outcome"] == "skipped_rename"
    assert ancestor_cases["backfill_walkup"]["leaf_outcome"] == "skipped_backfill"

    prompt_components = metrics["prompt_size_by_major_component"]
    assert prompt_components["_core"]["global_context_tokens"] > 0
    assert prompt_components["research/annual"]["prompt_budget_class"] == "extended_1m"
    assert prompt_components["research/annual"]["deferred_file_count"] == 0
    assert prompt_components["programs/ops"]["child_summaries_tokens"] > 0
    diagnostic_report = metrics["diagnostic_report"]
    assert diagnostic_report["observability_contract"]["semantic_events_surface"] == "operational_events"
    assert diagnostic_report["observability_contract"]["cost_surface"] == "token_events"
    assert diagnostic_report["terminal_reason_coverage_count"] >= 1
    assert "path_reports[].token_cost" in diagnostic_report["comparison_ready_keys"]

    quality = baseline["quality_harness"]
    assert quality["all_passed"] is True, json.dumps(quality, indent=2)

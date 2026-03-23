"""Phase 6 tests for scheduler explicitness and backend readiness traits."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.llm import resolve_backend_capabilities
from brain_sync.llm.claude_cli import ClaudeCliBackend
from brain_sync.llm.fake import FakeBackend
from brain_sync.regen.topology import decide_queue_batch

pytestmark = pytest.mark.unit


def test_single_ready_path_keeps_explicit_walk_up_special_case() -> None:
    decision = decide_queue_batch(["initiative/workstream"])

    assert decision.strategy == "single_path_walk_up"
    assert decision.ready_paths == ("initiative/workstream",)
    assert decision.scheduled_paths == ("initiative/workstream", "initiative", "")
    assert decision.waves == ()
    assert "bounded immediate walk-up special case" in decision.reason


def test_multiple_ready_paths_use_explicit_wave_batch() -> None:
    decision = decide_queue_batch(["area/sub1", "area/sub2"])

    assert decision.strategy == "wave_batch"
    assert decision.ready_paths == ("area/sub1", "area/sub2")
    assert decision.waves == (("area/sub1", "area/sub2"), ("area",), ("",))
    assert "share ancestor dedupe" in decision.reason


def test_fake_backend_exposes_low_overhead_parallel_ready_traits(tmp_path: Path) -> None:
    del tmp_path
    capabilities = resolve_backend_capabilities(FakeBackend(), model="fake-model")

    assert capabilities.max_concurrency == 8
    assert capabilities.structured_output.reliability == "strict"
    assert capabilities.invocation.startup_overhead_class == "low"


def test_claude_backend_exposes_high_overhead_single_worker_traits() -> None:
    capabilities = resolve_backend_capabilities(ClaudeCliBackend(), model="claude-sonnet-4-6")

    assert capabilities.prompt_budget_class == "extended_1m"
    assert capabilities.max_prompt_tokens == 1_000_000
    assert capabilities.max_concurrency == 1
    assert capabilities.structured_output.reliability == "strict"
    assert capabilities.invocation.startup_overhead_class == "high"

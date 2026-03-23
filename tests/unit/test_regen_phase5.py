from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import cast
from unittest.mock import patch

import pytest

from brain_sync.application.init import init_brain
from brain_sync.regen.diagnostics import build_regen_diagnostic_report
from brain_sync.regen.engine import ClaudeResult, RegenFailed, _save_terminal_regen_lock, regen_single_folder
from brain_sync.runtime.operational_events import OperationalEventType
from brain_sync.runtime.repository import (
    RegenLock,
    acquire_regen_ownership,
    delete_regen_lock,
    load_operational_events,
    load_regen_lock,
    release_regen_ownership,
    save_regen_lock,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    init_brain(root)
    return root


def _details(event) -> dict[str, object]:
    return json.loads(event.details_json or "{}")


def _structured_output(summary: str, journal: str = "") -> str:
    return f"<summary>\n{summary}\n</summary>\n<journal>\n{journal}\n</journal>"


def _latest_event(brain: Path, event_type: OperationalEventType, session_id: str):
    matches = [
        event for event in load_operational_events(brain, event_type=event_type) if event.session_id == session_id
    ]
    assert matches
    return matches[-1]


def test_regen_events_record_reason_and_propagation_details(brain: Path) -> None:
    kdir = brain / "knowledge" / "area"
    kdir.mkdir(parents=True)
    (kdir / "doc.md").write_text("# Area\nCurrent content.\n", encoding="utf-8")

    async def valid_output(prompt: str, cwd: Path, **kwargs):
        del prompt, cwd, kwargs
        return ClaudeResult(success=True, output=_structured_output("# Summary\nMeaningful summary text."))

    with patch("brain_sync.regen.engine.invoke_claude", side_effect=valid_output):
        asyncio.run(regen_single_folder(brain, "area", session_id="session-regen", owner_id="owner-1"))

    asyncio.run(regen_single_folder(brain, "area", session_id="session-unchanged", owner_id="owner-1"))

    regenerated = _latest_event(brain, OperationalEventType.REGEN_COMPLETED, "session-regen")
    regenerated_details = _details(regenerated)
    assert regenerated.outcome == "regenerated"
    assert regenerated_details["reason"] == "summary_written"
    assert regenerated_details["propagates_up"] is True
    assert regenerated_details["propagation_reason"] == "child_summary_changed"

    unchanged = _latest_event(brain, OperationalEventType.REGEN_COMPLETED, "session-unchanged")
    unchanged_details = _details(unchanged)
    assert unchanged.outcome == "skipped_unchanged"
    assert unchanged_details["reason"] == "content_hash_unchanged"
    assert unchanged_details["propagates_up"] is False
    assert unchanged_details["propagation_reason"] is None


def test_regen_started_and_failed_events_capture_typed_diagnostics(brain: Path) -> None:
    kdir = brain / "knowledge" / "typed"
    kdir.mkdir(parents=True)
    (kdir / "doc.md").write_text("# Typed\nImportant content.\n", encoding="utf-8")

    async def malformed_output(prompt: str, cwd: Path, **kwargs):
        del prompt, cwd, kwargs
        return ClaudeResult(success=True, output="<journal>\nOnly journal\n</journal>")

    with patch("brain_sync.regen.engine.invoke_claude", side_effect=malformed_output):
        with pytest.raises(RegenFailed, match="invalid structured output"):
            asyncio.run(regen_single_folder(brain, "typed", session_id="session-fail", owner_id="owner-1"))

    started = _latest_event(brain, OperationalEventType.REGEN_STARTED, "session-fail")
    started_details = _details(started)
    component_tokens = cast(dict[str, int], started_details["component_tokens"])
    assert started_details["reason"] == "content_changed"
    assert started_details["evaluation_outcome"] == "content_changed"
    assert component_tokens["direct_files"] > 0
    assert "prompt_budget_class" in started_details

    failed = _latest_event(brain, OperationalEventType.REGEN_FAILED, "session-fail")
    failed_details = _details(failed)
    assert failed.outcome == "failed_artifact_contract"
    assert failed_details["reason"] == "invalid_structured_output"
    assert failed_details["phase"] == "artifact_contract"
    assert "error" in failed_details


def test_diagnostic_report_aggregates_prompt_and_chunk_cost(brain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kdir = brain / "knowledge" / "chunky"
    kdir.mkdir(parents=True)
    big_content = "\n\n".join(f"## Section {i}\n{'content ' * 100}" for i in range(20))
    (kdir / "report.md").write_text(big_content, encoding="utf-8")

    async def mixed_output(prompt: str, cwd: Path, **kwargs):
        del prompt, cwd
        if kwargs.get("is_chunk"):
            return ClaudeResult(
                success=True,
                output="Chunk summary with retained facts.",
                input_tokens=90,
                output_tokens=10,
                duration_ms=3,
                num_turns=1,
            )
        return ClaudeResult(
            success=True,
            output=_structured_output("# Summary\nChunked final summary with retained facts."),
            input_tokens=140,
            output_tokens=30,
            duration_ms=5,
            num_turns=1,
        )

    monkeypatch.setattr("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 5_000)
    monkeypatch.setattr("brain_sync.regen.engine.CHUNK_TARGET_CHARS", 1_500)

    with patch("brain_sync.regen.engine.invoke_claude", side_effect=mixed_output):
        asyncio.run(regen_single_folder(brain, "chunky", session_id="session-chunk", owner_id="owner-1"))
        asyncio.run(regen_single_folder(brain, "chunky", session_id="session-chunk-2", owner_id="owner-1"))

    report = build_regen_diagnostic_report(brain, session_id="session-chunk")
    assert report["observability_contract"]["semantic_events_surface"] == "operational_events"
    assert report["prompt_component_coverage_count"] == 1
    assert report["terminal_reason_coverage_count"] >= 1

    chunky = next(path for path in report["path_reports"] if path["knowledge_path"] == "chunky")
    assert chunky["run_reason"] == "content_changed"
    assert chunky["latest_outcome"] == "regenerated"
    assert chunky["chunk_count"] > 0
    assert chunky["chunked_file_count"] == 1
    assert chunky["token_cost"]["chunk_invocations"] > 0
    assert chunky["token_cost"]["final_invocations"] == 1

    churn_report = build_regen_diagnostic_report(brain)
    assert any(item["knowledge_path"] == "chunky" for item in churn_report["high_churn_paths"])


def test_diagnostic_report_clears_stale_chunk_metadata_after_no_call(
    brain: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kdir = brain / "knowledge" / "chunky-stable"
    kdir.mkdir(parents=True)
    big_content = "\n\n".join(f"## Section {i}\n{'content ' * 100}" for i in range(20))
    (kdir / "report.md").write_text(big_content, encoding="utf-8")

    async def mixed_output(prompt: str, cwd: Path, **kwargs):
        del prompt, cwd
        if kwargs.get("is_chunk"):
            return ClaudeResult(
                success=True,
                output="Chunk summary with retained facts.",
                input_tokens=90,
                output_tokens=10,
                duration_ms=3,
                num_turns=1,
            )
        return ClaudeResult(
            success=True,
            output=_structured_output("# Summary\nChunked final summary with retained facts."),
            input_tokens=140,
            output_tokens=30,
            duration_ms=5,
            num_turns=1,
        )

    monkeypatch.setattr("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 5_000)
    monkeypatch.setattr("brain_sync.regen.engine.CHUNK_TARGET_CHARS", 1_500)

    with patch("brain_sync.regen.engine.invoke_claude", side_effect=mixed_output):
        asyncio.run(regen_single_folder(brain, "chunky-stable", session_id="session-chunky-1", owner_id="owner-1"))
        asyncio.run(regen_single_folder(brain, "chunky-stable", session_id="session-chunky-2", owner_id="owner-1"))

    report = build_regen_diagnostic_report(brain)
    chunky = next(path for path in report["path_reports"] if path["knowledge_path"] == "chunky-stable")
    assert chunky["latest_outcome"] == "skipped_unchanged"
    assert chunky["run_reason"] == "content_hash_unchanged"
    assert chunky["chunk_count"] == 0
    assert chunky["chunked_file_count"] == 0
    assert chunky["chunked_files"] == []


def test_terminal_lock_release_tolerates_already_unowned_row(brain: Path) -> None:
    save_regen_lock(brain, RegenLock(knowledge_path="area", regen_status="idle"))
    assert acquire_regen_ownership(brain, "area", "owner-1")
    assert release_regen_ownership(brain, "area", "owner-1", regen_status="idle", error_reason=None)

    _save_terminal_regen_lock(
        brain,
        knowledge_path="area",
        owner_id="owner-1",
        regen_status="idle",
        regen_started_utc="2026-03-23T00:00:00+00:00",
    )

    current = load_regen_lock(brain, "area")
    assert current is not None
    assert current.regen_status == "idle"
    assert current.owner_id is None


def test_terminal_lock_release_tolerates_missing_row(brain: Path) -> None:
    save_regen_lock(brain, RegenLock(knowledge_path="area", regen_status="idle"))
    assert acquire_regen_ownership(brain, "area", "owner-1")
    delete_regen_lock(brain, "area")

    _save_terminal_regen_lock(
        brain,
        knowledge_path="area",
        owner_id="owner-1",
        regen_status="failed",
        regen_started_utc="2026-03-23T00:00:00+00:00",
        error_reason="simulated failure",
    )

    current = load_regen_lock(brain, "area")
    assert current is not None
    assert current.regen_status == "failed"
    assert current.owner_id is None
    assert current.error_reason == "simulated failure"


def test_terminal_lock_release_still_raises_for_conflicting_owner(brain: Path) -> None:
    save_regen_lock(brain, RegenLock(knowledge_path="area", regen_status="idle"))
    assert acquire_regen_ownership(brain, "area", "owner-2")

    with pytest.raises(RuntimeError, match="failed to release regen ownership"):
        _save_terminal_regen_lock(
            brain,
            knowledge_path="area",
            owner_id="owner-1",
            regen_status="idle",
            regen_started_utc="2026-03-23T00:00:00+00:00",
        )

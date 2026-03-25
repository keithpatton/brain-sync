"""Phase 1 tests for explicit regen evaluation and backend capabilities."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from brain_sync.application.insights import InsightState, save_insight_state
from brain_sync.brain.fileops import iterdir_paths
from brain_sync.brain.layout import area_insights_dir, brain_manifest_path
from brain_sync.brain.tree import is_readable_file
from brain_sync.llm import (
    BackendCapabilities,
    InvocationContract,
    StructuredOutputContract,
    resolve_backend_capabilities,
)
from brain_sync.llm.base import LlmResult
from brain_sync.regen.engine import (
    RegenConfig,
    _collect_child_summaries,
    _compute_content_hash,
    _compute_structure_hash,
    _get_child_dirs,
    evaluate_folder_state,
    regen_single_folder,
)
from brain_sync.runtime.repository import _connect

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    manifest_path = brain_manifest_path(root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps({"version": 1}) + "\n", encoding="utf-8")
    _connect(root).close()
    return root


def _save_current_hashes(root: Path, knowledge_path: str) -> None:
    knowledge_dir = root / "knowledge" / knowledge_path if knowledge_path else root / "knowledge"
    child_dirs = _get_child_dirs(knowledge_dir)
    child_summaries = _collect_child_summaries(root, knowledge_path, child_dirs)
    has_direct_files = any(is_readable_file(path) for path in iterdir_paths(knowledge_dir))
    content_hash = _compute_content_hash(child_summaries, knowledge_dir, has_direct_files)
    structure_hash = _compute_structure_hash(child_dirs, knowledge_dir, has_direct_files)
    save_insight_state(
        root,
        InsightState(
            knowledge_path=knowledge_path,
            content_hash=content_hash,
            structure_hash=structure_hash,
            summary_hash="summary-hash",
        ),
    )


class TestEvaluateFolderState:
    def test_missing_path_outcome(self, brain: Path) -> None:
        evaluation = evaluate_folder_state(brain, "missing")
        assert evaluation.outcome == "missing_path"

    def test_no_content_outcome(self, brain: Path) -> None:
        (brain / "knowledge" / "empty").mkdir(parents=True)
        evaluation = evaluate_folder_state(brain, "empty")
        assert evaluation.outcome == "no_content"

    def test_content_changed_outcome_for_new_area(self, brain: Path) -> None:
        area = brain / "knowledge" / "project"
        area.mkdir(parents=True)
        (area / "doc.md").write_text("# Doc\n\nNew content.", encoding="utf-8")
        evaluation = evaluate_folder_state(brain, "project")
        assert evaluation.outcome == "content_changed"

    def test_unchanged_outcome(self, brain: Path) -> None:
        area = brain / "knowledge" / "steady"
        area.mkdir(parents=True)
        (area / "doc.md").write_text("# Doc\n\nStable content.", encoding="utf-8")
        _save_current_hashes(brain, "steady")
        evaluation = evaluate_folder_state(brain, "steady")
        assert evaluation.outcome == "unchanged"

    def test_structure_only_outcome(self, brain: Path) -> None:
        area = brain / "knowledge" / "rename"
        area.mkdir(parents=True)
        (area / "old-name.md").write_text("# Doc\n\nStable content.", encoding="utf-8")
        _save_current_hashes(brain, "rename")
        (area / "old-name.md").rename(area / "new-name.md")
        evaluation = evaluate_folder_state(brain, "rename")
        assert evaluation.outcome == "structure_only"

    def test_structure_only_outcome_when_new_child_has_no_summary_yet(self, brain: Path) -> None:
        area = brain / "knowledge" / "initiative"
        meetings = area / "meetings"
        area.mkdir(parents=True)
        meetings.mkdir()
        (meetings / "index.md").write_text("# Meetings\n\nExisting notes.", encoding="utf-8")

        _save_current_hashes(brain, "initiative/meetings")
        _save_current_hashes(brain, "initiative")

        monthly = meetings / "2026-03"
        monthly.mkdir()
        (monthly / "manual.md").write_text("# Manual Notes\n\nAdded by hand.", encoding="utf-8")

        evaluation = evaluate_folder_state(brain, "initiative/meetings")
        assert evaluation.outcome == "structure_only"
        assert evaluation.change.change_type == "rename"
        assert [child.name for child in evaluation.child_dirs] == ["2026-03"]
        assert evaluation.child_summaries == {}

    def test_metadata_backfill_outcome(self, brain: Path) -> None:
        area = brain / "knowledge" / "legacy"
        area.mkdir(parents=True)
        (area / "doc.md").write_text("# Doc\n\nLegacy content.", encoding="utf-8")
        insights_dir = area_insights_dir(brain, "legacy")
        insights_dir.mkdir(parents=True)
        (insights_dir / "summary.md").write_text("# Existing Summary", encoding="utf-8")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="legacy",
                content_hash="old-hash",
                summary_hash="old-summary",
                structure_hash=None,
            ),
        )
        evaluation = evaluate_folder_state(brain, "legacy")
        assert evaluation.outcome == "metadata_backfill"


class TestBackendCapabilities:
    def test_known_sonnet_46_model_reports_extended_context(self) -> None:
        class NoCapabilitiesBackend:
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
                del prompt, cwd, timeout, model, effort, max_turns, system_prompt, tools, is_chunk
                raise AssertionError("invoke should not be called in this test")

        capabilities = resolve_backend_capabilities(NoCapabilitiesBackend(), model="claude-sonnet-4-6")
        assert capabilities.prompt_budget_class == "extended_1m"
        assert capabilities.max_prompt_tokens == 1_000_000
        assert capabilities.max_concurrency == 1
        assert capabilities.structured_output.reliability == "strict"
        assert capabilities.invocation.startup_overhead_class == "medium"

    def test_unknown_model_stays_on_conservative_default(self) -> None:
        class NoCapabilitiesBackend:
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
                del prompt, cwd, timeout, model, effort, max_turns, system_prompt, tools, is_chunk
                raise AssertionError("invoke should not be called in this test")

        capabilities = resolve_backend_capabilities(NoCapabilitiesBackend(), model="unknown-model")
        assert capabilities.prompt_budget_class == "standard_200k"
        assert capabilities.max_prompt_tokens == 200_000
        assert capabilities.max_concurrency == 1

    def test_regen_execution_uses_backend_invocation_contract(self, brain: Path) -> None:
        area = brain / "knowledge" / "contract"
        area.mkdir(parents=True)
        (area / "doc.md").write_text("# Doc\n\nContract test content.", encoding="utf-8")

        class CapabilityBackend:
            def __init__(self) -> None:
                self.calls: list[dict[str, object]] = []

            def get_capabilities(self, *, model: str = "") -> BackendCapabilities:
                del model
                return BackendCapabilities(
                    prompt_budget_class="test",
                    max_prompt_tokens=321_000,
                    max_concurrency=2,
                    structured_output=StructuredOutputContract(
                        format="summary_journal_xml",
                        summary_required=True,
                        journal_optional=True,
                        reliability="strict",
                    ),
                    invocation=InvocationContract(
                        mode="single_prompt_inference",
                        system_prompt="Capability system prompt",
                        tools="",
                        prompt_overhead_tokens=7,
                        startup_overhead_class="low",
                    ),
                )

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
                self.calls.append(
                    {
                        "prompt": prompt,
                        "cwd": cwd,
                        "timeout": timeout,
                        "model": model,
                        "effort": effort,
                        "max_turns": max_turns,
                        "system_prompt": system_prompt,
                        "tools": tools,
                        "is_chunk": is_chunk,
                    }
                )
                return LlmResult(
                    success=True,
                    output="<summary># Summary\n\nCapability contract proof.</summary><journal></journal>",
                    input_tokens=11,
                    output_tokens=13,
                    num_turns=1,
                )

        backend = CapabilityBackend()
        result = asyncio.run(
            regen_single_folder(
                brain,
                "contract",
                config=RegenConfig(model="claude-sonnet-4-6", effort="low", timeout=30),
                backend=backend,
            )
        )

        assert result.action == "regenerated"
        assert len(backend.calls) == 1
        assert backend.calls[0]["system_prompt"] == "Capability system prompt"
        assert backend.calls[0]["tools"] == ""

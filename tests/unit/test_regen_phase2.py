"""Phase 2 tests for prompt budgeting and capability-driven packing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_sync.brain.layout import area_insights_dir, brain_manifest_path
from brain_sync.llm import capabilities_for_model
from brain_sync.regen.engine import CHUNK_TARGET_CHARS, _build_prompt
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


class TestPromptBudgeting:
    def test_extended_context_can_inline_large_file_without_chunking(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "annual"
        kdir.mkdir(parents=True)
        large_content = "# Annual\n\n" + ("Long-form content block. " * 20_000)
        assert len(large_content) > CHUNK_TARGET_CHARS
        (kdir / "report.md").write_text(large_content, encoding="utf-8")
        idir = area_insights_dir(brain, "annual")
        idir.mkdir(parents=True)

        capabilities = capabilities_for_model("claude-sonnet-4-6")
        result = _build_prompt("annual", kdir, {}, idir, brain, capabilities=capabilities)

        assert result.oversized_files is None
        assert result.diagnostics is not None
        assert result.diagnostics.effective_prompt_tokens == 320_000
        assert result.diagnostics.component_tokens["direct_files"] > 0

    def test_legacy_override_still_forces_deferral_in_direct_prompt_tests(self, brain: Path, monkeypatch) -> None:
        kdir = brain / "knowledge" / "legacy-budget"
        kdir.mkdir(parents=True)
        (kdir / "big.md").write_text("# Big\n" + ("x" * 50_000), encoding="utf-8")
        idir = area_insights_dir(brain, "legacy-budget")
        idir.mkdir(parents=True)

        monkeypatch.setattr("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 5_000)
        result = _build_prompt(
            "legacy-budget",
            kdir,
            {},
            idir,
            brain,
            capabilities=capabilities_for_model("claude-sonnet-4-6"),
        )

        assert result.oversized_files is not None
        assert result.diagnostics is not None
        assert result.diagnostics.prompt_budget_class == "legacy_override"

    def test_child_summary_omission_is_reported_in_diagnostics(self, brain: Path, monkeypatch) -> None:
        kdir = brain / "knowledge" / "parent"
        kdir.mkdir(parents=True)
        (kdir / "overview.md").write_text("# Overview\nshort", encoding="utf-8")
        idir = area_insights_dir(brain, "parent")
        idir.mkdir(parents=True)
        child_summaries = {f"child-{index:02d}": "# Summary\n\n" + ("detail " * 1500) for index in range(1, 8)}
        monkeypatch.setattr("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 12_000)

        result = _build_prompt(
            "parent",
            kdir,
            child_summaries,
            idir,
            brain,
            capabilities=capabilities_for_model("unknown-model"),
        )

        assert result.diagnostics is not None
        assert len(result.diagnostics.omitted_child_summaries) > 0
        assert result.diagnostics.prompt_budget_class == "legacy_override"

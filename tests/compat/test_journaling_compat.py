from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

import pytest

from brain_sync.application.doctor import doctor
from brain_sync.application.init import init_brain
from brain_sync.brain.layout import area_insights_dir, area_journal_dir
from brain_sync.llm.base import LlmResult
from brain_sync.regen.engine import RegenConfig, regen_single_folder

pytestmark = pytest.mark.integration


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    return root


class _StructuredJournalBackend:
    async def invoke(self, prompt: str, cwd: Path, **kwargs) -> LlmResult:
        assert "<journal>" in prompt
        return LlmResult(
            success=True,
            output=(
                "<summary>\n# Project Summary\nCompatibility-safe summary.\n</summary>\n\n"
                "<journal>\nFresh journal entry.\n</journal>"
            ),
            input_tokens=0,
            output_tokens=0,
            num_turns=1,
        )


def test_supported_brain_format_v1_legacy_journal_tree_heals_in_place(brain: Path) -> None:
    project = brain / "knowledge" / "project"
    project.mkdir(parents=True)
    (project / "doc.md").write_text("# Project\n\nMeaningful update.", encoding="utf-8")

    now = datetime.now()
    month = now.strftime("%Y-%m")
    day = now.strftime("%Y-%m-%d")
    legacy = area_insights_dir(brain, "project") / "journal" / month / f"{day}.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("## 08:15\n\nLegacy history.", encoding="utf-8")

    asyncio.run(regen_single_folder(brain, "project", config=RegenConfig(), backend=_StructuredJournalBackend()))

    healed = area_journal_dir(brain, "project") / month / f"{day}.md"
    assert healed.exists()
    content = healed.read_text(encoding="utf-8")
    assert "Legacy history." in content
    assert "Fresh journal entry." in content
    assert not legacy.exists()

    result = doctor(brain)
    assert not any(f.check == "legacy_journal_layout" for f in result.findings)

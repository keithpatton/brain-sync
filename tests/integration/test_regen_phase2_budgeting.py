"""Phase 2 integration tests for capability-driven prompt budgeting."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.llm.fake import FakeBackend
from brain_sync.regen.engine import RegenConfig, regen_single_folder

pytestmark = pytest.mark.integration


class TestCapabilityDrivenBudgeting:
    async def test_sonnet_46_large_leaf_avoids_chunk_fallback(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "research" / "annual"
        kdir.mkdir(parents=True)
        (kdir / "report.md").write_text("# Annual Report\n\n" + ("Insightful section. " * 20_000), encoding="utf-8")

        backend = FakeBackend(mode="stable")
        result = await regen_single_folder(
            brain,
            "research/annual",
            config=RegenConfig(model="claude-sonnet-4-6", effort="low", timeout=30),
            backend=backend,
        )

        assert result.action == "regenerated"
        assert backend.call_count == 1

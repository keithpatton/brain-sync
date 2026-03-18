"""Regression: content hash unchanged must not trigger redundant regen.

Bug pattern: multiple leaf changes collapsing to ancestor but content
hash already matches → wasted Claude calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.llm.fake import FakeBackend
from brain_sync.regen.engine import RegenConfig, regen_single_folder

pytestmark = [pytest.mark.e2e, pytest.mark.regression]


class TestContentHashNoRedundantRegen:
    """Content hash unchanged → no regen."""

    async def test_no_redundant_regen(self, tmp_path: Path):
        """After initial regen, unchanged content hash should skip."""
        from brain_sync.application.init import init_brain

        root = tmp_path / "brain"
        root.mkdir()
        init_brain(root)

        kdir = root / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nStable content.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        # Initial regen
        r1 = await regen_single_folder(root, "area", config=config, backend=backend)
        assert r1.action == "regenerated"
        assert backend.call_count == 1

        # Second regen — should skip, no Claude call
        r2 = await regen_single_folder(root, "area", config=config, backend=backend)
        assert r2.action == "skipped_unchanged"
        assert backend.call_count == 1  # no additional call

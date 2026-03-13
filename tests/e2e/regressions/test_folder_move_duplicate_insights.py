"""Regression: folder move must not create duplicate insight trees.

Bug pattern: move creates new insight path without cleaning up old one,
resulting in orphaned insight directories.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from brain_sync.llm.fake import FakeBackend
from brain_sync.regen import RegenConfig, regen_single_folder
from tests.e2e.harness.assertions import assert_no_duplicate_insights, assert_no_orphan_insights

pytestmark = [pytest.mark.e2e, pytest.mark.regression]


class TestFolderMoveNoDuplicateInsights:
    """Move doesn't create orphan insight trees."""

    async def test_no_orphan_after_move_and_regen(self, tmp_path: Path):
        """After move + regen, no orphan insight dirs should remain."""
        from brain_sync.commands.init import init_brain

        root = tmp_path / "brain"
        root.mkdir()
        init_brain(root)

        # Create and regen original
        kdir = root / "knowledge" / "original"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        await regen_single_folder(root, "original", config=config, backend=backend)
        assert (root / "insights" / "original" / "summary.md").exists()

        # Move knowledge folder
        shutil.move(str(root / "knowledge" / "original"), str(root / "knowledge" / "renamed"))
        # Also move insights (simulate watcher mirror)
        shutil.move(str(root / "insights" / "original"), str(root / "insights" / "renamed"))

        # Regen at new location
        await regen_single_folder(root, "renamed", config=config, backend=backend)

        # Invariants
        assert_no_orphan_insights(root)
        assert_no_duplicate_insights(root)

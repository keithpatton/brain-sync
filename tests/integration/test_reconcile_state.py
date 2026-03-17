"""Phase 1 integration tests: reconcile state transitions with FakeBackend."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.insights import load_insight_state
from brain_sync.brain.layout import area_insights_dir
from brain_sync.llm.fake import FakeBackend
from brain_sync.regen import RegenConfig, regen_single_folder

pytestmark = pytest.mark.integration


class TestReconcileState:
    """State transitions during regen with fake backend."""

    async def test_content_hash_unchanged_skips(self, brain: Path):
        """Content hash unchanged on second regen → skipped_unchanged."""
        kdir = brain / "knowledge" / "stable"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nUnchanging content.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        r1 = await regen_single_folder(brain, "stable", config=config, backend=backend)
        assert r1.action == "regenerated"

        r2 = await regen_single_folder(brain, "stable", config=config, backend=backend)
        assert r2.action == "skipped_unchanged"

        # InsightState should have content_hash set
        istate = load_insight_state(brain, "stable")
        assert istate is not None
        assert istate.content_hash is not None
        assert istate.regen_status == "idle"

    async def test_content_change_triggers_regen(self, brain: Path):
        """Modifying a file changes content hash → regenerated."""
        kdir = brain / "knowledge" / "changing"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Version 1\n\nOriginal.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        r1 = await regen_single_folder(brain, "changing", config=config, backend=backend)
        assert r1.action == "regenerated"
        hash1 = load_insight_state(brain, "changing").content_hash  # type: ignore[union-attr]

        # Modify the file
        (kdir / "doc.md").write_text("# Version 2\n\nModified content.", encoding="utf-8")

        r2 = await regen_single_folder(brain, "changing", config=config, backend=backend)
        assert r2.action == "regenerated"
        hash2 = load_insight_state(brain, "changing").content_hash  # type: ignore[union-attr]
        assert hash1 != hash2

    async def test_empty_folder_skipped(self, brain: Path):
        """An empty knowledge folder with no files is skipped."""
        kdir = brain / "knowledge" / "empty"
        kdir.mkdir(parents=True)

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        r = await regen_single_folder(brain, "empty", config=config, backend=backend)
        assert r.action == "skipped_no_content"

    async def test_missing_folder_cleaned_up(self, brain: Path):
        """If knowledge dir doesn't exist, stale co-located state is cleaned up."""
        save_dir = area_insights_dir(brain, "gone")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)

        r = await regen_single_folder(brain, "gone", config=config, backend=backend)
        assert r.action == "cleaned_up"
        assert not save_dir.exists()

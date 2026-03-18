"""Integration tests: reconcile preserves non-regenerable artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.reconcile import reconcile_knowledge_tree
from brain_sync.brain.layout import area_insights_dir
from brain_sync.llm.fake import FakeBackend
from brain_sync.regen.engine import RegenConfig, regen_single_folder

pytestmark = pytest.mark.integration


class TestReconcilePreservesJournals:
    async def test_reconcile_preserves_journals_on_orphan_cleanup(self, brain: Path):
        """Orphan insights with journals: regenerable artifacts cleaned, journals survive."""
        # Set up knowledge + insights via regen so DB state exists
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Project\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)
        await regen_single_folder(brain, "project", config=config, backend=backend)

        # Simulate journal entries at multiple levels
        idir = area_insights_dir(brain, "project")
        journal = idir / "journal" / "2026-03"
        journal.mkdir(parents=True)
        (journal / "2026-03-11.md").write_text("Journal entry 1", encoding="utf-8")
        (journal / "2026-03-12.md").write_text("Journal entry 2", encoding="utf-8")

        # Delete the readable content but leave the area dir + managed state in place.
        # This matches the co-located v1 layout where orphan cleanup preserves journal files.
        (kdir / "doc.md").unlink()

        # Reconcile should clean regenerable artifacts but preserve journals
        result = reconcile_knowledge_tree(brain)
        assert "project" in result.orphans_cleaned

        # Journals survive
        assert (journal / "2026-03-11.md").read_text(encoding="utf-8") == "Journal entry 1"
        assert (journal / "2026-03-12.md").read_text(encoding="utf-8") == "Journal entry 2"
        # summary.md should be gone
        assert not (idir / "summary.md").exists()


class TestRegenCleanupPreservesJournals:
    async def test_regen_cleanup_preserves_journals(self, brain: Path):
        """Regen on a no-content area preserves journals while cleaning regenerable artifacts."""
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Area\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = RegenConfig(model="fake-model", effort="low", timeout=30)
        await regen_single_folder(brain, "area", config=config, backend=backend)

        # Add journal entries
        idir = area_insights_dir(brain, "area")
        journal = idir / "journal" / "2026-03"
        journal.mkdir(parents=True)
        (journal / "2026-03-15.md").write_text("Important entry", encoding="utf-8")

        # Delete the readable content but leave the area dir + managed state in place.
        (kdir / "doc.md").unlink()

        # Regen should clean up but preserve journals
        r = await regen_single_folder(brain, "area", config=config, backend=backend)
        assert r.action == "skipped_no_content"
        assert (journal / "2026-03-15.md").read_text(encoding="utf-8") == "Important entry"
        assert not (idir / "summary.md").exists()

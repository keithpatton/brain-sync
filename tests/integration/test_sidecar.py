"""Integration tests for Phase 4 sidecar writes — regen + doctor with real FS + SQLite."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.llm.fake import FakeBackend
from brain_sync.regen import RegenConfig, regen_single_folder
from brain_sync.sidecar import SIDECAR_FILENAME, RegenMeta, read_regen_meta, write_regen_meta
from brain_sync.state import load_insight_state

pytestmark = pytest.mark.integration


def _config() -> RegenConfig:
    return RegenConfig(model="fake-model", effort="low", timeout=30)


class TestSidecarAfterRegen:
    """After regen_single_folder, sidecar exists alongside summary.md."""

    async def test_regenerated_writes_sidecar(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "overview.md").write_text("# Overview\n\nContent here.", encoding="utf-8")

        result = await regen_single_folder(brain, "project", config=_config(), backend=FakeBackend(mode="stable"))
        assert result.action == "regenerated"

        meta = read_regen_meta(brain / "insights" / "project")
        assert meta is not None
        assert meta.content_hash is not None
        assert meta.summary_hash is not None
        assert meta.structure_hash is not None
        assert meta.last_regen_utc is not None

    async def test_sidecar_matches_db(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nStuff.", encoding="utf-8")

        await regen_single_folder(brain, "project", config=_config(), backend=FakeBackend(mode="stable"))

        meta = read_regen_meta(brain / "insights" / "project")
        istate = load_insight_state(brain, "project")
        assert meta is not None
        assert istate is not None
        assert meta.content_hash == istate.content_hash
        assert meta.summary_hash == istate.summary_hash
        assert meta.structure_hash == istate.structure_hash

    async def test_skipped_unchanged_no_sidecar_change(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nStuff.", encoding="utf-8")
        backend = FakeBackend(mode="stable")
        config = _config()

        await regen_single_folder(brain, "project", config=config, backend=backend)
        sidecar_path = brain / "insights" / "project" / SIDECAR_FILENAME
        mtime_before = sidecar_path.stat().st_mtime

        # Second run — unchanged
        result = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result.action == "skipped_unchanged"
        # Sidecar should not be rewritten
        assert sidecar_path.stat().st_mtime == mtime_before

    async def test_skipped_rename_updates_structure_hash(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        backend = FakeBackend(mode="stable")
        config = _config()

        await regen_single_folder(brain, "project", config=config, backend=backend)
        meta1 = read_regen_meta(brain / "insights" / "project")
        assert meta1 is not None

        # Add a new child dir (causes structure change without content change)
        child = kdir / "sub"
        child.mkdir()
        (child / "readme.md").write_text("# Sub\n\nChild.", encoding="utf-8")

        await regen_single_folder(brain, "project", config=config, backend=backend)
        # This is a content change since child summaries are part of content
        # But let's check sidecar was updated regardless
        meta2 = read_regen_meta(brain / "insights" / "project")
        assert meta2 is not None
        assert meta2.structure_hash != meta1.structure_hash

    async def test_cleaned_up_deletes_sidecar(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        backend = FakeBackend(mode="stable")
        config = _config()

        await regen_single_folder(brain, "project", config=config, backend=backend)
        assert read_regen_meta(brain / "insights" / "project") is not None

        # Delete knowledge dir
        import shutil

        shutil.rmtree(kdir)

        result = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result.action == "cleaned_up"
        assert not (brain / "insights" / "project" / SIDECAR_FILENAME).exists()

    async def test_sidecar_write_failure_does_not_block_regen(self, brain: Path) -> None:
        from unittest.mock import patch

        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        backend = FakeBackend(mode="stable")
        config = _config()

        # Patch write_regen_meta everywhere — both regen.py and state.py call it
        with (
            patch("brain_sync.regen.write_regen_meta", side_effect=OSError("disk full")),
            patch("brain_sync.sidecar.atomic_write_bytes", side_effect=OSError("disk full")),
        ):
            result = await regen_single_folder(brain, "project", config=config, backend=backend)

        assert result.action == "regenerated"
        # Summary should still exist despite sidecar failure
        assert (brain / "insights" / "project" / "summary.md").exists()
        # regen_locks should still be updated (lifecycle persists even when sidecar fails)
        from brain_sync.state import _connect

        conn = _connect(brain)
        try:
            row = conn.execute(
                "SELECT knowledge_path FROM regen_locks WHERE knowledge_path = ?", ("project",)
            ).fetchone()
            assert row is not None
        finally:
            conn.close()
        # Sidecar should NOT exist (write was blocked)
        assert not (brain / "insights" / "project" / SIDECAR_FILENAME).exists()

    async def test_backfill_writes_sidecar(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        backend = FakeBackend(mode="stable")
        config = _config()

        # First regen to create summary
        await regen_single_folder(brain, "project", config=config, backend=backend)

        # Simulate pre-v18 state: write sidecar with structure_hash=None
        # (In v21, sidecars are authoritative — no need to touch DB)
        istate = load_insight_state(brain, "project")
        assert istate is not None
        write_regen_meta(
            brain / "insights" / "project",
            RegenMeta(
                content_hash=istate.content_hash,
                summary_hash=istate.summary_hash,
                structure_hash=None,
                last_regen_utc=istate.last_regen_utc,
            ),
        )

        result = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result.action == "skipped_backfill"

        meta = read_regen_meta(brain / "insights" / "project")
        assert meta is not None
        assert meta.structure_hash is not None
        assert meta.content_hash is not None


class TestSidecarPartialMerge:
    """Partial sidecar writes prefer DB values over existing sidecar."""

    async def test_skipped_rename_sidecar_uses_db_values(self, brain: Path) -> None:
        """Force a skipped_rename path and verify sidecar gets DB values for unchanged fields."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        # Also need a child dir — structure hash includes child dir names
        child = kdir / "sub"
        child.mkdir()
        (child / "notes.md").write_text("# Notes\n\nSome notes.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        # Regen "sub" first so parent can collect child summaries
        await regen_single_folder(brain, "project/sub", config=config, backend=backend)
        # Regen parent
        await regen_single_folder(brain, "project", config=config, backend=backend)

        istate_before = load_insight_state(brain, "project")
        assert istate_before is not None
        assert istate_before.content_hash is not None
        assert istate_before.summary_hash is not None

        # Now rename the child dir — changes structure_hash but not content_hash
        child_new = kdir / "sub-renamed"
        child.rename(child_new)
        # Also move insights to match
        i_sub = brain / "insights" / "project" / "sub"
        i_sub_new = brain / "insights" / "project" / "sub-renamed"
        if i_sub.exists():
            i_sub.rename(i_sub_new)

        result = await regen_single_folder(brain, "project", config=config, backend=backend)
        # This should be skipped_rename (structure changed, content unchanged)
        assert result.action == "skipped_rename"

        meta = read_regen_meta(brain / "insights" / "project")
        assert meta is not None
        # content_hash and summary_hash come from DB (unchanged)
        assert meta.content_hash == istate_before.content_hash
        assert meta.summary_hash == istate_before.summary_hash
        # structure_hash should be updated (different from before)
        assert meta.structure_hash is not None
        assert meta.structure_hash != istate_before.structure_hash

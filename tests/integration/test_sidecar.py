"""Integration tests for Phase 4 sidecar writes — regen + doctor with real FS + SQLite."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.insights import load_insight_state
from brain_sync.brain.layout import area_insights_dir, area_summary_path
from brain_sync.brain.sidecar import SIDECAR_FILENAME, RegenMeta, read_regen_meta, write_regen_meta
from brain_sync.llm.fake import FakeBackend
from brain_sync.regen.engine import RegenConfig, RegenFailed, regen_single_folder

pytestmark = pytest.mark.integration


def _config() -> RegenConfig:
    return RegenConfig(model="fake-model", effort="low", timeout=30)


def _insights_dir(root: Path, knowledge_path: str) -> Path:
    return area_insights_dir(root, knowledge_path)


class TestSidecarAfterRegen:
    """After regen_single_folder, sidecar exists alongside summary.md."""

    async def test_regenerated_writes_sidecar(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "overview.md").write_text("# Overview\n\nContent here.", encoding="utf-8")

        result = await regen_single_folder(brain, "project", config=_config(), backend=FakeBackend(mode="stable"))
        assert result.action == "regenerated"

        meta = read_regen_meta(_insights_dir(brain, "project"))
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

        meta = read_regen_meta(_insights_dir(brain, "project"))
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
        sidecar_path = _insights_dir(brain, "project") / SIDECAR_FILENAME
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
        meta1 = read_regen_meta(_insights_dir(brain, "project"))
        assert meta1 is not None

        # Add a new child dir (causes structure change without content change)
        child = kdir / "sub"
        child.mkdir()
        (child / "readme.md").write_text("# Sub\n\nChild.", encoding="utf-8")

        await regen_single_folder(brain, "project", config=config, backend=backend)
        # This is a content change since child summaries are part of content
        # But let's check sidecar was updated regardless
        meta2 = read_regen_meta(_insights_dir(brain, "project"))
        assert meta2 is not None
        assert meta2.structure_hash != meta1.structure_hash

    async def test_cleaned_up_deletes_sidecar(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        backend = FakeBackend(mode="stable")
        config = _config()

        await regen_single_folder(brain, "project", config=config, backend=backend)
        assert read_regen_meta(_insights_dir(brain, "project")) is not None

        # Delete knowledge dir
        import shutil

        shutil.rmtree(kdir)

        result = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result.action == "cleaned_up"
        assert not (_insights_dir(brain, "project") / SIDECAR_FILENAME).exists()

    async def test_sidecar_write_failure_fails_regen_and_rolls_back_summary(self, brain: Path) -> None:
        from unittest.mock import patch

        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        backend = FakeBackend(mode="stable")
        config = _config()

        # Patch the durable sidecar write path directly.
        with patch("brain_sync.brain.sidecar.write_regen_meta", side_effect=OSError("disk full")):
            with pytest.raises(RegenFailed, match="disk full"):
                await regen_single_folder(brain, "project", config=config, backend=backend)

        assert not area_summary_path(brain, "project").exists()
        from brain_sync.runtime.repository import _connect

        conn = _connect(brain)
        try:
            row = conn.execute("SELECT regen_status FROM regen_locks WHERE knowledge_path = ?", ("project",)).fetchone()
            assert row is not None
            assert row[0] == "failed"
        finally:
            conn.close()
        assert not (_insights_dir(brain, "project") / SIDECAR_FILENAME).exists()

    async def test_regen_with_owner_id_claims_and_releases_runtime_slot(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        result = await regen_single_folder(
            brain,
            "project",
            config=_config(),
            backend=FakeBackend(mode="stable"),
            owner_id="session-owner",
        )

        assert result.action == "regenerated"
        state = load_insight_state(brain, "project")
        assert state is not None
        assert state.regen_status == "idle"
        assert state.owner_id is None

    async def test_skipped_unchanged_with_owner_id_releases_runtime_slot(self, brain: Path) -> None:
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        backend = FakeBackend(mode="stable")
        config = _config()

        first = await regen_single_folder(
            brain,
            "project",
            config=config,
            backend=backend,
            owner_id="session-owner",
        )
        assert first.action == "regenerated"

        second = await regen_single_folder(
            brain,
            "project",
            config=config,
            backend=backend,
            owner_id="session-owner",
        )
        assert second.action == "skipped_unchanged"

        state = load_insight_state(brain, "project")
        assert state is not None
        assert state.regen_status == "idle"
        assert state.owner_id is None

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
            _insights_dir(brain, "project"),
            RegenMeta(
                content_hash=istate.content_hash,
                summary_hash=istate.summary_hash,
                structure_hash=None,
                last_regen_utc=istate.last_regen_utc,
            ),
        )

        result = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result.action == "skipped_backfill"

        meta = read_regen_meta(_insights_dir(brain, "project"))
        assert meta is not None
        assert meta.structure_hash is not None
        assert meta.content_hash is not None

    async def test_backfill_requires_ownership_before_portable_mutation(self, brain: Path) -> None:
        from brain_sync.runtime.repository import acquire_regen_ownership

        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        summary_path = area_summary_path(brain, "project")
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text("Existing summary", encoding="utf-8")
        write_regen_meta(
            _insights_dir(brain, "project"),
            RegenMeta(
                content_hash="old-hash",
                summary_hash="summary-hash",
                structure_hash=None,
                last_regen_utc="2026-01-01T00:00:00Z",
            ),
        )
        assert acquire_regen_ownership(brain, "project", "other-owner")

        before = read_regen_meta(_insights_dir(brain, "project"))
        with pytest.raises(RegenFailed, match="already owned"):
            await regen_single_folder(
                brain,
                "project",
                config=_config(),
                backend=FakeBackend(mode="stable"),
                owner_id="session-owner",
            )

        after = read_regen_meta(_insights_dir(brain, "project"))
        state = load_insight_state(brain, "project")
        assert before == after
        assert state is not None
        assert state.owner_id == "other-owner"
        assert state.regen_status == "running"


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
        result = await regen_single_folder(brain, "project", config=config, backend=backend)
        # This should be skipped_rename (structure changed, content unchanged)
        assert result.action == "skipped_rename"

        meta = read_regen_meta(_insights_dir(brain, "project"))
        assert meta is not None
        # content_hash and summary_hash come from DB (unchanged)
        assert meta.content_hash == istate_before.content_hash
        assert meta.summary_hash == istate_before.summary_hash
        # structure_hash should be updated (different from before)
        assert meta.structure_hash is not None
        assert meta.structure_hash != istate_before.structure_hash

    async def test_skipped_rename_requires_ownership_before_portable_mutation(self, brain: Path) -> None:
        from brain_sync.runtime.repository import acquire_regen_ownership

        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        child = kdir / "sub"
        child.mkdir()
        (child / "notes.md").write_text("# Notes\n\nSome notes.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        await regen_single_folder(brain, "project/sub", config=config, backend=backend)
        await regen_single_folder(brain, "project", config=config, backend=backend)

        before = read_regen_meta(_insights_dir(brain, "project"))
        assert before is not None

        child.rename(kdir / "sub-renamed")
        assert acquire_regen_ownership(brain, "project", "other-owner")

        with pytest.raises(RegenFailed, match="already owned"):
            await regen_single_folder(
                brain,
                "project",
                config=config,
                backend=backend,
                owner_id="session-owner",
            )

        after = read_regen_meta(_insights_dir(brain, "project"))
        state = load_insight_state(brain, "project")
        assert after == before
        assert state is not None
        assert state.owner_id == "other-owner"
        assert state.regen_status == "running"

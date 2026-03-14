"""Integration tests for Phase 5a sidecar read path — synchronization + authoritative reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.llm.fake import FakeBackend
from brain_sync.regen import RegenConfig, classify_folder_change, regen_single_folder
from brain_sync.sidecar import (
    RegenMeta,
    read_regen_meta,
    synchronize_sidecars_from_db,
    write_regen_meta,
)
from brain_sync.state import InsightState, delete_insight_state, save_insight_state

pytestmark = pytest.mark.integration


def _config() -> RegenConfig:
    return RegenConfig(model="fake-model", effort="low", timeout=30)


class TestSynchronizeSidecars:
    """Tests for synchronize_sidecars_from_db — one-time authority transfer."""

    def test_writes_missing_sidecars(self, brain: Path) -> None:
        """DB rows with hashes but no sidecars -> sidecars created."""
        # Create insights dir and DB row
        insights_dir = brain / "insights" / "project"
        insights_dir.mkdir(parents=True)
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="project",
                content_hash="ch1",
                summary_hash="sh1",
                structure_hash="st1",
                last_regen_utc="2026-01-01T00:00:00",
            ),
        )

        count = synchronize_sidecars_from_db(brain)
        assert count == 1

        meta = read_regen_meta(insights_dir)
        assert meta is not None
        assert meta.content_hash == "ch1"
        assert meta.summary_hash == "sh1"
        assert meta.structure_hash == "st1"

    def test_repairs_stale_sidecars(self, brain: Path) -> None:
        """DB has hash X, sidecar has hash Y -> sidecar overwritten with X."""
        insights_dir = brain / "insights" / "project"
        insights_dir.mkdir(parents=True)

        # Write stale sidecar
        write_regen_meta(insights_dir, RegenMeta(content_hash="stale", summary_hash="old_sum"))

        # DB has different values
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="project",
                content_hash="fresh",
                summary_hash="new_sum",
                structure_hash="new_struct",
            ),
        )

        count = synchronize_sidecars_from_db(brain)
        assert count == 1

        meta = read_regen_meta(insights_dir)
        assert meta is not None
        assert meta.content_hash == "fresh"
        assert meta.summary_hash == "new_sum"

    def test_noop_when_matching(self, brain: Path) -> None:
        """DB and sidecar agree -> no writes (mtime unchanged)."""
        insights_dir = brain / "insights" / "project"
        insights_dir.mkdir(parents=True)

        save_insight_state(
            brain,
            InsightState(
                knowledge_path="project",
                content_hash="ch1",
                summary_hash="sh1",
                structure_hash="st1",
            ),
        )
        write_regen_meta(insights_dir, RegenMeta(content_hash="ch1", summary_hash="sh1", structure_hash="st1"))

        import time

        time.sleep(0.05)  # ensure mtime would differ if rewritten
        mtime_before = (insights_dir / ".regen-meta.json").stat().st_mtime

        count = synchronize_sidecars_from_db(brain)
        assert count == 0
        assert (insights_dir / ".regen-meta.json").stat().st_mtime == mtime_before

    def test_skips_no_insights_dir(self, brain: Path) -> None:
        """DB row exists but no insights dir -> no sidecar created."""
        save_insight_state(
            brain,
            InsightState(knowledge_path="missing", content_hash="ch1", summary_hash="sh1"),
        )
        count = synchronize_sidecars_from_db(brain)
        assert count == 0

    def test_skips_no_content_hash(self, brain: Path) -> None:
        """DB row with null content_hash -> skipped."""
        insights_dir = brain / "insights" / "empty"
        insights_dir.mkdir(parents=True)
        save_insight_state(brain, InsightState(knowledge_path="empty"))
        count = synchronize_sidecars_from_db(brain)
        assert count == 0


class TestClassifyReadsFromSidecar:
    """After sync, classify_folder_change reads from sidecar."""

    def test_classify_reads_from_sidecar(self, brain: Path) -> None:
        """After sync, delete DB row, verify classify still uses sidecar hashes."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        # Regen to establish both DB and sidecar
        import asyncio

        asyncio.get_event_loop().run_until_complete(
            regen_single_folder(brain, "project", config=config, backend=backend)
        )

        # Delete DB row — sidecar should still provide hashes
        delete_insight_state(brain, "project")

        event, _, _ = classify_folder_change(brain, "project")
        # Content hasn't changed, so should be "none"
        assert event.change_type == "none"

    def test_classify_falls_back_to_db(self, brain: Path) -> None:
        """No sidecar, DB has hashes -> classification works via DB fallback."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        import asyncio

        asyncio.get_event_loop().run_until_complete(
            regen_single_folder(brain, "project", config=config, backend=backend)
        )

        # Delete sidecar — DB should still provide hashes
        sidecar_path = brain / "insights" / "project" / ".regen-meta.json"
        sidecar_path.unlink()

        event, _, _ = classify_folder_change(brain, "project")
        assert event.change_type == "none"


class TestRegenSkipsUnchangedFromSidecar:
    """Regen reads hashes from sidecar, skips when unchanged."""

    async def test_regen_skips_unchanged_from_sidecar(self, brain: Path) -> None:
        """Delete DB, keep sidecars, run regen_single_folder -> skipped_unchanged."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        # First regen establishes sidecar + DB
        result1 = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result1.action == "regenerated"

        # Delete DB row
        delete_insight_state(brain, "project")

        # Second regen — sidecar provides hashes, should skip
        result2 = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result2.action == "skipped_unchanged"

    async def test_delete_db_sidecars_survive_no_regen(self, brain: Path) -> None:
        """Full cycle: regen, delete DB, regen again — no unnecessary work."""
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "notes.md").write_text("# Notes\n\nSome notes.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        await regen_single_folder(brain, "area", config=config, backend=backend)
        sidecar_before = read_regen_meta(brain / "insights" / "area")
        assert sidecar_before is not None

        # Nuke entire DB
        db_path = brain / ".sync-state.sqlite"
        if db_path.exists():
            db_path.unlink()

        result = await regen_single_folder(brain, "area", config=config, backend=backend)
        assert result.action == "skipped_unchanged"


class TestStaleSidecarRepair:
    """Stale Phase 4 sidecar does not cause unnecessary regen after synchronize."""

    async def test_stale_sidecar_does_not_cause_regen(self, brain: Path) -> None:
        """Phase 4 sidecar stale vs DB -> synchronize -> no unnecessary regen."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        # Regen to establish DB + sidecar
        result1 = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result1.action == "regenerated"

        # Write stale sidecar (simulate Phase 4 stale export)
        write_regen_meta(
            brain / "insights" / "project",
            RegenMeta(content_hash="stale_hash", summary_hash="stale_sum"),
        )

        # Synchronize — DB overwrites stale sidecar
        count = synchronize_sidecars_from_db(brain)
        assert count == 1

        # Regen should skip (sidecar now matches actual state)
        result2 = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result2.action == "skipped_unchanged"


class TestDoctorWithStaleSidecar:
    """Doctor must not be misled by stale Phase 4 sidecars."""

    async def test_doctor_repairs_stale_sidecar_before_checks(self, brain: Path) -> None:
        """Doctor runs synchronize_sidecars_from_db before regen-change detection.

        Without synchronization, a stale sidecar would cause doctor to
        incorrectly report a content change (would-trigger-regen).
        """
        from brain_sync.commands.doctor import doctor as run_doctor

        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        # Regen to establish DB + sidecar
        await regen_single_folder(brain, "project", config=config, backend=backend)

        # Write stale sidecar (simulate Phase 4 stale export)
        write_regen_meta(
            brain / "insights" / "project",
            RegenMeta(content_hash="stale_hash", summary_hash="stale_sum"),
        )

        # Doctor should repair the stale sidecar before checking, so no
        # would-trigger-regen findings should appear for "project"
        result = run_doctor(brain, fix=False)
        regen_findings = [
            f for f in result.findings if f.check == "regen_change_detection" and f.knowledge_path == "project"
        ]
        assert len(regen_findings) == 0, f"Doctor incorrectly reported regen findings: {regen_findings}"

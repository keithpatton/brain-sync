"""Integration tests for sidecar-authoritative read path (v21+).

In v21, sidecars are the sole authority for regen hashes.
- save_insight_state() writes hashes to sidecars directly
- delete_insight_state() removes both sidecar and regen_locks row
- load_regen_hashes() reads from sidecar only
"""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.insights import InsightState, save_insight_state
from brain_sync.brain.layout import area_insights_dir
from brain_sync.brain.sidecar import (
    RegenMeta,
    read_regen_meta,
    write_regen_meta,
)
from brain_sync.llm.fake import FakeBackend
from brain_sync.regen import classify_folder_change
from brain_sync.regen.engine import RegenConfig, regen_single_folder

pytestmark = pytest.mark.integration


def _config() -> RegenConfig:
    return RegenConfig(model="fake-model", effort="low", timeout=30)


def _insights_dir(root: Path, knowledge_path: str) -> Path:
    return area_insights_dir(root, knowledge_path)


class TestSaveWritesSidecar:
    """save_insight_state() writes sidecar directly in v21+."""

    def test_save_writes_sidecar_directly(self, brain: Path) -> None:
        """save_insight_state() writes sidecar — no sync needed."""
        insights_dir = _insights_dir(brain, "project")
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

        meta = read_regen_meta(insights_dir)
        assert meta is not None
        assert meta.content_hash == "ch1"
        assert meta.summary_hash == "sh1"
        assert meta.structure_hash == "st1"


class TestClassifyReadsFromSidecar:
    """Classify reads hashes from sidecars (the sole authority in v21)."""

    async def test_classify_reads_from_sidecar(self, brain: Path) -> None:
        """After regen, sidecar provides hashes. Content unchanged -> 'none'."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        await regen_single_folder(brain, "project", config=config, backend=backend)

        # Sidecar exists and has hashes — content unchanged
        event, _, _ = classify_folder_change(brain, "project")
        assert event.change_type == "none"

    def test_no_sidecar_means_new_content(self, brain: Path) -> None:
        """Without sidecar, classify sees new content (no prior hashes)."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        # No regen done -> no sidecar -> classify sees content change
        event, _, _ = classify_folder_change(brain, "project")
        assert event.change_type == "content"


class TestRegenSkipsUnchangedFromSidecar:
    """Regen reads hashes from sidecar, skips when unchanged."""

    async def test_regen_skips_unchanged_from_sidecar(self, brain: Path) -> None:
        """Delete regen_locks row only, keep sidecar -> regen still skips."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        # First regen establishes sidecar + regen_locks
        result1 = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result1.action == "regenerated"

        # Delete regen_locks row only (keep sidecar) via raw SQL
        from brain_sync.runtime.repository import _connect

        conn = _connect(brain)
        try:
            conn.execute("DELETE FROM regen_locks WHERE knowledge_path = ?", ("project",))
            conn.commit()
        finally:
            conn.close()

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
        sidecar_before = read_regen_meta(_insights_dir(brain, "area"))
        assert sidecar_before is not None

        # Nuke entire DB
        from brain_sync.runtime import config as runtime_config

        db_path = runtime_config.RUNTIME_DB_FILE
        if db_path.exists():
            db_path.unlink()

        result = await regen_single_folder(brain, "area", config=config, backend=backend)
        assert result.action == "skipped_unchanged"


class TestStaleSidecarRepair:
    """Stale sidecar written directly does not persist after regen overwrites it."""

    async def test_regen_overwrites_stale_sidecar(self, brain: Path) -> None:
        """After regen, a manually-overwritten sidecar triggers re-regen."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        # Regen to establish correct sidecar
        result1 = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result1.action == "regenerated"

        # Write stale sidecar (simulate corruption — include structure_hash to avoid backfill path)
        write_regen_meta(
            _insights_dir(brain, "project"),
            RegenMeta(content_hash="stale_hash", summary_hash="stale_sum", structure_hash="stale_struct"),
        )

        # Regen should see content change (stale hashes don't match current content)
        result2 = await regen_single_folder(brain, "project", config=config, backend=backend)
        assert result2.action == "regenerated"

        # After re-regen, sidecar should have correct hashes again
        meta = read_regen_meta(_insights_dir(brain, "project"))
        assert meta is not None
        assert meta.content_hash != "stale_hash"


class TestDoctorWithStaleSidecar:
    """Doctor detects content change when sidecar has stale hashes."""

    async def test_doctor_detects_stale_sidecar_as_content_change(self, brain: Path) -> None:
        """Stale sidecar causes doctor to report would-trigger-regen."""
        from brain_sync.application.doctor import doctor as run_doctor

        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        backend = FakeBackend(mode="stable")
        config = _config()

        # Regen to establish correct sidecar
        await regen_single_folder(brain, "project", config=config, backend=backend)

        # Write stale sidecar (include structure_hash to avoid backfill path)
        write_regen_meta(
            _insights_dir(brain, "project"),
            RegenMeta(content_hash="stale_hash", summary_hash="stale_sum", structure_hash="stale_struct"),
        )

        # Doctor should detect the stale sidecar as a content change
        result = run_doctor(brain, fix=False)
        regen_findings = [
            f for f in result.findings if f.check == "regen_change_detection" and f.knowledge_path == "project"
        ]
        # In v21, stale sidecar means classify sees a content change
        assert len(regen_findings) == 1

"""System tests for brain-sync doctor CLI."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.harness.cli import CliRunner

pytestmark = pytest.mark.system


class TestDoctorCleanBrain:
    def test_exits_zero(self, cli: CliRunner, brain_root: Path) -> None:
        cli.run("init", str(brain_root))
        result = cli.run("doctor", "--root", str(brain_root))
        assert result.returncode == 0, f"Doctor failed: {result.stderr}"
        assert "healthy" in result.stderr.lower()


class TestDoctorWithIssues:
    def test_exits_one_on_drift(self, cli: CliRunner, brain_root: Path) -> None:
        cli.run("init", str(brain_root))
        # Create an orphan insights dir (no matching knowledge)
        orphan = brain_root / "insights" / "orphan_area"
        orphan.mkdir(parents=True)
        (orphan / "summary.md").write_text("# Orphan summary")

        result = cli.run("doctor", "--root", str(brain_root))
        assert result.returncode == 1


class TestDoctorFix:
    def test_fix_exits_zero(self, cli: CliRunner, brain_root: Path) -> None:
        cli.run("init", str(brain_root))
        # Create orphan insights dir (no summary to avoid WOULD_TRIGGER_REGEN)
        orphan = brain_root / "insights" / "orphan_area"
        orphan.mkdir(parents=True)

        result = cli.run("doctor", "--fix", "--root", str(brain_root))
        assert result.returncode == 0, f"Doctor --fix failed: {result.stderr}"
        assert not orphan.exists()


class TestDoctorRebuildDb:
    def test_rebuild_exits_zero(self, cli: CliRunner, brain_root: Path) -> None:
        cli.run("init", str(brain_root))
        result = cli.run("doctor", "--rebuild-db", "--root", str(brain_root))
        assert result.returncode == 0, f"Doctor --rebuild-db failed: {result.stderr}"


class TestDoctorWouldTriggerRegenExitsOne:
    def test_exits_one_on_would_trigger_regen(self, cli: CliRunner, brain_root: Path) -> None:
        """WOULD_TRIGGER_REGEN findings cause non-zero exit."""
        cli.run("init", str(brain_root))
        # Create a knowledge dir with content but insight_state with stale hash
        (brain_root / "knowledge" / "project").mkdir(parents=True)
        (brain_root / "knowledge" / "project" / "doc.md").write_text("# Content")
        (brain_root / "insights" / "project").mkdir(parents=True)
        (brain_root / "insights" / "project" / "summary.md").write_text("# Summary")

        # Insert regen_locks row + write stale sidecar with non-matching hashes
        # (non-null structure_hash prevents backfill from overwriting content_hash)
        import sqlite3

        from brain_sync.sidecar import RegenMeta, write_regen_meta

        db = brain_root / ".sync-state.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT OR REPLACE INTO regen_locks (knowledge_path, regen_status) VALUES (?, ?)",
            ("project", "idle"),
        )
        conn.commit()
        conn.close()

        # Write stale sidecar (the authority for hashes in v21)
        write_regen_meta(
            brain_root / "insights" / "project",
            RegenMeta(content_hash="stale_hash_that_wont_match", structure_hash="stale_struct_hash"),
        )

        result = cli.run("doctor", "--root", str(brain_root))
        assert result.returncode == 1


class TestDoctorWouldTriggerFetchExitsOne:
    def test_exits_one_on_would_trigger_fetch(self, cli: CliRunner, brain_root: Path) -> None:
        """WOULD_TRIGGER_FETCH findings cause non-zero exit."""
        import json

        cli.run("init", str(brain_root))
        # Write a manifest with a materialized_path pointing to a non-existent file
        manifest_dir = brain_root / ".brain-sync" / "sources"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "manifest_version": 1,
            "canonical_id": "confluence:99999",
            "source_url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/99999",
            "source_type": "confluence",
            "materialized_path": "area/c99999-missing-doc.md",
            "fetch_children": False,
            "sync_attachments": False,
            "target_path": "area",
            "status": "active",
        }
        (manifest_dir / "confluence-99999.json").write_text(json.dumps(manifest))

        result = cli.run("doctor", "--root", str(brain_root))
        assert result.returncode == 1


class TestDoctorMutualExclusivity:
    def test_multiple_flags_exits_one(self, cli: CliRunner, brain_root: Path) -> None:
        cli.run("init", str(brain_root))
        result = cli.run("doctor", "--fix", "--rebuild-db", "--root", str(brain_root))
        assert result.returncode == 1
        assert "mutually exclusive" in result.stderr.lower()

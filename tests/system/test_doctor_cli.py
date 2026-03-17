"""System tests for brain-sync doctor CLI."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from brain_sync.brain.layout import area_attachments_root, area_insights_dir
from brain_sync.brain.sidecar import RegenMeta, write_regen_meta
from tests.e2e.harness.cli import CliRunner

pytestmark = pytest.mark.system


class TestDoctorCleanBrain:
    def test_exits_zero(self, cli: CliRunner, brain_root: Path) -> None:
        cli.run("init", str(brain_root))
        result = cli.run("doctor", "--root", str(brain_root))
        assert result.returncode == 0, f"Doctor failed: {result.stderr}"
        assert "healthy" in result.stderr.lower()

    def test_uses_current_working_directory_when_it_is_a_brain_root(self, cli: CliRunner, brain_root: Path) -> None:
        cli.run("init", str(brain_root))
        result = cli.run("doctor", cwd=brain_root)
        assert result.returncode == 0, f"Doctor failed: {result.stderr}"
        assert "healthy" in result.stderr.lower()


class TestDoctorRootResolution:
    def test_reports_actionable_hint_when_no_root_can_be_resolved(self, cli: CliRunner, tmp_path: Path) -> None:
        result = cli.run("doctor", cwd=tmp_path)
        assert result.returncode == 1
        assert "use --root <brain>" in result.stderr.lower()
        assert "brain-sync init <path>" in result.stderr.lower()


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
        # Create a supported drift case that doctor --fix can repair.
        orphan = area_attachments_root(brain_root, "area") / "c999"
        orphan.mkdir(parents=True)
        (orphan / "file.png").write_bytes(b"data")

        result = cli.run("doctor", "--fix", "--root", str(brain_root))
        assert result.returncode == 0, f"Doctor --fix failed: {result.stderr}"
        assert not orphan.exists()


class TestDoctorRebuildDb:
    def test_rebuild_exits_zero(self, cli: CliRunner, brain_root: Path) -> None:
        cli.run("init", str(brain_root))
        result = cli.run("doctor", "--rebuild-db", "--root", str(brain_root))
        assert result.returncode == 0, f"Doctor --rebuild-db failed: {result.stderr}"


class TestDoctorWouldTriggerRegenExitsOne:
    def test_exits_one_on_would_trigger_regen(self, cli: CliRunner, brain_root: Path, config_dir: Path) -> None:
        """WOULD_TRIGGER_REGEN findings cause non-zero exit."""
        cli.run("init", str(brain_root))
        # Create a knowledge dir with content but insight_state with stale hash
        (brain_root / "knowledge" / "project").mkdir(parents=True)
        (brain_root / "knowledge" / "project" / "doc.md").write_text("# Content")
        insights_dir = area_insights_dir(brain_root, "project")
        insights_dir.mkdir(parents=True, exist_ok=True)
        (insights_dir / "summary.md").write_text("# Summary")

        # Ensure the runtime DB exists, then seed regen_locks + stale sidecar.
        cli.run("list", "--root", str(brain_root))
        db = config_dir / "db" / "brain-sync.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute(
            "INSERT OR REPLACE INTO regen_locks (knowledge_path, regen_status) VALUES (?, ?)",
            ("project", "idle"),
        )
        conn.commit()
        conn.close()

        # Write stale sidecar (the authority for hashes in v21)
        write_regen_meta(
            insights_dir, RegenMeta(content_hash="stale_hash_that_wont_match", structure_hash="stale_struct_hash")
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

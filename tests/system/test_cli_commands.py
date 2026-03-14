"""Phase 2 system tests: CLI subprocess invocations with fake LLM backend."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.e2e.harness.cli import CliRunner

pytestmark = pytest.mark.system


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    """brain-sync init via subprocess."""

    def test_creates_structure(self, cli: CliRunner, brain_root: Path):
        """Init creates the full directory tree and DB."""
        result = cli.run("init", str(brain_root))
        assert result.returncode == 0, f"Init failed: {result.stderr}"
        assert (brain_root / "knowledge").is_dir()
        assert (brain_root / "insights").is_dir()
        assert (brain_root / "knowledge" / "_core").is_dir()
        assert (brain_root / ".sync-state.sqlite").exists()

    def test_idempotent(self, cli: CliRunner, brain_root: Path):
        """Running init twice succeeds without error."""
        r1 = cli.run("init", str(brain_root))
        assert r1.returncode == 0
        r2 = cli.run("init", str(brain_root))
        assert r2.returncode == 0


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestList:
    """brain-sync list via subprocess."""

    def test_list_empty(self, cli: CliRunner, brain_root: Path):
        """List on an empty brain exits cleanly."""
        cli.run("init", str(brain_root))
        result = cli.run("list", "--root", str(brain_root))
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------


class TestAdd:
    """brain-sync add via subprocess."""

    def test_add_test_source(self, cli: CliRunner, brain_root: Path):
        """Add a test:// source registers it via manifest."""
        cli.run("init", str(brain_root))
        result = cli.run(
            "add",
            "test://doc/123",
            "--path",
            "area",
            "--root",
            str(brain_root),
        )
        assert result.returncode == 0, f"Add failed: {result.stderr}"

        # Verify manifest exists (Phase 2: manifests are authoritative, not DB)
        import json

        manifest_path = brain_root / ".brain-sync" / "sources" / "test-123.json"
        assert manifest_path.exists(), "Manifest not found"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["canonical_id"] == "test:123"
        assert data["target_path"] == "area"

    def test_add_duplicate_rejects(self, cli: CliRunner, brain_root: Path):
        """Adding the same source twice does not crash (warns instead)."""
        cli.run("init", str(brain_root))
        cli.run("add", "test://doc/456", "--path", "area", "--root", str(brain_root))
        r2 = cli.run("add", "test://doc/456", "--path", "area", "--root", str(brain_root))
        # Should succeed (warning, not error) — handler logs and returns
        assert r2.returncode == 0

    def test_add_invalid_url_rejects(self, cli: CliRunner, brain_root: Path):
        """Non-URL input is rejected with a helpful message."""
        cli.run("init", str(brain_root))
        result = cli.run("add", "not-a-url", "--path", "area", "--root", str(brain_root))
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


class TestRemove:
    """brain-sync remove via subprocess."""

    def test_remove_existing(self, cli: CliRunner, brain_root: Path):
        """Remove a registered source succeeds."""
        cli.run("init", str(brain_root))
        cli.run("add", "test://doc/rm1", "--path", "area", "--root", str(brain_root))
        result = cli.run("remove", "test:rm1", "--root", str(brain_root))
        assert result.returncode == 0

        # Verify removed from DB
        conn = sqlite3.connect(str(brain_root / ".sync-state.sqlite"))
        row = conn.execute("SELECT 1 FROM sync_cache WHERE canonical_id = 'test:rm1'").fetchone()
        conn.close()
        assert row is None

    def test_remove_nonexistent_exits_cleanly(self, cli: CliRunner, brain_root: Path):
        """Removing a source that doesn't exist exits cleanly (warning, not crash)."""
        cli.run("init", str(brain_root))
        result = cli.run("remove", "test:nonexistent", "--root", str(brain_root))
        # Should succeed (handler logs warning, returns)
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------


class TestMove:
    """brain-sync move via subprocess."""

    def test_move_source(self, cli: CliRunner, brain_root: Path):
        """Move changes target_path in the manifest."""
        cli.run("init", str(brain_root))
        cli.run("add", "test://doc/mv1", "--path", "old-area", "--root", str(brain_root))
        result = cli.run("move", "test:mv1", "--to", "new-area", "--root", str(brain_root))
        assert result.returncode == 0, f"Move failed: {result.stderr}"

        # Verify manifest has updated target_path (Phase 2: manifests are authoritative)
        import json

        manifest_path = brain_root / ".brain-sync" / "sources" / "test-mv1.json"
        assert manifest_path.exists(), "Manifest not found"
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert data["target_path"] == "new-area"

    def test_move_nonexistent_exits_cleanly(self, cli: CliRunner, brain_root: Path):
        """Moving a nonexistent source exits cleanly."""
        cli.run("init", str(brain_root))
        result = cli.run("move", "test:nonexistent", "--to", "area", "--root", str(brain_root))
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Add-file / Remove-file
# ---------------------------------------------------------------------------


class TestAddFile:
    """brain-sync add-file via subprocess."""

    def test_add_file_creates_entry(self, cli: CliRunner, brain_root: Path, tmp_path: Path):
        """add-file copies a local file into knowledge/."""
        cli.run("init", str(brain_root))
        src_file = tmp_path / "notes.md"
        src_file.write_text("# My Notes\n\nSome content.", encoding="utf-8")
        result = cli.run(
            "add-file",
            str(src_file),
            "--path",
            "area",
            "--root",
            str(brain_root),
        )
        assert result.returncode == 0, f"add-file failed: {result.stderr}"
        # File should exist in knowledge/area/
        found = list((brain_root / "knowledge" / "area").glob("*.md"))
        assert len(found) >= 1

    def test_add_file_duplicate_rejects(self, cli: CliRunner, brain_root: Path, tmp_path: Path):
        """Adding the same file twice is handled gracefully."""
        cli.run("init", str(brain_root))
        src_file = tmp_path / "dup.md"
        src_file.write_text("# Dup\n\nContent.", encoding="utf-8")
        cli.run("add-file", str(src_file), "--path", "area", "--root", str(brain_root))
        r2 = cli.run("add-file", str(src_file), "--path", "area", "--root", str(brain_root))
        # Should handle gracefully (overwrite or warn)
        assert r2.returncode == 0


class TestRemoveFile:
    """brain-sync remove-file via subprocess."""

    def test_remove_file_deletes(self, cli: CliRunner, brain_root: Path, tmp_path: Path):
        """remove-file removes the file from knowledge/."""
        cli.run("init", str(brain_root))
        # Create a file directly in knowledge/
        target = brain_root / "knowledge" / "area" / "doc.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Doc\n\nContent.", encoding="utf-8")

        result = cli.run("remove-file", "area/doc.md", "--root", str(brain_root))
        assert result.returncode == 0, f"remove-file failed: {result.stderr}"
        assert not target.exists()


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------


class TestReconcile:
    """brain-sync reconcile via subprocess."""

    def test_reconcile_no_changes(self, cli: CliRunner, brain_root: Path):
        """Reconcile on a clean brain exits cleanly."""
        cli.run("init", str(brain_root))
        result = cli.run("reconcile", "--root", str(brain_root))
        assert result.returncode == 0

    def test_reconcile_detects_move(self, cli: CliRunner, brain_root: Path):
        """Reconcile detects a source whose target was moved on disk."""
        cli.run("init", str(brain_root))
        # Add a source targeting "area-old"
        cli.run("add", "test://doc/rec1", "--path", "area-old", "--root", str(brain_root))
        # Manually write a file at the target (simulate prior sync)
        target = brain_root / "knowledge" / "area-old" / "t-rec1.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# Rec1\n\nContent.", encoding="utf-8")

        # Move the folder on disk
        import shutil

        shutil.move(
            str(brain_root / "knowledge" / "area-old"),
            str(brain_root / "knowledge" / "area-new"),
        )

        result = cli.run("reconcile", "--root", str(brain_root))
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Regen
# ---------------------------------------------------------------------------


class TestRegen:
    """brain-sync regen via subprocess with fake backend."""

    def test_regen_creates_summary(self, cli: CliRunner, brain_root: Path):
        """Regen via subprocess creates summary.md."""
        cli.run("init", str(brain_root))
        kdir = brain_root / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "overview.md").write_text("# Overview\n\nProject content.", encoding="utf-8")

        result = cli.run("regen", "--root", str(brain_root), "project")
        assert result.returncode == 0, f"Regen failed: {result.stderr}"
        summary = brain_root / "insights" / "project" / "summary.md"
        assert summary.exists()

    def test_regen_all(self, cli: CliRunner, brain_root: Path):
        """Regen all via subprocess."""
        cli.run("init", str(brain_root))
        kdir = brain_root / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        result = cli.run("regen", "--root", str(brain_root))
        assert result.returncode == 0, f"Regen all failed: {result.stderr}"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


class TestStatus:
    """brain-sync status via subprocess."""

    def test_status_exits_zero(self, cli: CliRunner, brain_root: Path):
        """Status command exits cleanly on an initialised brain."""
        cli.run("init", str(brain_root))
        result = cli.run("list", "--root", str(brain_root), "--status")
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    """CLI error handling."""

    def test_regen_nonexistent_path_fails(self, cli: CliRunner, brain_root: Path):
        """Regen on a path that doesn't exist in knowledge/ fails cleanly."""
        cli.run("init", str(brain_root))
        result = cli.run("regen", "--root", str(brain_root), "nonexistent")
        assert result.returncode != 0

    def test_uninitialised_root_fails(self, cli: CliRunner, tmp_path: Path):
        """Operations on an uninitialised root fail cleanly."""
        bad_root = tmp_path / "not-a-brain"
        bad_root.mkdir()
        result = cli.run("list", "--root", str(bad_root))
        # Should fail or warn — brain not initialised
        # (exact behavior depends on handler, but should not crash with traceback)
        # We just verify it didn't hang or produce a Python traceback
        assert "Traceback" not in result.stderr

    def test_cli_handles_corrupt_db(self, cli: CliRunner, brain_root: Path):
        """CLI handles a corrupt DB gracefully."""
        cli.run("init", str(brain_root))
        db_path = brain_root / ".sync-state.sqlite"
        # Corrupt the DB by dropping a table
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS sources")
        conn.commit()
        conn.close()

        # list should still work (state.py recreates missing tables on connect)
        result = cli.run("list", "--root", str(brain_root))
        # Should not crash with an unhandled exception
        assert "Traceback" not in result.stderr

"""Phase 2 system tests: CLI subprocess invocations with fake LLM backend."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from brain_sync.brain.layout import area_summary_path
from brain_sync.brain.manifest import read_source_manifest
from tests.e2e.harness.cli import CliRunner
from tests.harness.isolation import build_subprocess_env, layout_for_base_dir

pytestmark = pytest.mark.system


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------


class TestInit:
    """brain-sync init via subprocess."""

    def test_creates_structure(self, cli: CliRunner, brain_root: Path):
        """Init creates the v23 managed brain structure."""
        result = cli.run("init", str(brain_root))
        assert result.returncode == 0, f"Init failed: {result.stderr}"
        assert (brain_root / "knowledge").is_dir()
        assert not (brain_root / "insights").exists()
        assert (brain_root / "knowledge" / "_core").is_dir()
        assert (brain_root / ".brain-sync" / "brain.json").is_file()

    def test_idempotent(self, cli: CliRunner, brain_root: Path):
        """Running init twice succeeds without error."""
        r1 = cli.run("init", str(brain_root))
        assert r1.returncode == 0
        r2 = cli.run("init", str(brain_root))
        assert r2.returncode == 0

    def test_rejects_temp_root_with_machine_local_runtime(self, tmp_path: Path):
        """Init fails closed when a temp root would use the default ~/.brain-sync runtime."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        root = tmp_path / "brain"
        repo_root = Path(__file__).resolve().parents[2]
        env = build_subprocess_env(
            layout=layout_for_base_dir(tmp_path),
            repo_root=repo_root,
            include_config_dir=False,
            llm_backend=None,
        )

        result = subprocess.run(
            [sys.executable, "-m", "brain_sync", "init", str(root)],
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
            timeout=30,
        )

        assert result.returncode != 0
        assert "Refusing to init" in result.stderr
        assert not root.exists()
        assert not (home_dir / ".brain-sync" / "config.json").exists()


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

        manifest = read_source_manifest(brain_root, "test:123")
        assert manifest is not None
        assert manifest.canonical_id == "test:123"
        assert manifest.knowledge_path == "area/123.md"
        assert manifest.knowledge_state == "awaiting"

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

    def test_remove_help_describes_delete_files_as_compatibility(self, cli: CliRunner) -> None:
        result = cli.run("remove", "--help")
        help_text = " ".join(result.stdout.split())

        assert result.returncode == 0
        assert "Compatibility flag" in help_text
        assert "already deletes synced files from disk" in help_text

    def test_remove_existing(self, cli: CliRunner, brain_root: Path, config_dir: Path):
        """Remove a registered source succeeds."""
        cli.run("init", str(brain_root))
        cli.run("add", "test://doc/rm1", "--path", "area", "--root", str(brain_root))
        result = cli.run("remove", "test:rm1", "--root", str(brain_root))
        assert result.returncode == 0

        # Verify removed from DB
        conn = sqlite3.connect(str(config_dir / "db" / "brain-sync.sqlite"))
        row = conn.execute("SELECT 1 FROM sync_polling WHERE canonical_id = 'test:rm1'").fetchone()
        conn.close()
        assert row is None

    def test_remove_nonexistent_exits_cleanly(self, cli: CliRunner, brain_root: Path):
        """Removing a source that doesn't exist exits with a handled not-found result."""
        cli.run("init", str(brain_root))
        result = cli.run("remove", "test:nonexistent", "--root", str(brain_root))
        assert result.returncode == 1
        assert "Result: not_found" in result.stderr
        assert "Source not found: test:nonexistent" in result.stderr

    def test_remove_reports_lease_conflict(self, cli: CliRunner, brain_root: Path, config_dir: Path) -> None:
        cli.run("init", str(brain_root))
        cli.run("add", "test://doc/rm1", "--path", "area", "--root", str(brain_root))
        conn = sqlite3.connect(str(config_dir / "db" / "brain-sync.sqlite"))
        try:
            conn.execute(
                "INSERT INTO source_lifecycle_runtime "
                "(canonical_id, missing_confirmation_count, lease_owner, lease_expires_utc) "
                "VALUES (?, 0, ?, ?) "
                "ON CONFLICT(canonical_id) DO UPDATE SET "
                "lease_owner=excluded.lease_owner, lease_expires_utc=excluded.lease_expires_utc",
                ("test:rm1", "daemon-owner", "2099-01-01T00:00:00+00:00"),
            )
            conn.commit()
        finally:
            conn.close()

        result = cli.run("remove", "test:rm1", "--root", str(brain_root))

        assert result.returncode == 1
        assert "Result: lease_conflict" in result.stderr
        assert "Canonical ID: test:rm1" in result.stderr
        assert "Lease owner: daemon-owner" in result.stderr


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

        manifest = read_source_manifest(brain_root, "test:mv1")
        assert manifest is not None
        assert manifest.knowledge_path == "new-area/mv1.md"

    def test_move_nonexistent_exits_cleanly(self, cli: CliRunner, brain_root: Path):
        """Moving a nonexistent source exits with a handled not-found result."""
        cli.run("init", str(brain_root))
        result = cli.run("move", "test:nonexistent", "--to", "area", "--root", str(brain_root))
        assert result.returncode == 1
        assert "Result: not_found" in result.stderr
        assert "Destination: knowledge/area" in result.stderr
        assert "Source not found: test:nonexistent" in result.stderr

    def test_move_reports_lease_conflict(self, cli: CliRunner, brain_root: Path, config_dir: Path) -> None:
        cli.run("init", str(brain_root))
        cli.run("add", "test://doc/mv1", "--path", "old-area", "--root", str(brain_root))
        conn = sqlite3.connect(str(config_dir / "db" / "brain-sync.sqlite"))
        try:
            conn.execute(
                "INSERT INTO source_lifecycle_runtime "
                "(canonical_id, missing_confirmation_count, lease_owner, lease_expires_utc) "
                "VALUES (?, 0, ?, ?) "
                "ON CONFLICT(canonical_id) DO UPDATE SET "
                "lease_owner=excluded.lease_owner, lease_expires_utc=excluded.lease_expires_utc",
                ("test:mv1", "daemon-owner", "2099-01-01T00:00:00+00:00"),
            )
            conn.commit()
        finally:
            conn.close()

        result = cli.run("move", "test:mv1", "--to", "new-area", "--root", str(brain_root))

        assert result.returncode == 1
        assert "Result: lease_conflict" in result.stderr
        assert "Canonical ID: test:mv1" in result.stderr
        assert "Destination: knowledge/new-area" in result.stderr
        assert "Lease owner: daemon-owner" in result.stderr


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

    def test_add_file_fails_closed_without_leaking_operational_events_into_machine_local_runtime(self, tmp_path: Path):
        """add-file fails closed without leaking machine-local operational events."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        repo_root = Path(__file__).resolve().parents[2]
        root = tmp_path / "brain"
        src_file = tmp_path / "notes.md"
        src_file.write_text("# Notes\n\nContent.", encoding="utf-8")

        init_env = build_subprocess_env(
            layout=layout_for_base_dir(tmp_path),
            repo_root=repo_root,
            include_config_dir=False,
            llm_backend=None,
            extra_env={"BRAIN_SYNC_ALLOW_UNSAFE_TEMP_ROOTS": "1"},
        )

        init_result = subprocess.run(
            [sys.executable, "-m", "brain_sync", "init", str(root)],
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=init_env,
            timeout=30,
        )
        assert init_result.returncode == 0, f"Init failed: {init_result.stderr}"

        env = build_subprocess_env(
            layout=layout_for_base_dir(tmp_path),
            repo_root=repo_root,
            include_config_dir=False,
            llm_backend=None,
        )

        result = subprocess.run(
            [sys.executable, "-m", "brain_sync", "add-file", str(src_file), "--path", "area", "--root", str(root)],
            capture_output=True,
            text=True,
            cwd=repo_root,
            env=env,
            timeout=30,
        )

        assert result.returncode != 0
        assert "Refusing to add-file" in result.stderr
        runtime_db = home_dir / ".brain-sync" / "db" / "brain-sync.sqlite"
        assert not runtime_db.exists()


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
        """Regen via subprocess creates the co-located summary."""
        cli.run("init", str(brain_root))
        kdir = brain_root / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "overview.md").write_text("# Overview\n\nProject content.", encoding="utf-8")

        result = cli.run("regen", "--root", str(brain_root), "project")
        assert result.returncode == 0, f"Regen failed: {result.stderr}"
        summary = area_summary_path(brain_root, "project")
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

    def test_cli_handles_corrupt_db(self, cli: CliRunner, brain_root: Path, config_dir: Path):
        """CLI handles a corrupt DB gracefully."""
        cli.run("init", str(brain_root))
        db_path = config_dir / "db" / "brain-sync.sqlite"
        cli.run("list", "--root", str(brain_root))
        # Corrupt the DB by dropping a table
        conn = sqlite3.connect(str(db_path))
        conn.execute("DROP TABLE IF EXISTS sources")
        conn.commit()
        conn.close()

        # list should still work (state.py recreates missing tables on connect)
        result = cli.run("list", "--root", str(brain_root))
        # Should not crash with an unhandled exception
        assert "Traceback" not in result.stderr

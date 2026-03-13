"""Phase 2 system tests: CLI subprocess invocations with fake LLM backend."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.harness.cli import CliRunner

pytestmark = pytest.mark.system


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


class TestList:
    """brain-sync list via subprocess."""

    def test_list_empty(self, cli: CliRunner, brain_root: Path):
        """List on an empty brain exits cleanly."""
        cli.run("init", str(brain_root))
        result = cli.run("list", "--root", str(brain_root))
        assert result.returncode == 0


class TestRegen:
    """brain-sync regen via subprocess with fake backend."""

    def test_regen_creates_summary(self, cli: CliRunner, brain_root: Path):
        """Regen via subprocess creates summary.md."""
        cli.run("init", str(brain_root))
        # Create knowledge content
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


class TestStatus:
    """brain-sync status via subprocess."""

    def test_status_exits_zero(self, cli: CliRunner, brain_root: Path):
        """Status command exits cleanly on an initialised brain."""
        cli.run("init", str(brain_root))
        result = cli.run("list", "--root", str(brain_root), "--status")
        assert result.returncode == 0

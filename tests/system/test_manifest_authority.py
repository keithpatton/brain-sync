"""System tests: manifest authority via CLI subprocess."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.harness.cli import CliRunner

pytestmark = pytest.mark.system


class TestManifestAuthority:
    def test_list_with_manifests_no_db(self, cli: CliRunner, brain_root: Path):
        """brain-sync list with manifests but no DB still shows sources."""
        # Init brain and add a source
        cli.run("init", str(brain_root))
        result = cli.run(
            "add",
            "https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page",
            "--path",
            "area",
            "--root",
            str(brain_root),
        )
        assert result.returncode == 0, f"Add failed: {result.stderr}"

        # Delete DB
        db = brain_root / ".sync-state.sqlite"
        if db.exists():
            db.unlink()

        # List should still work
        result = cli.run("list", "--root", str(brain_root))
        assert result.returncode == 0, f"List failed: {result.stderr}"
        # CLI outputs source info via logging to stderr
        assert "confluence:12345" in result.stderr

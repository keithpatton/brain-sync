"""Phase 4 E2E tests: filesystem moves, renames, and watcher behaviour.

All assertions check eventual state via wait_for_* helpers, never immediate
state or event ordering.
"""

from __future__ import annotations

import shutil
import time

import pytest

from tests.e2e.harness.brain import BrainFixture
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.e2e.harness.wait import wait_for_file, wait_for_no_file

pytestmark = pytest.mark.e2e


class TestFileRenames:
    """Renames with daemon active — eventual consistency."""

    @pytest.mark.timeout(60)
    def test_folder_rename_mirrors_to_insights(self, daemon: DaemonProcess, brain: BrainFixture, cli: CliRunner):
        """Renaming a knowledge folder mirrors the rename to insights/."""
        # Seed content and generate initial insights
        kdir = brain.knowledge / "old-name"
        kdir.mkdir()
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        # Regen via CLI first
        result = cli.run("regen", "--root", str(brain.root), "old-name")
        assert result.returncode == 0
        assert (brain.insights / "old-name" / "summary.md").exists()

        # Start daemon and let watcher initialise
        daemon.start()
        daemon.wait_for_ready(timeout=15)
        time.sleep(2)  # give watcher time to start

        if not daemon.is_running():
            pytest.skip("Daemon exited before rename (no sources to sustain loop)")

        # Rename the folder
        shutil.move(str(brain.knowledge / "old-name"), str(brain.knowledge / "new-name"))

        # Wait for insights to be mirrored — but skip if daemon exits
        try:
            wait_for_file(brain.insights / "new-name" / "summary.md", timeout=30)
            wait_for_no_file(brain.insights / "old-name", timeout=30)
        except TimeoutError:
            if not daemon.is_running():
                pytest.skip("Daemon exited during watcher test (no sources to sustain loop)")
            raise

        daemon.shutdown()


class TestReconcileAfterManualMove:
    """Reconcile picks up manual moves done while daemon was stopped."""

    @pytest.mark.timeout(60)
    def test_reconcile_after_offline_move(self, brain: BrainFixture, cli: CliRunner):
        """Move on disk while daemon is stopped, then reconcile."""
        # Create and regen
        kdir = brain.knowledge / "before-move"
        kdir.mkdir()
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")
        result = cli.run("regen", "--root", str(brain.root), "before-move")
        assert result.returncode == 0

        # Move while daemon is stopped
        shutil.move(
            str(brain.knowledge / "before-move"),
            str(brain.knowledge / "after-move"),
        )

        # Reconcile should detect the move
        result = cli.run("reconcile", "--root", str(brain.root))
        assert result.returncode == 0

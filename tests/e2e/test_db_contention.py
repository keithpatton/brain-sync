"""Phase 3C: DB contention E2E tests.

Verify that CLI and daemon can safely share the SQLite database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.e2e.harness.assertions import assert_brain_consistent
from tests.e2e.harness.brain import BrainFixture, seed_knowledge_tree
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.e2e.harness.scenarios import run_regen

pytestmark = pytest.mark.e2e


class TestCliWhileDaemonActive:
    """CLI commands execute safely while daemon is running."""

    def test_list_while_daemon_running(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area/": {"doc.md": "# Doc\n\nContent."},
                },
            },
        )

        daemon.start()
        daemon.wait_for_ready()

        # Run CLI list while daemon is active
        result = cli.run("list", "--root", str(brain.root))
        assert result.returncode == 0
        assert "Traceback" not in result.stderr

        daemon.shutdown()

    def test_regen_while_daemon_running(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area/": {"doc.md": "# Doc\n\nContent."},
                },
            },
        )

        daemon.start()
        daemon.wait_for_ready()

        # Run CLI regen while daemon is active
        result = cli.run("regen", "--root", str(brain.root), "area")
        # May succeed or fail (concurrent regen lock), but should not crash
        assert "Traceback" not in result.stderr

        daemon.shutdown()
        assert_brain_consistent(brain.root)

    def test_status_while_daemon_running(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        daemon.start()
        daemon.wait_for_ready()

        result = cli.run("list", "--root", str(brain.root), "--status")
        assert result.returncode == 0
        assert "Traceback" not in result.stderr

        daemon.shutdown()


class TestConcurrentAddRemove:
    """Rapid add/remove CLI calls while daemon active."""

    def test_concurrent_add_remove(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        daemon.start()
        daemon.wait_for_ready()

        # Rapid add/remove cycle
        for i in range(5):
            cli.run("add", f"test://doc/rapid{i}", "--path", f"rapid{i}", "--root", str(brain.root))
        for i in range(5):
            cli.run("remove", f"test:rapid{i}", "--root", str(brain.root))

        daemon.shutdown()
        assert_brain_consistent(brain.root)


class TestStaleSessionReclaim:
    """Daemon reclaims stale regen_session rows on startup."""

    def test_stale_session_reclaim(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area/": {"doc.md": "# Doc\n\nContent."},
                },
            },
        )
        run_regen(cli, brain.root, "area")

        # Manually insert a stale running state
        conn = sqlite3.connect(str(brain.db_path))
        conn.execute(
            "UPDATE regen_locks SET regen_status = 'running', "
            "regen_started_utc = '2020-01-01T00:00:00+00:00', "
            "owner_id = 'stale-owner' "
            "WHERE knowledge_path = 'area'"
        )
        conn.commit()
        conn.close()

        # Daemon should reclaim the stale state on startup
        daemon.start()
        daemon.wait_for_ready()
        daemon.shutdown()

        # Verify no running states remain
        conn = sqlite3.connect(str(brain.db_path))
        rows = conn.execute("SELECT regen_status FROM regen_locks WHERE knowledge_path = 'area'").fetchall()
        conn.close()
        assert all(r[0] != "running" for r in rows), "Stale running state not reclaimed"

        assert_brain_consistent(brain.root)


class TestReconcileWhileDaemonRunning:
    """Run reconcile CLI while daemon is actively processing."""

    def test_reconcile_while_daemon_running(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        seed_knowledge_tree(
            brain.root,
            {
                "knowledge/": {
                    "area/": {"doc.md": "# Doc\n\nContent."},
                },
            },
        )
        run_regen(cli, brain.root, "area")

        daemon.start()
        daemon.wait_for_ready()

        # Simulate an offline-style mutation while daemon is running
        import shutil

        shutil.move(
            str(brain.knowledge / "area"),
            str(brain.knowledge / "area-moved"),
        )

        # Run explicit reconcile CLI while daemon still active
        result = cli.run("reconcile", "--root", str(brain.root))
        assert result.returncode == 0
        assert "Traceback" not in result.stderr

        import time

        time.sleep(3)

        daemon.shutdown()
        assert_brain_consistent(brain.root)


class TestDoubleDaemonOwnership:
    """Two daemons against the same brain — second start is refused."""

    def test_second_daemon_is_refused(
        self,
        brain: BrainFixture,
        config_dir: Path,
        capture_dir: Path,
    ):
        d1 = DaemonProcess(brain.root, config_dir, capture_dir)
        d2 = DaemonProcess(brain.root, config_dir, capture_dir)
        try:
            d1.start()
            d1.wait_for_ready()

            # Start second daemon — should fail closed at startup.
            d2.start()
            import time

            time.sleep(3)
            assert not d2.is_running()
            assert "already running" in d2.stderr_text.lower()
        finally:
            d2.shutdown()
            d1.shutdown()

        assert_brain_consistent(brain.root)

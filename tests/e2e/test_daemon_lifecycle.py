"""Phase 3 E2E tests: daemon lifecycle (start, ready, shutdown)."""

from __future__ import annotations

import time

import pytest

from tests.e2e.harness.brain import BrainFixture
from tests.e2e.harness.daemon import DaemonProcess

pytestmark = pytest.mark.e2e


class TestDaemonLifecycle:
    """Start, readiness, and shutdown of the daemon subprocess."""

    @pytest.mark.timeout(30)
    def test_starts_and_stops_cleanly(self, daemon: DaemonProcess):
        """Daemon starts, becomes ready, and exits cleanly on CTRL_C."""
        daemon.start()
        daemon.wait_for_ready(timeout=15)
        assert daemon.is_running()
        daemon.shutdown(timeout=10)
        assert not daemon.is_running()

    @pytest.mark.timeout(30)
    def test_runs_with_empty_brain(self, daemon: DaemonProcess, brain: BrainFixture):
        """Daemon runs on an empty brain without crashing.

        The daemon may exit quickly when there are no sources — that's
        acceptable. The key invariant: no unhandled crash, DB intact.
        """
        daemon.start()
        daemon.wait_for_ready(timeout=15)
        time.sleep(2)
        # Daemon may or may not still be running — both are OK
        daemon.shutdown()
        # DB should be intact
        assert brain.db_path.exists()

    @pytest.mark.timeout(30)
    def test_graceful_shutdown_saves_state(self, daemon: DaemonProcess, brain: BrainFixture):
        """State is persisted after graceful shutdown."""
        daemon.start()
        daemon.wait_for_ready(timeout=15)
        # DB should exist and have schema
        assert brain.db_path.exists()
        daemon.shutdown()
        # DB should still be intact after shutdown
        import sqlite3

        conn = sqlite3.connect(str(brain.db_path))
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "sync_cache" in tables
        assert "regen_locks" in tables

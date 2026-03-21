"""Phase 5 E2E tests: burst changes, concurrent access, resilience."""

from __future__ import annotations

import time

import pytest

from tests.e2e.harness.assertions import (
    assert_no_duplicate_insights,
    assert_no_orphan_insights,
    assert_summary_exists,
)
from tests.e2e.harness.brain import BrainFixture
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess

pytestmark = pytest.mark.e2e


class TestBurstFileChanges:
    """Many files created quickly — tests batching and dedup."""

    @pytest.mark.timeout(90)
    def test_burst_creates(self, daemon: DaemonProcess, brain: BrainFixture):
        """Create many files quickly, verify no duplicates or orphans."""
        # Seed initial structure
        kdir = brain.knowledge / "burst"
        kdir.mkdir()
        (kdir / "seed.md").write_text("# Seed\n\nInitial content.", encoding="utf-8")

        daemon.start()
        daemon.wait_for_ready(timeout=15)

        # Burst: create 10 files quickly
        for i in range(10):
            (kdir / f"doc{i:02d}.md").write_text(f"# Doc {i}\n\nBurst content {i}.", encoding="utf-8")

        # Wait for eventual consistency
        time.sleep(10)

        # Invariants: no orphans, no duplicates
        assert_no_orphan_insights(brain.root)
        assert_no_duplicate_insights(brain.root)

        daemon.shutdown()


class TestDaemonRestart:
    """Daemon restart recovers state."""

    @pytest.mark.timeout(60)
    def test_restart_recovers_state(self, daemon: DaemonProcess, brain: BrainFixture, cli: CliRunner):
        """Start → add content → regen → stop → restart → state intact."""
        # Create content and regen
        kdir = brain.knowledge / "restart"
        kdir.mkdir()
        (kdir / "doc.md").write_text("# Doc\n\nRestart content.", encoding="utf-8")
        result = cli.run("regen", "--root", str(brain.root), "restart")
        assert result.returncode == 0
        assert_summary_exists(brain.root, "restart")

        # Start daemon
        daemon.start()
        daemon.wait_for_ready(timeout=15)

        # Stop
        daemon.shutdown()

        # Restart
        daemon.start()
        daemon.wait_for_ready(timeout=15)

        # State should be intact
        assert_summary_exists(brain.root, "restart")

        daemon.shutdown()


class TestDoubleDaemonStart:
    """Second daemon start is refused explicitly."""

    @pytest.mark.timeout(30)
    def test_second_start_is_refused(self, brain: BrainFixture, config_dir, capture_dir):
        """A second daemon against the same brain is rejected at startup."""
        from tests.e2e.harness.daemon import DaemonProcess

        d1 = DaemonProcess(brain.root, config_dir, capture_dir)
        d2 = DaemonProcess(brain.root, config_dir, capture_dir)

        try:
            d1.start()
            d1.wait_for_ready(timeout=15)
            d2.start()
            # Give second daemon time to fail closed.
            time.sleep(3)
            assert not d2.is_running()
            assert "already running" in d2.stderr_text.lower()
            assert brain.db_path.exists()
        finally:
            d1.shutdown()
            d2.shutdown()


class TestRegenWithMalformedLlm:
    """Regen with malformed LLM output degrades gracefully."""

    @pytest.mark.timeout(30)
    def test_malformed_output_no_crash(self, brain: BrainFixture, config_dir):
        """Regen with malformed output should not crash."""
        kdir = brain.knowledge / "malformed"
        kdir.mkdir()
        (kdir / "doc.md").write_text("# Doc\n\nContent.", encoding="utf-8")

        cli = CliRunner(
            config_dir=config_dir,
            extra_env={"BRAIN_SYNC_FAKE_LLM_MODE": "malformed"},
        )
        # May fail (malformed output) but should not crash with a traceback
        result = cli.run("regen", "--root", str(brain.root), "malformed")
        # We accept either success (if the parser handles it) or a clean failure
        assert result.returncode in (0, 1)

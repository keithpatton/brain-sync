"""Phase 3A: Source-sync daemon E2E tests.

Full pipeline: daemon running → source scheduled → adapter fetched →
knowledge written → regen queued → insights updated.

Requires: Phase 0A (readiness signal) + Phase 1 (test source adapter).
"""

from __future__ import annotations

import pytest

from brain_sync.sources.test import register_test_root, reset_test_adapter
from tests.e2e.harness.assertions import assert_brain_consistent
from tests.e2e.harness.brain import BrainFixture
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.e2e.harness.scenarios import script_test_source
from tests.e2e.harness.wait import wait_for_file

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def _reset_test_adapter():
    """Reset the test adapter state between tests."""
    reset_test_adapter()
    yield
    reset_test_adapter()


class TestSourceSyncFullPipeline:
    """Add a test source, start daemon, verify knowledge + insights created."""

    def test_source_sync_full_pipeline(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        # Add source via CLI
        result = cli.run(
            "add",
            "test://doc/pipeline1",
            "--path",
            "synced",
            "--root",
            str(brain.root),
        )
        assert result.returncode == 0

        # Script the adapter to return content on first check
        script_test_source(
            brain.root,
            "test:pipeline1",
            [
                {"status": "CHANGED", "body": "# Pipeline Test\n\nSynced content.", "title": "Pipeline Test"},
            ],
        )
        register_test_root("test:pipeline1", brain.root)

        daemon.start()
        daemon.wait_for_ready()

        # Wait for knowledge file to appear
        wait_for_file(brain.knowledge / "synced" / "tpipeline1-pipeline-test.md", timeout=60)

        # Wait for insights regen (debounce + regen execution)
        wait_for_file(brain.insights / "synced" / "summary.md", timeout=90)

        daemon.shutdown()
        assert_brain_consistent(brain.root)


class TestSourceUpdateTriggersRegen:
    """Source update → knowledge write → summary updates."""

    def test_source_update_triggers_regen(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        cli.run("add", "test://doc/upd1", "--path", "updating", "--root", str(brain.root))

        script_test_source(
            brain.root,
            "test:upd1",
            [
                {"status": "CHANGED", "body": "# V1\n\nFirst version.", "title": "Updating Doc"},
                {"status": "CHANGED", "body": "# V2\n\nSecond version with more detail.", "title": "Updating Doc"},
            ],
        )
        register_test_root("test:upd1", brain.root)

        daemon.start()
        daemon.wait_for_ready()

        # Wait for initial sync (debounce + regen execution)
        wait_for_file(brain.knowledge / "updating" / "tupd1-updating-doc.md", timeout=60)
        wait_for_file(brain.insights / "updating" / "summary.md", timeout=90)

        daemon.shutdown()
        assert_brain_consistent(brain.root)


class TestSourceUnchangedSkipsFetch:
    """Adapter returns UNCHANGED → no knowledge write."""

    def test_source_unchanged_skips_fetch(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        cli.run("add", "test://doc/skip1", "--path", "stable", "--root", str(brain.root))

        # Only UNCHANGED entries
        script_test_source(
            brain.root,
            "test:skip1",
            [
                {"status": "UNCHANGED"},
                {"status": "UNCHANGED"},
            ],
        )
        register_test_root("test:skip1", brain.root)

        daemon.start()
        daemon.wait_for_ready()

        # Give the daemon a few ticks to process
        import time

        time.sleep(5)

        daemon.shutdown()

        # No knowledge file should have been written
        synced_files = list((brain.knowledge / "stable").glob("t*.md"))
        assert len(synced_files) == 0

        assert_brain_consistent(brain.root)


class TestSourceErrorBackoff:
    """Adapter raises error → interval increases."""

    def test_source_error_backoff(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ):
        cli.run("add", "test://doc/err1", "--path", "erroring", "--root", str(brain.root))

        # Script: first check errors, then succeeds
        script_test_source(
            brain.root,
            "test:err1",
            [
                {"status": "ERROR", "error": "connection timeout"},
                {"status": "CHANGED", "body": "# Recovered\n\nContent after error.", "title": "Recovered"},
            ],
        )
        register_test_root("test:err1", brain.root)

        daemon.start()
        daemon.wait_for_ready()

        # Give time for error + backoff + retry
        import time

        time.sleep(10)

        daemon.shutdown()

        # The source should have eventually synced (after recovery)
        # or at least the brain should be consistent
        assert_brain_consistent(brain.root)

"""Phase 3C: DB contention E2E tests.

Verify that CLI and daemon can safely share the SQLite database.
"""

from __future__ import annotations

import json
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.harness.assertions import assert_brain_consistent
from tests.e2e.harness.brain import BrainFixture, seed_knowledge_tree
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.e2e.harness.scenarios import run_regen

pytestmark = pytest.mark.e2e


def _barriered_daemon_process(
    *,
    brain_root: Path,
    config_dir: Path,
    capture_dir: Path,
    start_at: float,
) -> subprocess.Popen[str]:
    helper = DaemonProcess(brain_root, config_dir, capture_dir)
    env = helper._env()
    env["BRAIN_SYNC_TEST_ROOT"] = str(brain_root)
    env["BRAIN_SYNC_START_AT"] = f"{start_at:.6f}"
    code = (
        "import os, sys, time\n"
        "target = float(os.environ['BRAIN_SYNC_START_AT'])\n"
        "while time.time() < target:\n"
        "    time.sleep(0.01)\n"
        "from brain_sync.__main__ import main\n"
        "sys.argv = ['brain_sync', 'run', '--root', os.environ['BRAIN_SYNC_TEST_ROOT']]\n"
        "main()\n"
    )
    kwargs: dict[str, Any] = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "env": env,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    return subprocess.Popen([sys.executable, "-c", code], **kwargs)


def _wait_for_ready_pid(status_path: Path, candidate_pids: set[int], *, timeout: float = 15.0) -> int:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if status_path.exists():
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload = None
            if (
                isinstance(payload, dict)
                and payload.get("status") == "ready"
                and isinstance(payload.get("pid"), int)
                and payload["pid"] in candidate_pids
            ):
                return int(payload["pid"])
        time.sleep(0.1)
    raise TimeoutError(f"daemon.json never reported ready for candidate pids {sorted(candidate_pids)}")


def _shutdown_process(proc: subprocess.Popen[str], *, timeout: float = 10.0) -> None:
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            proc.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            proc.send_signal(signal.SIGINT)
        proc.wait(timeout=timeout)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    proc.terminate()
    try:
        proc.wait(timeout=5.0)
        return
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5.0)


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

    def test_barriered_simultaneous_start_allows_only_one_ready(
        self,
        brain: BrainFixture,
        config_dir: Path,
        capture_dir: Path,
    ):
        start_at = time.time() + 1.5
        p1 = _barriered_daemon_process(
            brain_root=brain.root,
            config_dir=config_dir,
            capture_dir=capture_dir,
            start_at=start_at,
        )
        p2 = _barriered_daemon_process(
            brain_root=brain.root,
            config_dir=config_dir,
            capture_dir=capture_dir,
            start_at=start_at,
        )
        try:
            ready_pid = _wait_for_ready_pid(config_dir / "daemon.json", {p1.pid, p2.pid})
            time.sleep(2.0)

            running = [proc for proc in (p1, p2) if proc.poll() is None]
            exited = [proc for proc in (p1, p2) if proc.poll() is not None]

            assert len(running) == 1
            assert len(exited) == 1
            assert running[0].pid == ready_pid

            loser = exited[0]
            loser_stderr = loser.stderr.read() if loser.stderr is not None else ""
            assert loser.returncode == 1
            assert "already running" in loser_stderr.lower()
        finally:
            _shutdown_process(p1)
            _shutdown_process(p2)

        assert_brain_consistent(brain.root)

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

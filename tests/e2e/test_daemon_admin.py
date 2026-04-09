from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.e2e.harness.brain import BrainFixture
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess

pytestmark = pytest.mark.e2e


def _stderr_messages(result) -> list[str]:
    messages: list[str] = []
    for raw_line in result.stderr.splitlines():
        if not raw_line.strip():
            continue
        _prefix, separator, payload = raw_line.partition(": ")
        message = payload if separator else raw_line
        if message.startswith("Logging initialised, run_id="):
            continue
        messages.append(message)
    return messages


def _wait_for_state(
    config_dir: Path,
    *,
    state: str,
    timeout: float = 15.0,
    pid_not: int | None = None,
) -> dict:
    deadline = time.monotonic() + timeout
    status_path = config_dir / "daemon.json"
    while time.monotonic() < deadline:
        if status_path.exists():
            try:
                payload = json.loads(status_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                payload = None
            if (
                isinstance(payload, dict)
                and payload.get("status") == state
                and (pid_not is None or payload.get("pid") != pid_not)
            ):
                return payload
        time.sleep(0.1)
    raise TimeoutError(f"daemon.json never reached state={state!r}")


class TestDaemonAdminE2E:
    def test_launcher_background_daemon_is_adopted_and_start_is_idempotent(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        config_dir: Path,
    ) -> None:
        assert cli.run("init", str(brain.root)).returncode == 0

        try:
            first_start = cli.run("start")
            assert first_start.returncode == 0, first_start.stderr
            ready = _wait_for_state(config_dir, state="ready")

            status_result = cli.run("status")
            second_start = cli.run("start")

            assert status_result.returncode == 0, status_result.stderr
            status_messages = _stderr_messages(status_result)
            assert "Daemon: running" in status_messages
            assert "  Controller kind: launcher-background" in status_messages
            assert any(message == f"  PID: {ready['pid']}" for message in status_messages)

            assert second_start.returncode == 0, second_start.stderr
            second_messages = _stderr_messages(second_start)
            assert "Result: already_running" in second_messages
            assert "  Controller kind: launcher-background" in second_messages
            assert any(message == f"  PID: {ready['pid']}" for message in second_messages)
        finally:
            cli.run("stop")

    def test_launcher_background_stop_and_restart_work_across_processes(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        config_dir: Path,
    ) -> None:
        assert cli.run("init", str(brain.root)).returncode == 0

        try:
            assert cli.run("start").returncode == 0
            first_ready = _wait_for_state(config_dir, state="ready")

            stop_result = cli.run("stop")
            assert stop_result.returncode == 0, stop_result.stderr
            stopped = _wait_for_state(config_dir, state="stopped")
            assert stopped["pid"] == first_ready["pid"]

            restart_result = cli.run("restart")
            assert restart_result.returncode == 0, restart_result.stderr
            second_ready = _wait_for_state(config_dir, state="ready", pid_not=first_ready["pid"])
            assert second_ready["controller_kind"] == "launcher-background"
            assert second_ready["pid"] != first_ready["pid"]
        finally:
            cli.run("stop")

    def test_terminal_foreground_daemon_is_adoptable_but_not_remotely_controllable(
        self,
        brain: BrainFixture,
        cli: CliRunner,
        daemon: DaemonProcess,
    ) -> None:
        assert cli.run("init", str(brain.root)).returncode == 0

        daemon.start()
        daemon.wait_for_ready()

        status_result = cli.run("status")
        start_result = cli.run("start")
        stop_result = cli.run("stop")
        restart_result = cli.run("restart")

        assert status_result.returncode == 0, status_result.stderr
        status_messages = _stderr_messages(status_result)
        assert "Daemon: running" in status_messages
        assert "  Controller kind: terminal-foreground" in status_messages

        assert start_result.returncode == 0, start_result.stderr
        start_messages = _stderr_messages(start_result)
        assert "Result: already_running" in start_messages
        assert "  Controller kind: terminal-foreground" in start_messages

        assert stop_result.returncode == 1, stop_result.stderr
        assert "Result: unsupported_for_controller_kind" in stop_result.stderr

        assert restart_result.returncode == 1, restart_result.stderr
        assert "Result: unsupported_for_controller_kind" in restart_result.stderr

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from brain_sync.runtime.repository import is_pid_running
from tests.e2e.harness.cli import CliRunner

pytestmark = pytest.mark.system


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


def _wait_for_daemon_status(
    config_dir: Path,
    *,
    status: str,
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
                and payload.get("status") == status
                and (pid_not is None or payload.get("pid") != pid_not)
            ):
                return payload
        time.sleep(0.1)
    raise TimeoutError(f"daemon.json never reached {status!r} status")


class TestDaemonAdminCli:
    def test_start_without_active_root_reports_setup_required(self, cli: CliRunner) -> None:
        result = cli.run("start")

        assert result.returncode == 1
        assert "Result: setup_required" in result.stderr
        assert "usable active brain root must be attached" in result.stderr

    def test_attach_root_rewrites_active_root_order(self, cli: CliRunner, tmp_path: Path, config_dir: Path) -> None:
        root_one = tmp_path / "brain-one"
        root_two = tmp_path / "brain-two"

        assert cli.run("init", str(root_one)).returncode == 0
        assert cli.run("init", str(root_two)).returncode == 0

        result = cli.run("attach-root", str(root_one))

        assert result.returncode == 0, result.stderr
        config = json.loads((config_dir / "config.json").read_text(encoding="utf-8"))
        assert config["brains"][0] == str(root_one.resolve())
        assert config["brains"][1] == str(root_two.resolve())

    def test_status_reports_launcher_background_daemon(
        self, cli: CliRunner, brain_root: Path, config_dir: Path
    ) -> None:
        assert cli.run("init", str(brain_root)).returncode == 0

        try:
            start_result = cli.run("start")
            assert start_result.returncode == 0, start_result.stderr
            ready = _wait_for_daemon_status(config_dir, status="ready")

            status_result = cli.run("status")

            assert status_result.returncode == 0, status_result.stderr
            messages = _stderr_messages(status_result)
            assert "Setup: ready" in messages
            assert "Daemon: running" in messages
            assert "  Controller kind: launcher-background" in messages
            assert any(message.startswith("  PID: ") for message in messages)
            assert any(message.startswith("  Started at: ") for message in messages)
            assert ready["controller_kind"] == "launcher-background"
        finally:
            cli.run("stop")

    def test_stop_stops_launcher_background_daemon(self, cli: CliRunner, brain_root: Path, config_dir: Path) -> None:
        assert cli.run("init", str(brain_root)).returncode == 0

        assert cli.run("start").returncode == 0
        ready = _wait_for_daemon_status(config_dir, status="ready")

        stop_result = cli.run("stop")

        assert stop_result.returncode == 0, stop_result.stderr
        messages = _stderr_messages(stop_result)
        assert "Result: stopped" in messages
        stopped = _wait_for_daemon_status(config_dir, status="stopped")
        assert stopped["pid"] == ready["pid"]

    def test_restart_replaces_launcher_background_daemon_pid(
        self,
        cli: CliRunner,
        brain_root: Path,
        config_dir: Path,
    ) -> None:
        assert cli.run("init", str(brain_root)).returncode == 0

        try:
            assert cli.run("start").returncode == 0
            first_ready = _wait_for_daemon_status(config_dir, status="ready")

            restart_result = cli.run("restart")
            assert restart_result.returncode == 0, restart_result.stderr

            second_ready = _wait_for_daemon_status(config_dir, status="ready", pid_not=first_ready["pid"])
            assert second_ready["pid"] != first_ready["pid"]
            assert second_ready["controller_kind"] == "launcher-background"
        finally:
            cli.run("stop")

    def test_stop_does_not_kill_stale_root_mismatch_launcher_background(
        self,
        cli: CliRunner,
        tmp_path: Path,
        config_dir: Path,
    ) -> None:
        running_root = tmp_path / "brain-running"
        active_root = tmp_path / "brain-active"

        assert cli.run("init", str(running_root)).returncode == 0
        assert cli.run("init", str(active_root)).returncode == 0
        assert cli.run("attach-root", str(running_root)).returncode == 0

        try:
            assert cli.run("start").returncode == 0
            ready = _wait_for_daemon_status(config_dir, status="ready")
            assert cli.run("attach-root", str(active_root)).returncode == 0

            stop_result = cli.run("stop")

            assert stop_result.returncode == 0, stop_result.stderr
            messages = _stderr_messages(stop_result)
            assert "Result: not_running" in messages
            assert "  Daemon: stale" in messages
            assert "  Reason: root_mismatch" in messages
            assert is_pid_running(int(ready["pid"])) is True

            status_result = cli.run("status")
            assert status_result.returncode == 0, status_result.stderr
            status_messages = _stderr_messages(status_result)
            assert "Daemon: stale" in status_messages
            assert "  Reason: root_mismatch" in status_messages
            assert any(message == f"  PID: {ready['pid']}" for message in status_messages)
        finally:
            cli.run("attach-root", str(running_root))
            cli.run("stop")

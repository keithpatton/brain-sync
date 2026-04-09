from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.launcher import (
    LAUNCHER_BACKGROUND_CONTROLLER,
    TERMINAL_FOREGROUND_CONTROLLER,
    DaemonStatus,
    RuntimeStatus,
    _background_creation_kwargs,
    get_runtime_status,
    restart_daemon,
    start_daemon,
    stop_daemon,
)
from brain_sync.application.roots import SetupStatus, attach_root, get_setup_status
from brain_sync.runtime.repository import DaemonGuardStatus, daemon_root_id

pytestmark = pytest.mark.unit


def _guard(*, refused: bool, pid: int = 1234, root: str | None = None) -> DaemonGuardStatus:
    return DaemonGuardStatus(
        lock_path=Path("/tmp/daemon.lock"),
        lock_present=True,
        competing_start_refused=refused,
        pid=pid,
        daemon_id="daemon:1234:test",
        brain_root=root,
    )


def _ready_setup(root: Path) -> SetupStatus:
    resolved = root.resolve()
    return SetupStatus(
        configured_active_root=resolved,
        usable_active_root=resolved,
        registered_roots=(resolved,),
        reason=None,
        message="Active brain root is ready.",
    )


def _daemon_status(
    *,
    root: Path,
    state: str,
    snapshot_status: str | None = None,
    controller_kind: str | None = None,
    pid: int | None = None,
    daemon_root: str | None = None,
    healthy: bool = False,
    competing_start_refused: bool = False,
    reason: str | None = None,
) -> DaemonStatus:
    return DaemonStatus(
        state=state,
        snapshot_status=snapshot_status,
        controller_kind=controller_kind,
        pid=pid,
        daemon_id="daemon:4321:test" if pid is not None else None,
        daemon_root=daemon_root,
        active_root=root.resolve(),
        started_at="2026-04-09T00:00:00+00:00" if pid is not None else None,
        updated_at="2026-04-09T00:00:01+00:00" if pid is not None else None,
        stopped_at=None,
        healthy=healthy,
        adoptable=healthy,
        competing_start_refused=competing_start_refused,
        stop_supported=healthy and controller_kind == LAUNCHER_BACKGROUND_CONTROLLER,
        restart_supported=healthy and controller_kind == LAUNCHER_BACKGROUND_CONTROLLER,
        reason=reason,
    )


def test_attach_root_rewrites_active_root_priority_and_preserves_other_roots(tmp_path: Path) -> None:
    root_one = tmp_path / "brain-one"
    root_two = tmp_path / "brain-two"

    init_brain(root_one)
    init_brain(root_two)

    result = attach_root(root_one)
    setup = get_setup_status()

    assert result.root == root_one.resolve()
    assert setup.ready is True
    assert setup.usable_active_root == root_one.resolve()
    assert setup.registered_roots == (root_one.resolve(), root_two.resolve())


def test_setup_status_reports_invalid_active_root(tmp_path: Path) -> None:
    from brain_sync.runtime.config import save_config

    missing_root = tmp_path / "missing-brain"
    save_config({"brains": [str(missing_root)]})

    status = get_setup_status()

    assert status.ready is False
    assert status.reason == "invalid_active_root"
    assert status.configured_active_root == missing_root
    assert status.usable_active_root is None


def test_runtime_status_classifies_healthy_launcher_background_daemon(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    init_brain(root)
    root_id = daemon_root_id(root.resolve())

    with (
        patch(
            "brain_sync.application.launcher.read_daemon_status",
            return_value={
                "pid": 1234,
                "status": "ready",
                "daemon_id": "daemon:1234:test",
                "brain_root": root_id,
                "controller_kind": LAUNCHER_BACKGROUND_CONTROLLER,
                "started_at": "2026-04-09T00:00:00+00:00",
                "updated_at": "2026-04-09T00:00:01+00:00",
            },
        ),
        patch(
            "brain_sync.application.launcher.inspect_daemon_start_guard",
            return_value=_guard(refused=True, root=root_id),
        ),
        patch("brain_sync.application.launcher.is_pid_running", return_value=True),
        patch("brain_sync.application.launcher.build_status_summary", return_value=None),
    ):
        daemon = get_runtime_status().daemon

    assert daemon.state == "running"
    assert daemon.healthy is True
    assert daemon.adoptable is True
    assert daemon.controller_kind == LAUNCHER_BACKGROUND_CONTROLLER
    assert daemon.stop_supported is True
    assert daemon.restart_supported is True


def test_terminal_foreground_daemon_is_adoptable_but_not_remotely_controllable(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    init_brain(root)
    root_id = daemon_root_id(root.resolve())

    with (
        patch(
            "brain_sync.application.launcher.read_daemon_status",
            return_value={
                "pid": 1234,
                "status": "ready",
                "daemon_id": "daemon:1234:test",
                "brain_root": root_id,
                "controller_kind": TERMINAL_FOREGROUND_CONTROLLER,
                "started_at": "2026-04-09T00:00:00+00:00",
                "updated_at": "2026-04-09T00:00:01+00:00",
            },
        ),
        patch(
            "brain_sync.application.launcher.inspect_daemon_start_guard",
            return_value=_guard(refused=True, root=root_id),
        ),
        patch("brain_sync.application.launcher.is_pid_running", return_value=True),
        patch("brain_sync.application.launcher.build_status_summary", return_value=None),
    ):
        daemon = get_runtime_status().daemon
        stop_result = stop_daemon()
        restart_result = restart_daemon()

    assert daemon.state == "running"
    assert daemon.adoptable is True
    assert daemon.stop_supported is False
    assert stop_result.result == "unsupported_for_controller_kind"
    assert restart_result.result == "unsupported_for_controller_kind"


def test_background_creation_kwargs_hide_windows_console() -> None:
    with (
        patch("brain_sync.application.launcher.os.name", "nt"),
        patch(
            "brain_sync.application.launcher.windows_hidden_process_kwargs",
            return_value={"creationflags": 123, "startupinfo": "hidden"},
        ) as hidden_kwargs,
    ):
        kwargs = _background_creation_kwargs()

    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["close_fds"] is True
    assert kwargs["creationflags"] == 123
    assert kwargs["startupinfo"] == "hidden"
    hidden_kwargs.assert_called_once()


def test_background_creation_kwargs_preserve_posix_session_behavior() -> None:
    with patch("brain_sync.application.launcher.os.name", "posix"):
        kwargs = _background_creation_kwargs()

    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL
    assert kwargs["close_fds"] is True
    assert kwargs["start_new_session"] is True
    assert "creationflags" not in kwargs


def test_runtime_status_does_not_promote_snapshot_missing_pid(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    init_brain(root)
    root_id = daemon_root_id(root.resolve())

    with (
        patch(
            "brain_sync.application.launcher.read_daemon_status",
            return_value={
                "status": "ready",
                "daemon_id": "daemon:1234:test",
                "brain_root": root_id,
                "controller_kind": LAUNCHER_BACKGROUND_CONTROLLER,
                "started_at": "2026-04-09T00:00:00+00:00",
                "updated_at": "2026-04-09T00:00:01+00:00",
            },
        ),
        patch(
            "brain_sync.application.launcher.inspect_daemon_start_guard",
            return_value=_guard(refused=True, pid=4321, root=root_id),
        ),
        patch("brain_sync.application.launcher.is_pid_running", return_value=True),
        patch("brain_sync.application.launcher.build_status_summary", return_value=None),
    ):
        daemon = get_runtime_status().daemon

    assert daemon.state == "stale"
    assert daemon.healthy is False
    assert daemon.adoptable is False
    assert daemon.pid == 4321
    assert daemon.reason == "snapshot_missing_pid"
    assert daemon.stop_supported is False
    assert daemon.restart_supported is False


def test_stale_root_mismatch_launcher_background_is_not_remotely_controllable(tmp_path: Path) -> None:
    running_root = tmp_path / "brain-running"
    active_root = tmp_path / "brain-active"
    init_brain(running_root)
    init_brain(active_root)
    attach_root(active_root)
    running_root_id = daemon_root_id(running_root.resolve())

    with (
        patch(
            "brain_sync.application.launcher.read_daemon_status",
            return_value={
                "pid": 1234,
                "status": "ready",
                "daemon_id": "daemon:1234:test",
                "brain_root": running_root_id,
                "controller_kind": LAUNCHER_BACKGROUND_CONTROLLER,
                "started_at": "2026-04-09T00:00:00+00:00",
                "updated_at": "2026-04-09T00:00:01+00:00",
            },
        ),
        patch(
            "brain_sync.application.launcher.inspect_daemon_start_guard",
            return_value=_guard(refused=True, root=running_root_id),
        ),
        patch("brain_sync.application.launcher.is_pid_running", return_value=True),
        patch("brain_sync.application.launcher.build_status_summary", return_value=None),
        patch("brain_sync.application.launcher._start_new_background") as start_new_background,
    ):
        daemon = get_runtime_status().daemon
        start_result = start_daemon()
        stop_result = stop_daemon()
        restart_result = restart_daemon()

    assert daemon.state == "stale"
    assert daemon.reason == "root_mismatch"
    assert daemon.stop_supported is False
    assert daemon.restart_supported is False
    assert start_result.result == "stale"
    assert stop_result.result == "not_running"
    assert restart_result.result == "stale"
    start_new_background.assert_not_called()


def test_start_daemon_fails_closed_when_post_start_daemon_is_stale(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    init_brain(root)
    setup = _ready_setup(root)
    initial_status = RuntimeStatus(
        setup=setup,
        daemon=_daemon_status(root=root, state="not_running", reason="not_running"),
        content=None,
    )
    stale_status = _daemon_status(
        root=root,
        state="stale",
        snapshot_status="ready",
        controller_kind=LAUNCHER_BACKGROUND_CONTROLLER,
        pid=4321,
        daemon_root="other-root",
        healthy=False,
        competing_start_refused=True,
        reason="root_mismatch",
    )
    final_status = _daemon_status(root=root, state="not_running", reason="not_running")

    with (
        patch("brain_sync.application.launcher.get_runtime_status", return_value=initial_status),
        patch("brain_sync.application.launcher.get_setup_status", return_value=setup),
        patch("brain_sync.application.launcher.subprocess.Popen", return_value=SimpleNamespace(pid=4321)),
        patch("brain_sync.application.launcher._wait_for_background_start", return_value=True),
        patch(
            "brain_sync.application.launcher._classify_daemon_status",
            side_effect=[stale_status, final_status],
        ),
        patch("brain_sync.application.launcher.is_pid_running", return_value=True),
        patch("brain_sync.application.launcher._terminate_process") as terminate_process,
        patch("brain_sync.application.launcher._wait_for_pid_exit", return_value=True) as wait_for_pid_exit,
    ):
        result = start_daemon()

    assert result.result == "start_failed"
    assert result.daemon.state == "not_running"
    assert (
        result.message
        == "Launcher-background daemon did not reach a healthy running state for the current active root."
    )
    terminate_process.assert_called_once_with(4321)
    wait_for_pid_exit.assert_called_once_with(4321)

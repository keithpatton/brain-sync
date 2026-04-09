"""Shared bootstrap, status, and daemon-admin workflows for CLI and MCP."""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import sysconfig
import time
from dataclasses import dataclass
from pathlib import Path

from brain_sync.application.roots import SetupStatus, get_setup_status
from brain_sync.application.status import StatusSummary, build_status_summary
from brain_sync.runtime.repository import (
    daemon_root_id,
    inspect_daemon_start_guard,
    is_pid_running,
    read_daemon_status,
    write_daemon_status,
)
from brain_sync.util.processes import windows_hidden_process_kwargs

log = logging.getLogger(__name__)

TERMINAL_FOREGROUND_CONTROLLER = "terminal-foreground"
LAUNCHER_BACKGROUND_CONTROLLER = "launcher-background"
UNKNOWN_CONTROLLER = "unknown"
_RUNNING_SNAPSHOT_STATUSES = frozenset({"starting", "ready"})


@dataclass(frozen=True)
class DaemonStatus:
    """Daemon health/adoption view for the current runtime config directory."""

    state: str
    snapshot_status: str | None
    controller_kind: str | None
    pid: int | None
    daemon_id: str | None
    daemon_root: str | None
    active_root: Path | None
    started_at: str | None
    updated_at: str | None
    stopped_at: str | None
    healthy: bool
    adoptable: bool
    competing_start_refused: bool
    stop_supported: bool
    restart_supported: bool
    reason: str | None


@dataclass(frozen=True)
class RuntimeStatus:
    """Combined setup and daemon/admin status for CLI and MCP surfaces."""

    setup: SetupStatus
    daemon: DaemonStatus
    content: StatusSummary | None


@dataclass(frozen=True)
class DaemonAdminResult:
    """Result of a start/stop/restart admin operation."""

    result: str
    daemon: DaemonStatus
    message: str | None = None
    adopted: bool = False


def _controller_kind(snapshot: dict | None) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    raw = snapshot.get("controller_kind")
    if raw in {
        TERMINAL_FOREGROUND_CONTROLLER,
        LAUNCHER_BACKGROUND_CONTROLLER,
        UNKNOWN_CONTROLLER,
    }:
        return raw
    if isinstance(raw, str) and raw.strip():
        return UNKNOWN_CONTROLLER
    return UNKNOWN_CONTROLLER


def _snapshot_running(snapshot_status: str | None) -> bool:
    return snapshot_status in _RUNNING_SNAPSHOT_STATUSES


def _snapshot_str(snapshot: dict | None, key: str) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get(key)
    return value if isinstance(value, str) else None


def _snapshot_int(snapshot: dict | None, key: str) -> int | None:
    if not isinstance(snapshot, dict):
        return None
    value = snapshot.get(key)
    return value if isinstance(value, int) else None


def _classify_daemon_status(setup: SetupStatus) -> DaemonStatus:
    snapshot = read_daemon_status()
    guard = inspect_daemon_start_guard()

    snapshot_status = _snapshot_str(snapshot, "status")
    snapshot_pid = _snapshot_int(snapshot, "pid")
    pid = snapshot_pid if snapshot_pid is not None else guard.pid
    pid_live = isinstance(snapshot_pid, int) and is_pid_running(snapshot_pid)

    active_root = setup.usable_active_root
    active_root_id = daemon_root_id(active_root) if active_root is not None else None
    daemon_root = _snapshot_str(snapshot, "brain_root")
    root_matches = active_root_id is not None and daemon_root == active_root_id
    guard_pid_matches = guard.pid is None or guard.pid == snapshot_pid
    guard_root_matches = guard.brain_root is None or guard.brain_root == daemon_root
    controller_kind = _controller_kind(snapshot)
    healthy = bool(
        isinstance(snapshot, dict)
        and _snapshot_running(snapshot_status)
        and isinstance(snapshot_pid, int)
        and pid_live
        and root_matches
        and guard.competing_start_refused
        and guard_pid_matches
        and guard_root_matches
    )

    if healthy:
        state = "running"
        reason = None
    elif snapshot_status == "stopped" and not guard.competing_start_refused and not pid_live:
        state = "not_running"
        reason = "stopped"
    elif snapshot is None and not guard.competing_start_refused:
        state = "not_running"
        reason = "not_running"
    elif not pid_live and not guard.competing_start_refused:
        state = "not_running"
        reason = "not_running"
    else:
        state = "stale"
        if snapshot is None and guard.competing_start_refused:
            reason = "guard_locked_without_snapshot"
        elif not _snapshot_running(snapshot_status):
            reason = "snapshot_not_running"
        elif snapshot_pid is None:
            reason = "snapshot_missing_pid"
        elif not pid_live:
            reason = "pid_not_running"
        elif daemon_root is None:
            reason = "snapshot_missing_root"
        elif not root_matches:
            reason = "root_mismatch"
        elif not guard.competing_start_refused:
            reason = "guard_not_locked"
        elif guard.pid is not None and guard.pid != snapshot_pid:
            reason = "guard_pid_mismatch"
        elif guard.brain_root is not None and guard.brain_root != daemon_root:
            reason = "guard_root_mismatch"
        else:
            reason = "unhealthy"

    remotely_controllable = bool(controller_kind == LAUNCHER_BACKGROUND_CONTROLLER and healthy)
    return DaemonStatus(
        state=state,
        snapshot_status=snapshot_status,
        controller_kind=controller_kind,
        pid=pid,
        daemon_id=_snapshot_str(snapshot, "daemon_id"),
        daemon_root=daemon_root,
        active_root=active_root,
        started_at=_snapshot_str(snapshot, "started_at"),
        updated_at=_snapshot_str(snapshot, "updated_at"),
        stopped_at=_snapshot_str(snapshot, "stopped_at"),
        healthy=healthy,
        adoptable=healthy,
        competing_start_refused=guard.competing_start_refused,
        stop_supported=remotely_controllable,
        restart_supported=remotely_controllable,
        reason=reason,
    )


def get_runtime_status() -> RuntimeStatus:
    """Return shared runtime/bootstrap status for the current config directory."""
    setup = get_setup_status()
    daemon = _classify_daemon_status(setup)

    content: StatusSummary | None = None
    if setup.ready and setup.usable_active_root is not None:
        try:
            content = build_status_summary(setup.usable_active_root)
        except Exception:
            log.warning("Failed to build content status summary", exc_info=True)

    return RuntimeStatus(setup=setup, daemon=daemon, content=content)


def _background_env() -> dict[str, str]:
    env = dict(os.environ)
    env["BRAIN_SYNC_DAEMON_CONTROLLER_KIND"] = LAUNCHER_BACKGROUND_CONTROLLER
    return env


def _background_creation_kwargs() -> dict:
    kwargs: dict = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        creationflags = 0
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "DETACHED_PROCESS", 0)
        kwargs.update(windows_hidden_process_kwargs(creationflags=creationflags))
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _brain_sync_background_command() -> list[str]:
    """Return the preferred daemon launch command for this Python environment.

    Prefer the installed `brain-sync` console-script wrapper so process lists
    show a more useful executable name. Fall back to the module invocation to
    preserve compatibility if the wrapper is unavailable.
    """

    scripts_dir = sysconfig.get_path("scripts")
    candidate_dirs: list[Path] = []
    if scripts_dir:
        candidate_dirs.append(Path(scripts_dir))
    candidate_dirs.append(Path(sys.executable).resolve().parent)

    candidate_names = ["brain-sync.exe", "brain-sync"] if os.name == "nt" else ["brain-sync"]
    seen: set[Path] = set()
    for directory in candidate_dirs:
        for name in candidate_names:
            candidate = (directory / name).resolve(strict=False)
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.is_file():
                return [str(candidate)]

    return [sys.executable, "-m", "brain_sync"]


def _wait_for_pid_exit(pid: int, *, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_pid_running(pid):
            return True
        time.sleep(0.1)
    return not is_pid_running(pid)


def _wait_for_background_start(*, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = _classify_daemon_status(get_setup_status())
        if current.healthy and current.controller_kind == LAUNCHER_BACKGROUND_CONTROLLER:
            return True
        time.sleep(0.1)
    return False


def _wait_for_not_running_state(*, timeout: float = 2.0) -> DaemonStatus:
    deadline = time.monotonic() + timeout
    current = _classify_daemon_status(get_setup_status())
    while time.monotonic() < deadline:
        if current.state == "not_running":
            return current
        time.sleep(0.1)
        current = _classify_daemon_status(get_setup_status())
    return current


def _terminate_process(pid: int) -> None:
    if os.name == "nt":
        import ctypes

        PROCESS_TERMINATE = 0x0001
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0x00000000
        WAIT_TIMEOUT = 0x00000102
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid)
        if not handle:
            raise OSError(f"Could not open process {pid} for termination")
        try:
            if ctypes.windll.kernel32.TerminateProcess(handle, 1) == 0:
                raise OSError(f"Could not terminate process {pid}")
            wait_result = ctypes.windll.kernel32.WaitForSingleObject(handle, 10_000)
            if wait_result not in {WAIT_OBJECT_0, WAIT_TIMEOUT}:
                raise OSError(f"Unexpected wait result while stopping process {pid}: {wait_result}")
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        return

    os.kill(pid, signal.SIGINT)


def _record_stopped_snapshot(daemon: DaemonStatus) -> None:
    if daemon.daemon_id is None:
        return
    root = daemon.active_root
    if root is None and daemon.daemon_root:
        root = Path(daemon.daemon_root)
    if root is None:
        return
    write_daemon_status(
        root=root,
        pid=daemon.pid or 0,
        status="stopped",
        daemon_id=daemon.daemon_id,
        controller_kind=daemon.controller_kind,
    )


def _stop_launcher_background(daemon: DaemonStatus) -> DaemonAdminResult:
    if daemon.pid is None:
        return DaemonAdminResult(
            result="not_running",
            daemon=_classify_daemon_status(get_setup_status()),
            message="No live launcher-background daemon PID was available to stop.",
        )

    _terminate_process(daemon.pid)
    exited = _wait_for_pid_exit(daemon.pid)
    _record_stopped_snapshot(daemon)
    current = _wait_for_not_running_state()
    if current.state != "not_running":
        log.info(
            "Launcher-background daemon stop did not fully settle: state=%s reason=%s exited=%s",
            current.state,
            current.reason,
            exited,
        )
    return DaemonAdminResult(
        result="stopped",
        daemon=current,
        message="Stopped launcher-background daemon.",
    )


def _stale_control_blocked_result(action: str) -> DaemonAdminResult:
    current = _classify_daemon_status(get_setup_status())
    return DaemonAdminResult(
        result="stale",
        daemon=current,
        message=(
            "A live but stale daemon is still attached to this runtime config directory; "
            f"launcher v1 will not remotely {action} it."
        ),
    )


def _start_new_background(root: Path) -> DaemonAdminResult:
    cmd = [*_brain_sync_background_command(), "run", "--root", str(root)]
    proc = subprocess.Popen(
        cmd,
        cwd=str(root),
        env=_background_env(),
        **_background_creation_kwargs(),
    )
    started = _wait_for_background_start()
    current = _classify_daemon_status(get_setup_status())
    if started and current.healthy and current.controller_kind == LAUNCHER_BACKGROUND_CONTROLLER:
        return DaemonAdminResult(
            result="started",
            daemon=current,
            message="Started launcher-background daemon.",
        )
    if is_pid_running(proc.pid):
        _terminate_process(proc.pid)
        _wait_for_pid_exit(proc.pid)
        current = _classify_daemon_status(get_setup_status())
    return DaemonAdminResult(
        result="start_failed",
        daemon=current,
        message="Launcher-background daemon did not reach a healthy running state for the current active root.",
    )


def start_daemon() -> DaemonAdminResult:
    """Start or adopt the shared daemon for the active runtime root."""
    status = get_runtime_status()
    if not status.setup.ready or status.setup.usable_active_root is None:
        return DaemonAdminResult(
            result="setup_required",
            daemon=status.daemon,
            message="A usable active brain root must be attached before starting the daemon.",
        )

    daemon = status.daemon
    if daemon.healthy:
        return DaemonAdminResult(
            result="already_running",
            daemon=daemon,
            message="A healthy daemon is already running for this runtime config directory.",
            adopted=True,
        )

    if daemon.state == "stale" and daemon.competing_start_refused:
        return _stale_control_blocked_result("replace")

    return _start_new_background(status.setup.usable_active_root)


def stop_daemon() -> DaemonAdminResult:
    """Stop the shared launcher-background daemon when remote control is supported."""
    status = get_runtime_status()
    daemon = status.daemon
    if daemon.state == "not_running":
        return DaemonAdminResult(result="not_running", daemon=daemon, message="No daemon is currently running.")
    if daemon.state == "stale":
        return DaemonAdminResult(
            result="not_running",
            daemon=daemon,
            message="No healthy remotely controllable daemon is currently running.",
        )
    if daemon.controller_kind != LAUNCHER_BACKGROUND_CONTROLLER or not daemon.stop_supported:
        return DaemonAdminResult(
            result="unsupported_for_controller_kind",
            daemon=daemon,
            message="Remote stop is supported only for launcher-background daemons in v1.",
        )
    return _stop_launcher_background(daemon)


def restart_daemon() -> DaemonAdminResult:
    """Restart the shared daemon using the launcher-background admin flow."""
    status = get_runtime_status()
    if not status.setup.ready or status.setup.usable_active_root is None:
        return DaemonAdminResult(
            result="setup_required",
            daemon=status.daemon,
            message="A usable active brain root must be attached before restarting the daemon.",
        )

    daemon = status.daemon
    if daemon.state == "not_running":
        return _start_new_background(status.setup.usable_active_root)
    if daemon.state == "stale" and daemon.competing_start_refused:
        return _stale_control_blocked_result("restart")
    if daemon.state == "stale":
        return _start_new_background(status.setup.usable_active_root)
    if daemon.controller_kind != LAUNCHER_BACKGROUND_CONTROLLER or not daemon.restart_supported:
        return DaemonAdminResult(
            result="unsupported_for_controller_kind",
            daemon=daemon,
            message="Remote restart is supported only for launcher-background daemons in v1.",
        )

    stop_result = _stop_launcher_background(daemon)
    if stop_result.result != "stopped":
        return stop_result
    start_result = _start_new_background(status.setup.usable_active_root)
    if start_result.result == "started":
        return DaemonAdminResult(
            result="restarted",
            daemon=start_result.daemon,
            message="Restarted launcher-background daemon.",
        )
    return start_result


def ensure_daemon_running_for_mcp() -> DaemonAdminResult | None:
    """Best-effort daemon ensure-running for full MCP tool use."""
    status = get_runtime_status()
    if not status.setup.ready:
        return None
    if status.daemon.healthy:
        return DaemonAdminResult(
            result="already_running",
            daemon=status.daemon,
            message="A healthy daemon is already running for this runtime config directory.",
            adopted=True,
        )
    result = start_daemon()
    if result.result not in {"started", "already_running"}:
        log.info("MCP ensure-running did not start a daemon: %s (%s)", result.result, result.message)
    return result

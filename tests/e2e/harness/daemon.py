"""Daemon process lifecycle manager for E2E tests."""

from __future__ import annotations

import json
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psutil

from tests.harness.isolation import build_subprocess_env, layout_from_config_dir


class DaemonProcess:
    """Manages a brain-sync daemon subprocess for E2E tests."""

    def __init__(
        self,
        brain_root: Path,
        config_dir: Path,
        capture_dir: Path | None = None,
        extra_env: dict[str, str] | None = None,
    ):
        self.brain_root = brain_root
        self.config_dir = config_dir
        self.capture_dir = capture_dir
        self.extra_env = extra_env or {}
        self._proc: subprocess.Popen | None = None  # type: ignore[type-arg]
        self._launch_time: str | None = None

    def _home_dir(self) -> Path:
        return layout_from_config_dir(self.config_dir).home_dir

    def _skill_dir(self) -> Path:
        return layout_from_config_dir(self.config_dir).skill_dir

    def _env(self) -> dict[str, str]:
        return build_subprocess_env(
            layout=layout_from_config_dir(self.config_dir),
            capture_dir=self.capture_dir,
            extra_env=self.extra_env,
        )

    def start(self) -> None:
        """Start the daemon subprocess."""
        self._launch_time = datetime.now(UTC).isoformat()
        cmd = [sys.executable, "-m", "brain_sync", "run", "--root", str(self.brain_root)]
        # CREATE_NEW_PROCESS_GROUP lets us send a targeted console control
        # event on Windows without taking down the pytest worker process.
        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env(),
            **kwargs,
        )

    def wait_for_ready(self, timeout: float = 15) -> None:
        """Poll the daemon status file until status='ready' for this process."""
        if self._proc is None:
            raise RuntimeError("Daemon not started")
        status_path = self.config_dir / "daemon.json"
        pid = self._proc.pid
        launch_time = self._launch_time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running():
                stderr = self.stderr_text
                raise RuntimeError(f"Daemon exited before becoming ready. stderr:\n{stderr}")
            if status_path.exists():
                try:
                    payload = json.loads(status_path.read_text(encoding="utf-8"))
                    if (
                        payload.get("pid") == pid
                        and payload.get("status") == "ready"
                        and payload.get("started_at")
                        and launch_time
                        and payload["started_at"] >= launch_time
                    ):
                        return
                except (json.JSONDecodeError, OSError):
                    pass
            time.sleep(0.5)
        raise TimeoutError(f"Daemon not ready after {timeout}s")

    def shutdown(self, timeout: float = 10) -> None:
        """Gracefully shut down the daemon."""
        if self._proc is None or not self.is_running():
            return

        # Platform-appropriate signal
        try:
            if sys.platform == "win32":
                # CTRL_BREAK_EVENT targets the child process group more
                # reliably than CTRL_C_EVENT under xdist/CI consoles.
                self._proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                self._proc.send_signal(signal.SIGINT)
        except OSError:
            pass

        try:
            self._proc.wait(timeout=timeout)
            return
        except subprocess.TimeoutExpired:
            pass

        # Escalate: terminate
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass

        # Last resort: kill entire process tree
        self._kill_tree()

    def _kill_tree(self) -> None:
        """Kill the daemon and all child processes."""
        if self._proc is None:
            return
        try:
            parent = psutil.Process(self._proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.kill()
                except psutil.NoSuchProcess:
                    pass
            parent.kill()
            parent.wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass

    def is_running(self) -> bool:
        """Check if the daemon process is still running."""
        if self._proc is None:
            return False
        return self._proc.poll() is None

    @property
    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    @property
    def stdout_text(self) -> str:
        """Read captured stdout (only available after process exits)."""
        if self._proc and self._proc.stdout:
            try:
                return self._proc.stdout.read().decode("utf-8", errors="replace")
            except Exception:
                return ""
        return ""

    @property
    def stderr_text(self) -> str:
        """Read captured stderr (only available after process exits)."""
        if self._proc and self._proc.stderr:
            try:
                return self._proc.stderr.read().decode("utf-8", errors="replace")
            except Exception:
                return ""
        return ""

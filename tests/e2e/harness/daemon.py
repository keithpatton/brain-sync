"""Daemon process lifecycle manager for E2E tests."""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import psutil


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

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["BRAIN_SYNC_CONFIG_DIR"] = str(self.config_dir)
        env["BRAIN_SYNC_LLM_BACKEND"] = "fake"
        if self.capture_dir:
            env["BRAIN_SYNC_CAPTURE_PROMPTS"] = str(self.capture_dir)
        env.pop("CLAUDECODE", None)
        env.update(self.extra_env)
        return env

    def start(self) -> None:
        """Start the daemon subprocess."""
        cmd = [sys.executable, "-m", "brain_sync", "run", str(self.brain_root)]
        # CREATE_NEW_PROCESS_GROUP needed on Windows for CTRL_C_EVENT
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
        """Poll the SQLite database until the daemon is present."""
        db_path = self.brain_root / ".sync-state.sqlite"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.is_running():
                raise RuntimeError("Daemon exited before becoming ready")
            if db_path.exists():
                try:
                    conn = sqlite3.connect(str(db_path), timeout=1)
                    # If we can connect and the DB has tables, daemon is ready
                    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    conn.close()
                    if tables:
                        return
                except (sqlite3.OperationalError, sqlite3.DatabaseError):
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
                self._proc.send_signal(signal.CTRL_C_EVENT)
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

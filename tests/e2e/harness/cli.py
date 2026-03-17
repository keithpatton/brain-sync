"""CLI subprocess runner for system and E2E tests."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CliResult:
    """Result of a CLI subprocess invocation."""

    returncode: int
    stdout: str
    stderr: str


@dataclass
class CliRunner:
    """Run brain-sync CLI commands as subprocesses with isolated env."""

    config_dir: Path
    capture_dir: Path | None = None
    extra_env: dict[str, str] = field(default_factory=dict)

    def _home_dir(self) -> Path:
        return self.config_dir.parent / "home"

    def _skill_dir(self) -> Path:
        return self._home_dir() / ".claude" / "skills" / "brain-sync"

    def _env(self) -> dict[str, str]:
        env = os.environ.copy()
        home_dir = self._home_dir()
        env["BRAIN_SYNC_CONFIG_DIR"] = str(self.config_dir)
        env["BRAIN_SYNC_SKILL_INSTALL_DIR"] = str(self._skill_dir())
        env["BRAIN_SYNC_LLM_BACKEND"] = "fake"
        env["HOME"] = str(home_dir)
        env["USERPROFILE"] = str(home_dir)
        env["APPDATA"] = str(home_dir / "AppData" / "Roaming")
        env["LOCALAPPDATA"] = str(home_dir / "AppData" / "Local")
        if self.capture_dir:
            env["BRAIN_SYNC_CAPTURE_PROMPTS"] = str(self.capture_dir)
        # Remove CLAUDECODE to prevent unwanted CLI mode
        env.pop("CLAUDECODE", None)
        env.update(self.extra_env)
        return env

    def run(self, *args: str, timeout: float = 30, cwd: Path | None = None) -> CliResult:
        """Run ``python -m brain_sync <args>`` as a subprocess."""
        cmd = [sys.executable, "-m", "brain_sync", *args]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=self._env(),
            cwd=str(cwd) if cwd is not None else None,
        )
        return CliResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

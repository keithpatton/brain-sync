"""CLI subprocess runner for system and E2E tests."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from tests.harness.isolation import build_subprocess_env, layout_from_config_dir


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
        return layout_from_config_dir(self.config_dir).home_dir

    def _skill_dir(self) -> Path:
        return layout_from_config_dir(self.config_dir).skill_dir

    def _env(self) -> dict[str, str]:
        return build_subprocess_env(
            layout=layout_from_config_dir(self.config_dir),
            capture_dir=self.capture_dir,
            extra_env=self.extra_env,
        )

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

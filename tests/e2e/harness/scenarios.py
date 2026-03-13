"""Reusable multi-step workflows for E2E tests."""

from __future__ import annotations

import shutil
from pathlib import Path

from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess


def write_knowledge_file(root: Path, rel_path: str, content: str) -> Path:
    """Create a knowledge file, ensuring parent dirs exist."""
    target = root / "knowledge" / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def move_folder(root: Path, old_path: str, new_path: str) -> None:
    """Rename a folder within knowledge/."""
    src = root / "knowledge" / old_path
    dst = root / "knowledge" / new_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


def run_regen(cli: CliRunner, brain_root: Path, path: str | None = None) -> None:
    """Run brain-sync regen via CLI helper."""
    args = ["regen", str(brain_root)]
    if path:
        args.extend(["--path", path])
    result = cli.run(*args)
    assert result.returncode == 0, f"Regen failed: {result.stderr}"


def restart_daemon(daemon: DaemonProcess) -> None:
    """Stop and restart the daemon, preserving brain state."""
    daemon.shutdown()
    daemon.start()
    daemon.wait_for_ready()


def add_source_and_verify(cli: CliRunner, root: Path, url: str, path: str) -> None:
    """Add a source and verify it appears in DB."""
    result = cli.run("add", url, "--target-path", path, "--root", str(root))
    assert result.returncode == 0, f"Add failed: {result.stderr}"

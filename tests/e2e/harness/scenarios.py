"""Reusable multi-step workflows for E2E tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

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
    args = ["regen", "--root", str(brain_root)]
    if path:
        args.append(path)
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


def script_test_source(
    root: Path,
    canonical_id: str,
    sequence: list[dict[str, Any]],
    *,
    delay_ms: int = 0,
) -> None:
    """Write a scenario JSON for the test source adapter.

    The adapter reads from ``{root}/.test-adapter/{canonical_id}.json``.
    """
    adapter_dir = root / ".test-adapter"
    adapter_dir.mkdir(exist_ok=True)
    safe_name = canonical_id.replace(":", "_")
    data = {"sequence": sequence, "delay_ms": delay_ms}
    (adapter_dir / f"{safe_name}.json").write_text(json.dumps(data), encoding="utf-8")

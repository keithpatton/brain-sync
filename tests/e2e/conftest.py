"""Shared fixtures for E2E tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.e2e.harness.artifacts import pytest_runtest_makereport  # noqa: F401
from tests.e2e.harness.brain import BrainFixture, create_brain
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess


@pytest.fixture
def brain(tmp_path: Path) -> BrainFixture:
    """Create a fresh brain for testing."""
    config_dir = tmp_path / ".brain-sync"
    config_dir.mkdir()
    config = {"brain_root": str(tmp_path / "brain")}
    (config_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return create_brain(tmp_path)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Isolated config directory."""
    d = tmp_path / ".brain-sync"
    d.mkdir(exist_ok=True)
    return d


@pytest.fixture
def capture_dir(tmp_path: Path) -> Path:
    """Directory for captured prompts."""
    d = tmp_path / "prompts"
    d.mkdir()
    return d


@pytest.fixture
def cli(config_dir: Path, capture_dir: Path) -> CliRunner:
    """CLI runner with isolated env."""
    return CliRunner(config_dir=config_dir, capture_dir=capture_dir)


@pytest.fixture
def daemon(brain: BrainFixture, config_dir: Path, capture_dir: Path):
    """Daemon process with automatic cleanup."""
    d = DaemonProcess(
        brain_root=brain.root,
        config_dir=config_dir,
        capture_dir=capture_dir,
    )
    yield d
    d.shutdown()

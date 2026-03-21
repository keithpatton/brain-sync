"""Shared fixtures for system tests (CLI subprocess)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.harness.cli import CliRunner
from tests.harness.isolation import layout_from_config_dir, write_active_brain_config


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Isolated config directory."""
    d = tmp_path / ".brain-sync"
    d.mkdir()
    return d


@pytest.fixture
def cli(config_dir: Path) -> CliRunner:
    """CLI runner with isolated env."""
    return CliRunner(config_dir=config_dir)


@pytest.fixture
def brain_root(tmp_path: Path, config_dir: Path) -> Path:
    """Path where brain will be initialised by CLI."""
    root = tmp_path / "brain"
    write_active_brain_config(layout_from_config_dir(config_dir), root)
    return root

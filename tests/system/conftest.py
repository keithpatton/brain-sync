"""Shared fixtures for system tests (CLI subprocess)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.e2e.harness.cli import CliRunner


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
    # Write config so CLI can discover brain root
    config = {"brain_root": str(root)}
    (config_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    return root

"""Shared fixtures for E2E tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.e2e.harness.artifacts import pytest_runtest_makereport  # noqa: F401
from tests.e2e.harness.assertions import assert_brain_consistent
from tests.e2e.harness.brain import BrainFixture, create_brain
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess

# Thread-local-ish holder: stores the brain root path so the autouse
# invariant fixture can access it even after the brain fixture is torn down.
_brain_root_holder: dict[str, Path] = {}


@pytest.fixture
def brain(tmp_path: Path, config_dir: Path) -> BrainFixture:
    """Create a fresh brain for testing."""
    config = {"brain_root": str(tmp_path / "brain")}
    (config_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    bf = create_brain(tmp_path)
    # Stash root path for the invariant fixture
    _brain_root_holder[str(tmp_path)] = bf.root
    return bf


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated config directory."""
    d = tmp_path / ".brain-sync"
    d.mkdir(exist_ok=True)
    runtime_db_file = d / "db" / "brain-sync.sqlite"
    daemon_status_file = d / "daemon.json"
    config_file = d / "config.json"
    monkeypatch.setenv("BRAIN_SYNC_CONFIG_DIR", str(d))
    monkeypatch.setattr("brain_sync.config.CONFIG_DIR", d)
    monkeypatch.setattr("brain_sync.config.CONFIG_FILE", config_file)
    monkeypatch.setattr("brain_sync.config.RUNTIME_DB_FILE", runtime_db_file)
    monkeypatch.setattr("brain_sync.config.DAEMON_STATUS_FILE", daemon_status_file)
    monkeypatch.setattr("brain_sync.state.RUNTIME_DB_FILE", runtime_db_file)
    monkeypatch.setattr("brain_sync.state.DAEMON_STATUS_FILE", daemon_status_file)
    monkeypatch.setattr("brain_sync.token_tracking.RUNTIME_DB_FILE", runtime_db_file)
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


@pytest.fixture(autouse=True)
def _check_brain_invariants(request: pytest.FixtureRequest, tmp_path: Path):
    """Post-test invariant: knowledge/, insights/, and DB must be consistent.

    Opt out with ``@pytest.mark.skip_invariants``.
    """
    yield
    if request.node.get_closest_marker("skip_invariants"):
        return
    key = str(tmp_path)
    root = _brain_root_holder.pop(key, None)
    if root is not None and root.exists():
        assert_brain_consistent(root)

"""Shared fixtures for E2E tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e.harness.artifacts import pytest_runtest_makereport  # noqa: F401
from tests.e2e.harness.assertions import assert_brain_consistent
from tests.e2e.harness.brain import BrainFixture, create_brain
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.harness.isolation import apply_in_process_isolation, layout_from_config_dir, write_active_brain_config

# Thread-local-ish holder: stores the brain root path so the autouse
# invariant fixture can access it even after the brain fixture is torn down.
_brain_root_holder: dict[str, Path] = {}


@pytest.fixture
def brain(tmp_path: Path, config_dir: Path) -> BrainFixture:
    """Create a fresh brain for testing."""
    write_active_brain_config(layout_from_config_dir(config_dir), tmp_path / "brain")
    bf = create_brain(tmp_path)
    # Stash root path for the invariant fixture
    _brain_root_holder[str(tmp_path)] = bf.root
    return bf


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated config directory."""
    d = tmp_path / ".brain-sync"
    d.mkdir(exist_ok=True)
    apply_in_process_isolation(monkeypatch, layout=layout_from_config_dir(d))
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

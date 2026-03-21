"""Top-level test conftest — shared fixtures for all test tiers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from brain_sync.runtime.paths import brain_sync_user_dir
from tests.harness.isolation import (
    apply_in_process_isolation,
    assert_temp_test_layout,
    layout_for_base_dir,
    populate_brain_sync_env,
)

_COLLECTION_LAYOUT = layout_for_base_dir(
    Path(tempfile.mkdtemp(prefix="brain-sync-test-collection-")), config_dir_name="config"
)
_COLLECTION_LAYOUT.config_dir.mkdir(parents=True, exist_ok=True)
_COLLECTION_LAYOUT.home_dir.mkdir(parents=True, exist_ok=True)
populate_brain_sync_env(os.environ, layout=_COLLECTION_LAYOUT)


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent any in-process test from touching the real machine-local state.

    Uses a separate temp directory (not tmp_path) to avoid polluting the test's
    working directory.  E2E/system tests are unaffected — they run in subprocesses
    with isolated env set by the test harness.
    """
    with tempfile.TemporaryDirectory() as td:
        layout = layout_for_base_dir(Path(td), config_dir_name="config")
        layout.config_dir.mkdir()
        layout.home_dir.mkdir()
        apply_in_process_isolation(monkeypatch, layout=layout)
        yield


@pytest.fixture(autouse=True)
def _guard_against_live_runtime_paths(request: pytest.FixtureRequest) -> None:
    if request.node.get_closest_marker("allow_non_temp_test_layout"):
        return
    assert_temp_test_layout(config_dir=brain_sync_user_dir(), home_dir=Path.home())

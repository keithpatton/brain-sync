from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.runtime.paths import (
    ALLOW_UNSAFE_TEMP_ROOTS_ENV,
    UnsafeMachineLocalRuntimeError,
    ensure_safe_temp_root_runtime,
)
from brain_sync.runtime.repository import _connect

pytestmark = pytest.mark.unit


def _configure_machine_local_runtime(monkeypatch: pytest.MonkeyPatch, home_dir: Path) -> None:
    monkeypatch.delenv("BRAIN_SYNC_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    monkeypatch.setenv("APPDATA", str(home_dir / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home_dir / "AppData" / "Local"))


def test_guard_rejects_temp_root_with_machine_local_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    temp_root = Path(tempfile.gettempdir()) / "brain-sync-unsafe-test" / "brain"

    _configure_machine_local_runtime(monkeypatch, home_dir)

    with pytest.raises(UnsafeMachineLocalRuntimeError, match="Refusing to test operation"):
        ensure_safe_temp_root_runtime(temp_root, operation="test operation")


def test_init_brain_rejects_temp_root_with_machine_local_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    temp_root = Path(tempfile.gettempdir()) / "brain-sync-unsafe-init" / "brain"
    skill_dir = tmp_path / "skills"

    _configure_machine_local_runtime(monkeypatch, home_dir)
    monkeypatch.setenv("BRAIN_SYNC_SKILL_INSTALL_DIR", str(skill_dir))

    with pytest.raises(UnsafeMachineLocalRuntimeError, match="initialise brain"):
        init_brain(temp_root)

    assert not temp_root.exists()
    assert not skill_dir.exists()


def test_runtime_db_rejects_temp_root_with_machine_local_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    temp_root = Path(tempfile.gettempdir()) / "brain-sync-unsafe-db" / "brain"

    _configure_machine_local_runtime(monkeypatch, home_dir)

    with pytest.raises(UnsafeMachineLocalRuntimeError, match="access runtime DB"):
        _connect(temp_root)


def test_override_allows_temp_root_with_machine_local_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    temp_root = Path(tempfile.gettempdir()) / "brain-sync-unsafe-override" / "brain"
    skill_dir = tmp_path / "skills"

    _configure_machine_local_runtime(monkeypatch, home_dir)
    monkeypatch.setenv(ALLOW_UNSAFE_TEMP_ROOTS_ENV, "1")
    monkeypatch.setenv("BRAIN_SYNC_SKILL_INSTALL_DIR", str(skill_dir))

    result = init_brain(temp_root)

    assert result.root == temp_root.resolve()
    assert (temp_root / ".brain-sync" / "brain.json").is_file()

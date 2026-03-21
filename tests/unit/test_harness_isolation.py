"""Regression tests for test harness environment isolation."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.init import skill_install_dir
from tests.e2e.harness.cli import CliRunner
from tests.e2e.harness.daemon import DaemonProcess
from tests.harness.isolation import assert_temp_test_layout

pytestmark = pytest.mark.unit


def test_skill_install_dir_uses_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill_dir = tmp_path / "home" / ".claude" / "skills" / "brain-sync"
    monkeypatch.setenv("BRAIN_SYNC_SKILL_INSTALL_DIR", str(skill_dir))

    assert skill_install_dir() == skill_dir


def test_cli_runner_isolates_machine_local_env(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    runner = CliRunner(config_dir=config_dir)

    env = runner._env()
    home_dir = config_dir.parent / "home"

    assert env["BRAIN_SYNC_CONFIG_DIR"] == str(config_dir)
    assert env["BRAIN_SYNC_SKILL_INSTALL_DIR"] == str(home_dir / ".claude" / "skills" / "brain-sync")
    assert env["HOME"] == str(home_dir)
    assert env["USERPROFILE"] == str(home_dir)
    assert env["APPDATA"] == str(home_dir / "AppData" / "Roaming")
    assert env["LOCALAPPDATA"] == str(home_dir / "AppData" / "Local")


def test_daemon_process_isolates_machine_local_env(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    daemon = DaemonProcess(brain_root=tmp_path / "brain", config_dir=config_dir)

    env = daemon._env()
    home_dir = config_dir.parent / "home"

    assert env["BRAIN_SYNC_CONFIG_DIR"] == str(config_dir)
    assert env["BRAIN_SYNC_SKILL_INSTALL_DIR"] == str(home_dir / ".claude" / "skills" / "brain-sync")
    assert env["HOME"] == str(home_dir)
    assert env["USERPROFILE"] == str(home_dir)
    assert env["APPDATA"] == str(home_dir / "AppData" / "Roaming")
    assert env["LOCALAPPDATA"] == str(home_dir / "AppData" / "Local")


def test_temp_layout_guard_accepts_isolated_temp_paths(tmp_path: Path) -> None:
    assert_temp_test_layout(config_dir=tmp_path / ".brain-sync", home_dir=tmp_path / "home")


def test_temp_layout_guard_rejects_non_temp_paths() -> None:
    with pytest.raises(AssertionError, match="non-temporary config/home path"):
        assert_temp_test_layout(config_dir=Path("C:/Users/live-user/.brain-sync"), home_dir=Path("C:/Users/live-user"))

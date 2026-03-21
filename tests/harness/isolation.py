"""Shared test-isolation helpers for in-process and subprocess harnesses."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass(frozen=True)
class TestIsolationLayout:
    config_dir: Path
    home_dir: Path

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def runtime_db_file(self) -> Path:
        return self.config_dir / "db" / "brain-sync.sqlite"

    @property
    def daemon_status_file(self) -> Path:
        return self.config_dir / "daemon.json"

    @property
    def skill_dir(self) -> Path:
        return self.home_dir / ".claude" / "skills" / "brain-sync"

    @property
    def log_dir(self) -> Path:
        return self.config_dir / "logs"

    @property
    def log_file(self) -> Path:
        return self.log_dir / "brain-sync.log"

    @property
    def google_token_file(self) -> Path:
        return self.config_dir / "google_token.json"


def layout_for_base_dir(
    base_dir: Path, *, config_dir_name: str = ".brain-sync", home_dir_name: str = "home"
) -> TestIsolationLayout:
    return TestIsolationLayout(
        config_dir=base_dir / config_dir_name,
        home_dir=base_dir / home_dir_name,
    )


def layout_from_config_dir(config_dir: Path, *, home_dir_name: str = "home") -> TestIsolationLayout:
    return TestIsolationLayout(config_dir=config_dir, home_dir=config_dir.parent / home_dir_name)


def populate_brain_sync_env(
    env: MutableMapping[str, str],
    *,
    layout: TestIsolationLayout,
    capture_dir: Path | None = None,
    repo_root: Path | None = None,
    llm_backend: str | None = "fake",
    include_config_dir: bool = True,
    extra_env: Mapping[str, str] | None = None,
) -> MutableMapping[str, str]:
    if include_config_dir:
        env["BRAIN_SYNC_CONFIG_DIR"] = str(layout.config_dir)
    else:
        env.pop("BRAIN_SYNC_CONFIG_DIR", None)
    env["BRAIN_SYNC_SKILL_INSTALL_DIR"] = str(layout.skill_dir)
    env["HOME"] = str(layout.home_dir)
    env["USERPROFILE"] = str(layout.home_dir)
    env["APPDATA"] = str(layout.home_dir / "AppData" / "Roaming")
    env["LOCALAPPDATA"] = str(layout.home_dir / "AppData" / "Local")
    if llm_backend is None:
        env.pop("BRAIN_SYNC_LLM_BACKEND", None)
    else:
        env["BRAIN_SYNC_LLM_BACKEND"] = llm_backend
    if capture_dir is None:
        env.pop("BRAIN_SYNC_CAPTURE_PROMPTS", None)
    else:
        env["BRAIN_SYNC_CAPTURE_PROMPTS"] = str(capture_dir)
    if repo_root is not None:
        pythonpath = str(repo_root / "src")
        existing = env.get("PYTHONPATH")
        env["PYTHONPATH"] = pythonpath if not existing else pythonpath + os.pathsep + existing
    env.pop("CLAUDECODE", None)
    if extra_env:
        env.update({key: str(value) for key, value in extra_env.items()})
    return env


def build_subprocess_env(
    *,
    layout: TestIsolationLayout,
    capture_dir: Path | None = None,
    repo_root: Path | None = None,
    llm_backend: str | None = "fake",
    include_config_dir: bool = True,
    extra_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ)
    populate_brain_sync_env(
        env,
        layout=layout,
        capture_dir=capture_dir,
        repo_root=repo_root,
        llm_backend=llm_backend,
        include_config_dir=include_config_dir,
        extra_env=extra_env,
    )
    return env


def apply_in_process_isolation(
    monkeypatch: pytest.MonkeyPatch,
    *,
    layout: TestIsolationLayout,
) -> None:
    monkeypatch.setenv("BRAIN_SYNC_CONFIG_DIR", str(layout.config_dir))
    monkeypatch.setenv("BRAIN_SYNC_SKILL_INSTALL_DIR", str(layout.skill_dir))
    monkeypatch.setenv("HOME", str(layout.home_dir))
    monkeypatch.setenv("USERPROFILE", str(layout.home_dir))
    monkeypatch.setenv("APPDATA", str(layout.home_dir / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(layout.home_dir / "AppData" / "Local"))
    monkeypatch.setattr("brain_sync.runtime.config.CONFIG_DIR", layout.config_dir)
    monkeypatch.setattr("brain_sync.runtime.config.CONFIG_FILE", layout.config_file)
    monkeypatch.setattr("brain_sync.runtime.config.RUNTIME_DB_FILE", layout.runtime_db_file)
    monkeypatch.setattr("brain_sync.runtime.config.DAEMON_STATUS_FILE", layout.daemon_status_file)
    monkeypatch.setattr("brain_sync.util.logging.LOG_DIR", layout.log_dir)
    monkeypatch.setattr("brain_sync.util.logging.LOG_FILE", layout.log_file)


def write_active_brain_config(layout: TestIsolationLayout, root: Path) -> None:
    layout.config_dir.mkdir(parents=True, exist_ok=True)
    layout.config_file.write_text(json.dumps({"brains": [str(root)]}), encoding="utf-8")


def assert_temp_test_layout(*, config_dir: Path, home_dir: Path) -> None:
    temp_root = Path(tempfile.gettempdir()).resolve(strict=False)
    resolved_config = config_dir.resolve(strict=False)
    resolved_home = home_dir.resolve(strict=False)
    try:
        resolved_config.relative_to(temp_root)
        resolved_home.relative_to(temp_root)
    except ValueError as exc:
        raise AssertionError(
            "Test isolation resolved to a non-temporary config/home path "
            f"(config={resolved_config}, home={resolved_home})"
        ) from exc

from __future__ import annotations

import os
import tempfile
from pathlib import Path

RUNTIME_DB_SCHEMA_VERSION = 27
RUNTIME_DB_DIRNAME = "db"
RUNTIME_DB_FILENAME = "brain-sync.sqlite"
DAEMON_STATUS_FILENAME = "daemon.json"
ALLOW_UNSAFE_TEMP_ROOTS_ENV = "BRAIN_SYNC_ALLOW_UNSAFE_TEMP_ROOTS"


class UnsafeMachineLocalRuntimeError(RuntimeError):
    """Raised when a temp brain root would write into the real machine-local runtime."""


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        _resolve_path(path).relative_to(_resolve_path(parent))
        return True
    except ValueError:
        return False


def machine_local_config_dir() -> Path:
    return Path.home() / ".brain-sync"


def brain_sync_user_dir() -> Path:
    if "BRAIN_SYNC_CONFIG_DIR" in os.environ:
        return Path(os.environ["BRAIN_SYNC_CONFIG_DIR"])
    return Path.home() / ".brain-sync"


def runtime_uses_machine_local_config_dir() -> bool:
    return _resolve_path(brain_sync_user_dir()) == _resolve_path(machine_local_config_dir())


def is_temp_brain_root(root: Path) -> bool:
    root = _resolve_path(root)
    candidates: list[Path] = [Path(tempfile.gettempdir())]

    for name in ("TEMP", "TMP", "TMPDIR"):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value))

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Temp")

    return any(_is_relative_to(root, candidate) for candidate in candidates)


def ensure_safe_temp_root_runtime(root: Path, *, operation: str) -> None:
    """Fail closed when a temp brain root would use the real ~/.brain-sync runtime."""
    if os.environ.get(ALLOW_UNSAFE_TEMP_ROOTS_ENV) == "1":
        return
    if not is_temp_brain_root(root):
        return
    if not runtime_uses_machine_local_config_dir():
        return

    raise UnsafeMachineLocalRuntimeError(
        f"Refusing to {operation} for temp brain root '{root}' while using machine-local runtime "
        f"'{brain_sync_user_dir()}'. Set BRAIN_SYNC_CONFIG_DIR to an isolated directory, or set "
        f"{ALLOW_UNSAFE_TEMP_ROOTS_ENV}=1 to override."
    )


def runtime_db_path() -> Path:
    return brain_sync_user_dir() / RUNTIME_DB_DIRNAME / RUNTIME_DB_FILENAME


def daemon_status_path() -> Path:
    return brain_sync_user_dir() / DAEMON_STATUS_FILENAME


__all__ = [
    "ALLOW_UNSAFE_TEMP_ROOTS_ENV",
    "DAEMON_STATUS_FILENAME",
    "RUNTIME_DB_DIRNAME",
    "RUNTIME_DB_FILENAME",
    "RUNTIME_DB_SCHEMA_VERSION",
    "UnsafeMachineLocalRuntimeError",
    "brain_sync_user_dir",
    "daemon_status_path",
    "ensure_safe_temp_root_runtime",
    "is_temp_brain_root",
    "machine_local_config_dir",
    "runtime_db_path",
    "runtime_uses_machine_local_config_dir",
]

"""Brain root resolution, setup readiness, and active-root attachment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import brain_sync.runtime.config as _config
from brain_sync.brain.fileops import path_is_dir, path_is_file
from brain_sync.brain.layout import brain_manifest_path, knowledge_root
from brain_sync.runtime.config import active_brain_root, load_config
from brain_sync.runtime.paths import ensure_safe_temp_root_runtime

# Re-export for backwards compatibility during migration
__all__ = [
    "AttachRootResult",
    "BrainNotFoundError",
    "InvalidBrainRootError",
    "SetupStatus",
    "attach_root",
    "get_setup_status",
    "list_registered_roots",
    "resolve_active_root",
    "resolve_root",
    "validate_brain_root",
]


class BrainNotFoundError(Exception):
    """Raised when no brain root can be resolved."""


class InvalidBrainRootError(BrainNotFoundError):
    """Raised when the brain root is misconfigured."""


@dataclass(frozen=True)
class SetupStatus:
    """Current runtime attachment readiness for the single-brain runtime model."""

    configured_active_root: Path | None
    usable_active_root: Path | None
    registered_roots: tuple[Path, ...]
    reason: str | None
    message: str

    @property
    def ready(self) -> bool:
        return self.usable_active_root is not None


@dataclass(frozen=True)
class AttachRootResult:
    """Result of making one initialized brain root active for this runtime."""

    root: Path
    previous_active_root: Path | None
    registered_roots: tuple[Path, ...]


def _normalize_root_key(root: Path | str) -> str:
    resolved = Path(root).expanduser().resolve(strict=False)
    value = str(resolved)
    return value.lower() if os.name == "nt" else value


def _dedupe_roots(paths: list[Path]) -> tuple[Path, ...]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = _normalize_root_key(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return tuple(deduped)


def list_registered_roots(config: Mapping[str, object] | None = None) -> tuple[Path, ...]:
    """Return registered roots from config.json in stored order."""
    data = load_config() if config is None else config
    brains = data.get("brains")
    if not isinstance(brains, list):
        return ()

    paths: list[Path] = []
    for entry in brains:
        if isinstance(entry, str) and entry.strip():
            paths.append(Path(entry).expanduser())
    return _dedupe_roots(paths)


def _save_active_root(root: Path, *, config: dict | None = None) -> tuple[Path | None, tuple[Path, ...]]:
    """Write *root* to index 0 and preserve other registered roots after it."""
    data = load_config() if config is None else config
    previous_active = active_brain_root(data)
    registered = list_registered_roots(data)
    ordered = _dedupe_roots([root.resolve(), *registered])
    data["brains"] = [str(path) for path in ordered]
    _config.save_config(data)
    return previous_active, ordered


def validate_brain_root(root: Path) -> None:
    """Validate that root has the expected brain structure.

    Raises InvalidBrainRootError if the structural invariant is violated.
    """
    if not path_is_dir(knowledge_root(root)) or not path_is_file(brain_manifest_path(root)):
        raise InvalidBrainRootError(
            f"Brain root '{root}' is invalid.\n"
            f"Expected structure:\n"
            f"  {root}/.brain-sync/brain.json\n"
            f"  {root}/knowledge/\n"
            f"The configured root appears to point to the wrong directory."
        )


def resolve_active_root() -> Path:
    """Read the active brain root from ~/.brain-sync/config.json.

    The runtime is intentionally single-brain per config directory. If the
    config file still carries multiple registered roots, only the first entry
    is treated as active runtime state in this architecture stage.

    Raises BrainNotFoundError if no brain is configured.
    Raises InvalidBrainRootError if the root lacks expected structure.
    """
    config_file = _config.config_file_path()
    if not config_file.exists():
        raise BrainNotFoundError("No brain configured. Run: brain-sync init <path>")
    data = load_config()
    if not data:
        raise BrainNotFoundError(f"Cannot read {config_file}")
    root = active_brain_root(data)
    if root is None:
        raise BrainNotFoundError("No active brain root registered in config")
    validate_brain_root(root)
    return root


def get_setup_status() -> SetupStatus:
    """Inspect current runtime readiness without requiring a valid active root."""
    data = load_config()
    registered = list_registered_roots(data)
    configured = active_brain_root(data)
    if configured is None:
        return SetupStatus(
            configured_active_root=None,
            usable_active_root=None,
            registered_roots=registered,
            reason="no_active_root",
            message="No active brain root is registered in config.json.",
        )

    try:
        validate_brain_root(configured)
    except InvalidBrainRootError as exc:
        return SetupStatus(
            configured_active_root=configured,
            usable_active_root=None,
            registered_roots=registered,
            reason="invalid_active_root",
            message=str(exc),
        )

    return SetupStatus(
        configured_active_root=configured,
        usable_active_root=configured,
        registered_roots=registered,
        reason=None,
        message="Active brain root is ready.",
    )


def attach_root(root: Path) -> AttachRootResult:
    """Make an existing initialized brain root the active runtime root."""
    resolved = root.resolve()
    ensure_safe_temp_root_runtime(resolved, operation="attach root")
    validate_brain_root(resolved)
    previous_active, registered = _save_active_root(resolved)
    return AttachRootResult(
        root=resolved,
        previous_active_root=previous_active,
        registered_roots=registered,
    )


def resolve_root() -> Path:
    """Compatibility alias for the active-root resolver."""
    return resolve_active_root()


def _require_root(root: Path | None) -> Path:
    """Resolve root: explicit path wins, otherwise auto-discover from config."""
    if root is not None:
        resolved = root.resolve()
        validate_brain_root(resolved)
        return resolved
    return resolve_active_root()

"""Brain root resolution and context discovery."""

from __future__ import annotations

from pathlib import Path

import brain_sync.runtime.config as _config
from brain_sync.brain.fileops import path_is_dir, path_is_file
from brain_sync.brain.layout import brain_manifest_path, knowledge_root
from brain_sync.runtime.config import active_brain_root, load_config

# Re-export for backwards compatibility during migration
__all__ = [
    "BrainNotFoundError",
    "InvalidBrainRootError",
    "resolve_active_root",
    "resolve_root",
    "validate_brain_root",
]


class BrainNotFoundError(Exception):
    """Raised when no brain root can be resolved."""


class InvalidBrainRootError(BrainNotFoundError):
    """Raised when the brain root is misconfigured."""


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

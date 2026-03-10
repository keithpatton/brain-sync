"""Brain root resolution and context discovery."""

from __future__ import annotations

from pathlib import Path

from brain_sync.config import CONFIG_DIR, CONFIG_FILE, load_config

# Re-export for backwards compatibility during migration
__all__ = ["CONFIG_DIR", "CONFIG_FILE", "BrainNotFoundError", "resolve_root"]


class BrainNotFoundError(Exception):
    """Raised when no brain root can be resolved."""


def resolve_root() -> Path:
    """Read brain root from ~/.brain-sync/config.json.

    Returns the first registered brain root.
    Raises BrainNotFoundError if no brain is configured.
    """
    if not CONFIG_FILE.exists():
        raise BrainNotFoundError("No brain configured. Run: brain-sync init <path>")
    data = load_config()
    if not data:
        raise BrainNotFoundError(f"Cannot read {CONFIG_FILE}")
    brains = data.get("brains", [])
    if not brains:
        raise BrainNotFoundError("No brain roots registered in config")
    return Path(brains[0])


def _require_root(root: Path | None) -> Path:
    """Resolve root: explicit path wins, otherwise auto-discover from config."""
    if root is not None:
        return root.resolve()
    return resolve_root()

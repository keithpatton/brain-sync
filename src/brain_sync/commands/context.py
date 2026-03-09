"""Brain root resolution and context discovery."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".brain-sync"
CONFIG_FILE = CONFIG_DIR / "config.json"


class BrainNotFoundError(Exception):
    """Raised when no brain root can be resolved."""


def resolve_root() -> Path:
    """Read brain root from ~/.brain-sync/config.json.

    Returns the first registered brain root.
    Raises BrainNotFoundError if no brain is configured.
    """
    if not CONFIG_FILE.exists():
        raise BrainNotFoundError("No brain configured. Run: brain-sync init <path>")
    try:
        data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        raise BrainNotFoundError(f"Cannot read {CONFIG_FILE}: {e}") from e
    brains = data.get("brains", [])
    if not brains:
        raise BrainNotFoundError("No brain roots registered in config")
    return Path(brains[0])


def _require_root(root: Path | None) -> Path:
    """Resolve root: explicit path wins, otherwise auto-discover from config."""
    if root is not None:
        return root.resolve()
    return resolve_root()

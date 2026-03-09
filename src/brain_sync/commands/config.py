"""Source credential configuration commands."""

from __future__ import annotations

import json
import logging

from brain_sync.commands.context import CONFIG_DIR, CONFIG_FILE

log = logging.getLogger(__name__)


def _load_config() -> dict:
    """Load existing config or return empty dict."""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_config(config: dict) -> None:
    """Write config to disk."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def configure_confluence(
    *,
    domain: str,
    email: str,
    token: str,
) -> None:
    """Set Confluence credentials in ~/.brain-sync/config.json."""
    config = _load_config()
    config["confluence"] = {
        "domain": domain,
        "email": email,
        "token": token,
    }
    _save_config(config)
    log.info("Confluence credentials saved to %s", CONFIG_FILE)

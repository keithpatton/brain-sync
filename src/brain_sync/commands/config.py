"""Source credential configuration commands."""

from __future__ import annotations

import logging

from brain_sync.config import CONFIG_FILE, load_config, save_config

log = logging.getLogger(__name__)


def configure_confluence(
    *,
    domain: str,
    email: str,
    token: str,
) -> None:
    """Set Confluence credentials in ~/.brain-sync/config.json."""
    config = load_config()
    config["confluence"] = {
        "domain": domain,
        "email": email,
        "token": token,
    }
    save_config(config)
    log.info("Confluence credentials saved to %s", CONFIG_FILE)

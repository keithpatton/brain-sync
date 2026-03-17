"""Confluence authentication provider."""

from __future__ import annotations

import logging

from brain_sync.runtime.config import CONFIG_FILE, load_config, save_config
from brain_sync.sources.confluence.rest import ConfluenceAuth, get_confluence_auth

log = logging.getLogger(__name__)


class ConfluenceAuthProvider:
    def load_auth(self) -> ConfluenceAuth | None:
        return get_confluence_auth()

    def configure(self, **kwargs: str) -> None:
        config = load_config()
        config["confluence"] = {
            "domain": kwargs["domain"],
            "email": kwargs["email"],
            "token": kwargs["token"],
        }
        save_config(config)
        log.info("Confluence credentials saved to %s", CONFIG_FILE)

    def validate_config(self) -> bool:
        return self.load_auth() is not None

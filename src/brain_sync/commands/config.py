"""Source credential configuration commands."""

from __future__ import annotations

import logging
from pathlib import Path

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


def configure_googledocs(
    *,
    client_secrets: str | None = None,
    reauth: bool = False,
) -> bool:
    """Configure Google Docs OAuth authentication."""
    from brain_sync.sources.googledocs.auth import (
        GoogleDocsAuthProvider,
        _get_client_secrets_path,
        run_oauth_flow,
    )

    if client_secrets:
        path = Path(client_secrets).resolve()
        if not path.exists():
            log.error("File not found: %s", path)
            return False
        config = load_config()
        config.setdefault("googledocs", {})["client_secrets_file"] = str(path)
        save_config(config)
        log.info("Client secrets path saved to config")
        run_oauth_flow(path)
        log.info("Google Docs: authenticated and token saved")
        return True

    if reauth:
        path = _get_client_secrets_path()
        if not path or not path.exists():
            log.error("No client secrets configured. Run with --client-secrets first")
            return False
        run_oauth_flow(path)
        log.info("Google Docs: re-authenticated")
        return True

    # Validate only
    provider = GoogleDocsAuthProvider()
    if provider.validate_config():
        log.info("Google Docs: authenticated")
        return True
    log.error("No Google Docs auth. Run: brain-sync config googledocs --client-secrets <path>")
    return False

"""Source credential configuration commands."""

from __future__ import annotations

import logging

from brain_sync.runtime.config import CONFIG_FILE, load_config, save_config

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


def configure_google(
    *,
    client_id: str | None = None,
    client_secret: str | None = None,
    project_id: str | None = None,
    reauth: bool = False,
) -> bool:
    """Configure Google Docs OAuth authentication."""
    from brain_sync.sources.googledocs.auth import (
        GoogleDocsAuthProvider,
        has_google_oauth_client,
        run_oauth_flow,
        save_google_oauth_client,
    )

    client_args_provided = client_id is not None or client_secret is not None or project_id is not None
    if (client_id is None) != (client_secret is None):
        raise ValueError("Pass both --client-id and --client-secret together.")

    if client_id is not None and client_secret is not None:
        save_google_oauth_client(client_id=client_id, client_secret=client_secret, project_id=project_id)
        log.info("Google Docs OAuth client saved to %s", CONFIG_FILE)

    if not has_google_oauth_client():
        raise ValueError(
            "Google OAuth client is not configured. Run config google with --client-id and --client-secret."
        )

    if not reauth and not client_args_provided:
        provider = GoogleDocsAuthProvider()
        if provider.validate_config():
            log.info("Google Docs: already authenticated")
            return True

    run_oauth_flow()
    log.info("Google Docs: authenticated and token saved")
    return True

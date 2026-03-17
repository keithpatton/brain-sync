"""Compatibility shim for Confluence REST helpers."""

from brain_sync.runtime.config import CONFIG_FILE
from brain_sync.sources.confluence.rest import (
    BACKOFF_BASE,
    MAX_RETRIES,
    ConfluenceAuth,
    _request,
    download_attachment,
    fetch_attachments,
    fetch_child_pages,
    fetch_comments,
    fetch_page_body,
    fetch_page_version,
    get_confluence_auth,
    reset_auth_cache,
)

__all__ = [
    "BACKOFF_BASE",
    "CONFIG_FILE",
    "MAX_RETRIES",
    "ConfluenceAuth",
    "_request",
    "download_attachment",
    "fetch_attachments",
    "fetch_child_pages",
    "fetch_comments",
    "fetch_page_body",
    "fetch_page_version",
    "get_confluence_auth",
    "reset_auth_cache",
]

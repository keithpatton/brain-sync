"""Source-aware title resolution for placement suggestions."""

from __future__ import annotations

import asyncio
import logging
import re

import httpx

from brain_sync.sources import SourceType, detect_source_type, extract_google_doc_id
from brain_sync.util.urls import extract_title_from_url

log = logging.getLogger(__name__)


_GDOCS_USELESS_SLUGS = frozenset({"edit", "preview", "copy", "view", "pub", "mobilebasic"})


def _is_opaque_gdocs_title(url: str, title: str) -> bool:
    """Check if extracted title is not human-readable for a Google Docs URL.

    Only applies to Google Docs URLs. Returns True when the title is:
    - The doc ID itself (possibly title-cased by extract_title_from_url)
    - A generic URL action slug like 'Edit', 'Preview', etc.
    """
    try:
        doc_id = extract_google_doc_id(url)
    except Exception:
        return False
    lower = title.lower()
    if lower in _GDOCS_USELESS_SLUGS:
        return True
    # extract_title_from_url replaces hyphens/underscores with spaces and title-cases,
    # so strip all non-alphanumeric chars before comparing against the raw doc ID.
    title_alnum = re.sub(r"[^a-z0-9]", "", lower)
    doc_id_alnum = re.sub(r"[^a-z0-9]", "", doc_id.lower())
    return title_alnum == doc_id_alnum


async def _resolve_gdocs_title(url: str) -> str | None:
    """Fetch Google Docs title via Drive API. Returns None on any failure."""
    from brain_sync.sources.googledocs.auth import GoogleDocsAuthProvider
    from brain_sync.sources.googledocs.rest import fetch_doc_title

    doc_id = extract_google_doc_id(url)
    auth = GoogleDocsAuthProvider().load_auth()
    if auth is None:
        return None
    async with httpx.AsyncClient() as client:
        return await fetch_doc_title(doc_id, auth, client)


async def resolve_source_title(url: str) -> str | None:
    """Resolve best available title for a source URL.

    1. Try cheap URL-slug heuristic
    2. If source is Google Docs and title is opaque, fetch via Drive API
    3. Returns None only if nothing usable exists
    """
    title = extract_title_from_url(url)

    try:
        source_type = detect_source_type(url)
    except Exception:
        return title or None

    is_opaque = not title or _is_opaque_gdocs_title(url, title)
    if source_type == SourceType.GOOGLE_DOCS and is_opaque:
        fetched = await _resolve_gdocs_title(url)
        if fetched:
            return fetched
        # Opaque title is useless — don't fall back to it
        return None

    return title or None


def resolve_source_title_sync(url: str) -> str | None:
    """Sync wrapper for resolve_source_title().

    Handles both cases: called outside any event loop (CLI) and called
    inside an existing event loop (MCP sync tool handlers).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        # No running loop — safe to use asyncio.run()
        try:
            return asyncio.run(resolve_source_title(url))
        except Exception:
            log.debug("Title resolution failed for %s", url, exc_info=True)
            return None

    # Inside a running loop (MCP) — run in a new thread with its own loop
    import concurrent.futures

    def _run() -> str | None:
        return asyncio.run(resolve_source_title(url))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_run)
            return future.result(timeout=15)
    except Exception:
        log.debug("Title resolution failed for %s", url, exc_info=True)
        return None

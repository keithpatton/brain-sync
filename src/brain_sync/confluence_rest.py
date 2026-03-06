from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".confluence-cli" / "config.json"

# Retry settings
MAX_RETRIES = 3
BACKOFF_BASE = 0.5  # seconds


@dataclass(frozen=True)
class ConfluenceAuth:
    domain: str
    email: str
    token: str

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}/wiki/rest/api"

    @property
    def basic_auth(self) -> tuple[str, str]:
        return (self.email, self.token)


_cached_auth: ConfluenceAuth | None = None
_auth_checked: bool = False


def get_confluence_auth() -> ConfluenceAuth | None:
    """Read credentials from confluence-cli config, falling back to env vars."""
    global _cached_auth, _auth_checked
    if _auth_checked:
        return _cached_auth

    _auth_checked = True

    # Try confluence-cli config file
    if _CONFIG_PATH.exists():
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            domain = data.get("domain")
            email = data.get("email")
            token = data.get("token")
            if domain and email and token:
                _cached_auth = ConfluenceAuth(domain=domain, email=email, token=token)
                log.debug("Loaded Confluence auth from %s", _CONFIG_PATH)
                return _cached_auth
        except Exception as e:
            log.debug("Failed to read confluence-cli config: %s", e)

    # Fallback to env vars
    import os
    domain = os.environ.get("CONFLUENCE_DOMAIN")
    email = os.environ.get("CONFLUENCE_EMAIL")
    token = os.environ.get("CONFLUENCE_TOKEN")
    if domain and email and token:
        _cached_auth = ConfluenceAuth(domain=domain, email=email, token=token)
        log.debug("Loaded Confluence auth from environment variables")
        return _cached_auth

    log.warning("No Confluence REST auth available (checked %s and env vars)", _CONFIG_PATH)
    return None


def reset_auth_cache() -> None:
    """Reset the cached auth (for testing)."""
    global _cached_auth, _auth_checked
    _cached_auth = None
    _auth_checked = False


async def _request(
    client: httpx.AsyncClient,
    auth: ConfluenceAuth,
    method: str,
    path: str,
    **kwargs: object,
) -> httpx.Response:
    """Make a request with retry-on-429."""
    import asyncio

    url = f"{auth.base_url}{path}"
    for attempt in range(MAX_RETRIES + 1):
        resp = await client.request(
            method, url, auth=auth.basic_auth, **kwargs,
        )
        if resp.status_code != 429 or attempt == MAX_RETRIES:
            resp.raise_for_status()
            return resp

        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            delay = float(retry_after)
        else:
            delay = BACKOFF_BASE * (2 ** attempt)
        log.debug("Rate limited (429), retrying in %.1fs (attempt %d)", delay, attempt + 1)
        await asyncio.sleep(delay)

    return resp  # unreachable but satisfies type checker


async def fetch_page_version(
    page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient,
) -> int | None:
    """Cheap metadata check: returns page version number."""
    try:
        resp = await _request(
            client, auth, "GET",
            f"/content/{page_id}",
            params={"expand": "version"},
        )
        data = resp.json()
        return data.get("version", {}).get("number")
    except Exception as e:
        log.debug("Version check failed for page %s: %s", page_id, e)
        return None


async def fetch_page_body(
    page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient,
) -> tuple[str, str | None, int | None]:
    """Fetch page body, title, and version in one call.

    Returns (html, title, version_number).
    """
    resp = await _request(
        client, auth, "GET",
        f"/content/{page_id}",
        params={"expand": "body.storage,version,title"},
    )
    data = resp.json()
    html = data.get("body", {}).get("storage", {}).get("value", "")
    title = data.get("title")
    version = data.get("version", {}).get("number")
    return html, title, version


async def fetch_child_pages(
    page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient,
) -> list[dict]:
    """Fetch child pages. Returns list of {id, title, version}."""
    results: list[dict] = []
    start = 0
    limit = 25
    while True:
        resp = await _request(
            client, auth, "GET",
            f"/content/{page_id}/child/page",
            params={"expand": "version", "start": str(start), "limit": str(limit)},
        )
        data = resp.json()
        for item in data.get("results", []):
            results.append({
                "id": item["id"],
                "title": item.get("title"),
                "version": item.get("version", {}).get("number"),
            })
        if data.get("size", 0) < limit:
            break
        start += limit
    return results


async def fetch_attachments(
    page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient,
) -> list[dict]:
    """Fetch attachments. Returns list of {id, title, version, download_url, media_type}."""
    results: list[dict] = []
    start = 0
    limit = 25
    while True:
        resp = await _request(
            client, auth, "GET",
            f"/content/{page_id}/child/attachment",
            params={"expand": "version", "start": str(start), "limit": str(limit)},
        )
        data = resp.json()
        for item in data.get("results", []):
            download = item.get("_links", {}).get("download", "")
            results.append({
                "id": item["id"],
                "title": item.get("title"),
                "version": item.get("version", {}).get("number"),
                "download_url": f"https://{auth.domain}/wiki{download}" if download else "",
                "media_type": item.get("metadata", {}).get("mediaType", ""),
            })
        if data.get("size", 0) < limit:
            break
        start += limit
    return results


async def download_attachment(
    url: str, auth: ConfluenceAuth, client: httpx.AsyncClient,
) -> bytes:
    """Download attachment binary content."""
    resp = await client.get(url, auth=auth.basic_auth, follow_redirects=True)
    resp.raise_for_status()
    return resp.content

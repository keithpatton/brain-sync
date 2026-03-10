from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_CONFIG_PATH = Path.home() / ".brain-sync" / "config.json"

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


class _AuthCache:
    """Thread-safe cache for Confluence authentication credentials."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._auth: ConfluenceAuth | None = None
        self._checked: bool = False

    def get(self) -> ConfluenceAuth | None:
        with self._lock:
            if self._checked:
                return self._auth
            self._checked = True

        # Try brain-sync config file (~/.brain-sync/config.json)
        auth = self._load_from_config()
        if auth is None:
            auth = self._load_from_env()

        with self._lock:
            self._auth = auth
        if auth is None:
            log.warning("No Confluence REST auth available (checked %s and env vars)", _CONFIG_PATH)
        return auth

    def reset(self) -> None:
        with self._lock:
            self._auth = None
            self._checked = False

    @staticmethod
    def _load_from_config() -> ConfluenceAuth | None:
        if not _CONFIG_PATH.exists():
            return None
        try:
            data = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
            confluence = data.get("confluence", {})
            domain = confluence.get("domain")
            email = confluence.get("email")
            token = confluence.get("token")
            if domain and email and token:
                log.debug("Loaded Confluence auth from %s", _CONFIG_PATH)
                return ConfluenceAuth(domain=domain, email=email, token=token)
        except Exception as e:
            log.debug("Failed to read brain-sync config: %s", e)
        return None

    @staticmethod
    def _load_from_env() -> ConfluenceAuth | None:
        import os

        domain = os.environ.get("CONFLUENCE_DOMAIN")
        email = os.environ.get("CONFLUENCE_EMAIL")
        token = os.environ.get("CONFLUENCE_TOKEN")
        if domain and email and token:
            log.debug("Loaded Confluence auth from environment variables")
            return ConfluenceAuth(domain=domain, email=email, token=token)
        return None


_auth_cache = _AuthCache()


def get_confluence_auth() -> ConfluenceAuth | None:
    """Read credentials from brain-sync config, falling back to env vars."""
    return _auth_cache.get()


def reset_auth_cache() -> None:
    """Reset the cached auth (for testing)."""
    _auth_cache.reset()


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
            method,
            url,
            auth=auth.basic_auth,
            **kwargs,  # pyright: ignore[reportArgumentType]
        )
        if resp.status_code != 429 or attempt == MAX_RETRIES:
            resp.raise_for_status()
            return resp

        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            delay = float(retry_after)
        else:
            delay = BACKOFF_BASE * (2**attempt)
        log.debug("Rate limited (429), retrying in %.1fs (attempt %d)", delay, attempt + 1)
        await asyncio.sleep(delay)

    return resp  # unreachable but satisfies type checker


async def fetch_page_version(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> int | None:
    """Cheap metadata check: returns page version number."""
    try:
        resp = await _request(
            client,
            auth,
            "GET",
            f"/content/{page_id}",
            params={"expand": "version"},
        )
        data = resp.json()
        return data.get("version", {}).get("number")
    except Exception as e:
        log.debug("Version check failed for page %s: %s", page_id, e)
        return None


async def fetch_page_body(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> tuple[str, str | None, int | None]:
    """Fetch page body, title, and version in one call.

    Returns (html, title, version_number).
    """
    resp = await _request(
        client,
        auth,
        "GET",
        f"/content/{page_id}",
        params={"expand": "body.storage,version,title"},
    )
    data = resp.json()
    html = data.get("body", {}).get("storage", {}).get("value", "")
    title = data.get("title")
    version = data.get("version", {}).get("number")
    return html, title, version


async def fetch_child_pages(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> list[dict]:
    """Fetch child pages. Returns list of {id, title, version}."""
    results: list[dict] = []
    start = 0
    limit = 25
    while True:
        resp = await _request(
            client,
            auth,
            "GET",
            f"/content/{page_id}/child/page",
            params={"expand": "version", "start": str(start), "limit": str(limit)},
        )
        data = resp.json()
        for item in data.get("results", []):
            results.append(
                {
                    "id": item["id"],
                    "title": item.get("title"),
                    "version": item.get("version", {}).get("number"),
                }
            )
        if data.get("size", 0) < limit:
            break
        start += limit
    return results


async def fetch_attachments(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> list[dict]:
    """Fetch attachments. Returns list of {id, title, version, download_url, media_type}."""
    results: list[dict] = []
    start = 0
    limit = 25
    while True:
        resp = await _request(
            client,
            auth,
            "GET",
            f"/content/{page_id}/child/attachment",
            params={"expand": "version", "start": str(start), "limit": str(limit)},
        )
        data = resp.json()
        for item in data.get("results", []):
            download = item.get("_links", {}).get("download", "")
            results.append(
                {
                    "id": item["id"],
                    "title": item.get("title"),
                    "version": item.get("version", {}).get("number"),
                    "download_url": f"https://{auth.domain}/wiki{download}" if download else "",
                    "media_type": item.get("metadata", {}).get("mediaType", ""),
                }
            )
        if data.get("size", 0) < limit:
            break
        start += limit
    return results


async def fetch_comments(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> str | None:
    """Fetch page comments via REST API. Returns markdown string, or None."""
    results: list[dict] = []
    start = 0
    limit = 25
    try:
        while True:
            resp = await _request(
                client,
                auth,
                "GET",
                f"/content/{page_id}/child/comment",
                params={
                    "expand": "body.storage,version",
                    "start": str(start),
                    "limit": str(limit),
                },
            )
            data = resp.json()
            for item in data.get("results", []):
                body_html = item.get("body", {}).get("storage", {}).get("value", "")
                title = item.get("title") or ""
                version = item.get("version", {})
                author = version.get("by", {}).get("displayName", "Unknown")
                when = version.get("when", "")
                results.append(
                    {
                        "author": author,
                        "date": when,
                        "title": title,
                        "body": body_html,
                    }
                )
            if data.get("size", 0) < limit:
                break
            start += limit
    except Exception as e:
        log.debug("Comments fetch failed for page %s: %s", page_id, e)
        return None

    if not results:
        return None

    from brain_sync.converter import html_to_markdown

    lines: list[str] = []
    for c in results:
        header = f"**{c['author']}**"
        if c["date"]:
            header += f" ({c['date']})"
        lines.append(header)
        body_md = html_to_markdown(c["body"]).strip()
        if body_md:
            lines.append(body_md)
        lines.append("")
    return "\n".join(lines).strip()


async def download_attachment(
    url: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> bytes:
    """Download attachment binary content."""
    resp = await client.get(url, auth=auth.basic_auth, follow_redirects=True)
    resp.raise_for_status()
    return resp.content

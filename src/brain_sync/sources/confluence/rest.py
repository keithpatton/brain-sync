from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import httpx

import brain_sync.runtime.config as runtime_config
from brain_sync.sources.base import RemoteSourceMissingError

log = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_BASE = 0.5


@dataclass(frozen=True)
class ConfluenceAuth:
    domain: str
    email: str
    token: str

    @property
    def base_url(self) -> str:
        return f"https://{self.domain}/wiki/api/v2"

    @property
    def basic_auth(self) -> tuple[str, str]:
        return (self.email, self.token)


class _AuthCache:
    """Thread-safe cache for Confluence authentication credentials."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._auth: ConfluenceAuth | None = None
        self._checked = False

    def get(self) -> ConfluenceAuth | None:
        with self._lock:
            if self._checked:
                return self._auth
            self._checked = True

        auth = self._load_from_config()
        if auth is None:
            auth = self._load_from_env()

        with self._lock:
            self._auth = auth
        if auth is None:
            log.warning(
                "No Confluence REST auth available (checked %s and env vars)",
                runtime_config.config_file_path(),
            )
        return auth

    def reset(self) -> None:
        with self._lock:
            self._auth = None
            self._checked = False

    @staticmethod
    def _load_from_config() -> ConfluenceAuth | None:
        config_file = runtime_config.config_file_path()
        if not config_file.exists():
            return None
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            confluence = data.get("confluence", {})
            domain = confluence.get("domain")
            email = confluence.get("email")
            token = confluence.get("token")
            if domain and email and token:
                log.debug("Loaded Confluence auth from %s", config_file)
                return ConfluenceAuth(domain=domain, email=email, token=token)
        except Exception as exc:
            log.debug("Failed to read brain-sync config: %s", exc)
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
        delay = float(retry_after) if retry_after else BACKOFF_BASE * (2**attempt)
        log.debug("Rate limited (429), retrying in %.1fs (attempt %d)", delay, attempt + 1)
        await asyncio.sleep(delay)

    return resp


async def fetch_page_version(page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient) -> int | None:
    """Cheap metadata check: returns page version number."""
    try:
        resp = await _request(client, auth, "GET", f"/pages/{page_id}")
        data = resp.json()
        return data.get("version", {}).get("number")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise RemoteSourceMissingError(
                source_type="confluence",
                source_id=page_id,
                details=f"Confluence page {page_id} returned 404 during version check",
            ) from exc
        log.debug("Version check failed for page %s: %s", page_id, exc)
        return None
    except Exception as exc:
        log.debug("Version check failed for page %s: %s", page_id, exc)
        return None


async def fetch_page_body(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> tuple[str, str | None, int | None]:
    """Fetch page body, title, and version in one call."""
    try:
        resp = await _request(
            client,
            auth,
            "GET",
            f"/pages/{page_id}",
            params={"body-format": "storage"},
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise RemoteSourceMissingError(
                source_type="confluence",
                source_id=page_id,
                details=f"Confluence page {page_id} returned 404 during body fetch",
            ) from exc
        raise
    data = resp.json()
    html = data.get("body", {}).get("storage", {}).get("value", "")
    title = data.get("title")
    version = data.get("version", {}).get("number")
    return html, title, version


async def fetch_child_pages(page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient) -> list[dict]:
    """Fetch child pages. Returns list of {id, title}."""
    results: list[dict] = []
    cursor: str | None = None
    limit = 250
    while True:
        params: dict[str, str] = {"limit": str(limit)}
        if cursor:
            params["cursor"] = cursor
        resp = await _request(
            client,
            auth,
            "GET",
            f"/pages/{page_id}/children",
            params=params,
        )
        data = resp.json()
        for item in data.get("results", []):
            results.append(
                {
                    "id": item["id"],
                    "title": item.get("title"),
                }
            )
        cursor = _next_cursor(data)
        if cursor is None:
            break
    return results


async def fetch_attachments(page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient) -> list[dict]:
    """Fetch attachments. Returns list of metadata dictionaries."""
    results: list[dict] = []
    cursor: str | None = None
    limit = 250
    while True:
        params: dict[str, str] = {"limit": str(limit)}
        if cursor:
            params["cursor"] = cursor
        resp = await _request(
            client,
            auth,
            "GET",
            f"/pages/{page_id}/attachments",
            params=params,
        )
        data = resp.json()
        for item in data.get("results", []):
            download = item.get("downloadLink") or item.get("_links", {}).get("download", "")
            results.append(
                {
                    "id": item["id"],
                    "title": item.get("title"),
                    "version": item.get("version", {}).get("number"),
                    "download_url": _absolute_wiki_url(auth.domain, download),
                    "media_type": item.get("mediaType", ""),
                }
            )
        cursor = _next_cursor(data)
        if cursor is None:
            break
    return results


async def fetch_comments(page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient) -> str | None:
    """Fetch page comments and return rendered markdown, or None."""
    from brain_sync.sources.confluence.comments import fetch_structured_comments
    from brain_sync.sources.conversion import format_comments

    try:
        comments = await fetch_structured_comments(page_id, auth, client)
    except Exception as exc:
        log.debug("Comments fetch failed for page %s: %s", page_id, exc)
        return None

    if not comments:
        return None
    return format_comments(comments)


async def fetch_users_by_account_ids(
    account_ids: list[str],
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> dict[str, str]:
    """Resolve account IDs to display names using one bulk lookup."""
    if not account_ids:
        return {}

    requested = sorted({account_id for account_id in account_ids if account_id})
    if not requested:
        return {}

    resp = await _request(
        client,
        auth,
        "POST",
        "/users-bulk",
        json={"accountIds": requested},
    )
    data = resp.json()
    return {
        item["accountId"]: item.get("displayName") or item.get("publicName") or item["accountId"]
        for item in data.get("results", [])
        if item.get("accountId")
    }


async def download_attachment(url: str, auth: ConfluenceAuth, client: httpx.AsyncClient) -> bytes:
    """Download attachment binary content."""
    resp = await client.get(url, auth=auth.basic_auth, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def _next_cursor(data: dict) -> str | None:
    next_link = data.get("_links", {}).get("next")
    if not next_link:
        return None
    query = parse_qs(urlparse(next_link).query)
    values = query.get("cursor")
    return values[0] if values else None


def _absolute_wiki_url(domain: str, url_or_path: str) -> str:
    if not url_or_path:
        return ""
    if url_or_path.startswith("http://") or url_or_path.startswith("https://"):
        return url_or_path
    if url_or_path.startswith("/wiki/"):
        return f"https://{domain}{url_or_path}"
    if url_or_path.startswith("/"):
        return f"https://{domain}/wiki{url_or_path}"
    return f"https://{domain}/wiki/{url_or_path.lstrip('/')}"


__all__ = [
    "BACKOFF_BASE",
    "MAX_RETRIES",
    "ConfluenceAuth",
    "_request",
    "download_attachment",
    "fetch_attachments",
    "fetch_child_pages",
    "fetch_comments",
    "fetch_page_body",
    "fetch_page_version",
    "fetch_users_by_account_ids",
    "get_confluence_auth",
    "reset_auth_cache",
]

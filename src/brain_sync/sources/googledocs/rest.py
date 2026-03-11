"""Google Docs REST client — fetch via HTML export with OAuth2 or gcloud auth."""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from brain_sync.sources.googledocs.auth import GoogleOAuthCredentials, _GcloudFallbackCredentials

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 30.0
SUBPROCESS_TIMEOUT = 15


class FetchError(Exception):
    pass


def _gcloud_cmd() -> str:
    """Resolve the gcloud command, checking PATH and standard install locations."""
    if sys.platform == "win32":
        cmd = shutil.which("gcloud.cmd") or shutil.which("gcloud")
        if cmd is None:
            import os

            for base in [
                os.path.join(os.environ.get("LOCALAPPDATA", ""), "Google", "Cloud SDK"),
                os.path.join(os.environ.get("PROGRAMFILES", ""), "Google", "google-cloud-sdk"),
            ]:
                candidate = os.path.join(base, "google-cloud-sdk", "bin", "gcloud.cmd")
                if os.path.isfile(candidate):
                    cmd = candidate
                    break
    else:
        cmd = shutil.which("gcloud")
    if cmd is None:
        raise FileNotFoundError("gcloud not found on PATH. Install from https://cloud.google.com/sdk")
    return cmd


async def _get_access_token() -> str:
    """Get a fresh OAuth access token via gcloud."""
    cmd = _gcloud_cmd()
    proc = await asyncio.create_subprocess_exec(
        cmd,
        "auth",
        "print-access-token",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SUBPROCESS_TIMEOUT)
    except TimeoutError:
        proc.kill()
        raise FetchError("gcloud auth print-access-token timed out") from None

    if proc.returncode != 0:
        raise FetchError(f"gcloud auth failed (exit {proc.returncode}): {stderr.decode().strip()}")

    token = stdout.decode().strip()
    if not token:
        raise FetchError("gcloud returned empty access token — run 'gcloud auth login' first")
    return token


async def fetch_doc_html(
    doc_id: str, auth: GoogleOAuthCredentials | _GcloudFallbackCredentials, client: httpx.AsyncClient
) -> str:
    """Fetch Google Doc as HTML via export endpoint."""
    token = await auth.get_token()
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=html"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = await client.get(url, headers=headers, follow_redirects=True, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise FetchError(f"Google Docs fetch failed for {doc_id}: {e}") from e
    return response.text


async def fetch_doc_title(
    doc_id: str, auth: GoogleOAuthCredentials | _GcloudFallbackCredentials, client: httpx.AsyncClient
) -> str | None:
    """Fetch Google Doc title via Docs API v1 (lightweight metadata only).

    Uses the Docs API rather than Drive API because shared docs that haven't
    been added to "My Drive" are invisible to the Drive API but accessible
    via the Docs API with documents.readonly scope.
    """
    token = await auth.get_token()
    url = f"https://docs.googleapis.com/v1/documents/{doc_id}"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"fields": "title"}
    try:
        response = await client.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        return response.json().get("title")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            log.debug("Google Doc not found (no access?): %s", doc_id)
        else:
            log.debug("Docs API title fetch failed for %s: %s", doc_id, e)
        return None
    except httpx.HTTPError:
        log.debug("Docs API title fetch failed for %s", doc_id, exc_info=True)
        return None


def extract_title_from_html(html: str) -> str | None:
    """Extract <title> from Google Docs HTML export."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    tag = tree.css_first("title")
    if not tag or not tag.text():
        return None
    text = tag.text().strip()
    return text or None

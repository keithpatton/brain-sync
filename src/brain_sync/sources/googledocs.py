from __future__ import annotations

import asyncio
import logging
import shutil
import sys

import httpx

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
            # Check standard Windows install locations
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


async def googledocs_fetch(doc_id: str, client: httpx.AsyncClient) -> str:
    """Fetch Google Doc as HTML via the export endpoint with gcloud auth.

    Returns raw HTML string.
    """
    token = await _get_access_token()
    url = f"https://docs.google.com/document/d/{doc_id}/export?format=html"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        response = await client.get(url, headers=headers, follow_redirects=True, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise FetchError(f"Google Docs fetch failed for {doc_id}: {e}") from e

    return response.text

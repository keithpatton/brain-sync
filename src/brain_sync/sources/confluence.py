from __future__ import annotations

import asyncio
import logging
import shutil
import sys

log = logging.getLogger(__name__)

SUBPROCESS_TIMEOUT = 60


def _confluence_cmd() -> str:
    """Resolve the confluence command, preferring .cmd on Windows."""
    if sys.platform == "win32":
        cmd = shutil.which("confluence.cmd") or shutil.which("confluence")
    else:
        cmd = shutil.which("confluence")
    if cmd is None:
        raise FileNotFoundError("confluence-cli not found on PATH")
    return cmd


class FetchError(Exception):
    pass


async def confluence_metadata(page_id: str) -> str | None:
    """Fetch page version number via confluence-cli as a cheap metadata check.

    Returns version string, or None if metadata check is not supported/fails.
    """
    try:
        cmd = _confluence_cmd()
        proc = await asyncio.create_subprocess_exec(
            cmd, "read", page_id, "--format", "json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=SUBPROCESS_TIMEOUT
        )
        if proc.returncode != 0:
            log.debug("Confluence metadata check failed: %s", stderr.decode())
            return None
        import json
        data = json.loads(stdout.decode("utf-8"))
        version = data.get("version", {}).get("number")
        return str(version) if version is not None else None
    except Exception as e:
        log.debug("Confluence metadata check unavailable: %s", e)
        return None


async def confluence_fetch(page_id: str) -> str:
    """Fetch page HTML content via confluence-cli.

    Returns raw HTML string.
    """
    cmd = _confluence_cmd()
    proc = await asyncio.create_subprocess_exec(
        cmd, "read", page_id,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=SUBPROCESS_TIMEOUT
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise FetchError(f"Confluence fetch timed out for page {page_id}")

    if proc.returncode != 0:
        raise FetchError(
            f"confluence read failed (exit {proc.returncode}): {stderr.decode().strip()}"
        )

    return stdout.decode("utf-8")


async def confluence_comments(page_id: str) -> str | None:
    """Fetch page comments as markdown via confluence-cli.

    Returns markdown string, or None if no comments or fetch fails.
    """
    try:
        cmd = _confluence_cmd()
        proc = await asyncio.create_subprocess_exec(
            cmd, "comments", page_id, "--format", "markdown", "--all",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=SUBPROCESS_TIMEOUT
        )
        if proc.returncode != 0:
            log.debug("Confluence comments fetch failed: %s", stderr.decode())
            return None
        text = stdout.decode("utf-8").strip()
        return text if text else None
    except Exception as e:
        log.debug("Confluence comments unavailable: %s", e)
        return None

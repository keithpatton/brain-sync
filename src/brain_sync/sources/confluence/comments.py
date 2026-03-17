"""Structured comment parsing for Confluence pages."""

from __future__ import annotations

import logging

import httpx

from brain_sync.sources.base import Comment
from brain_sync.sources.confluence.rest import ConfluenceAuth, _request

log = logging.getLogger(__name__)


async def fetch_structured_comments(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> list[Comment]:
    """Paginated comment fetch returning structured Comment objects."""
    comments: list[Comment] = []
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
                version = item.get("version", {})
                author = version.get("by", {}).get("displayName", "Unknown")
                when = version.get("when", "")
                comments.append(
                    Comment(
                        author=author,
                        created=when,
                        content=body_html,
                    )
                )
            if data.get("size", 0) < limit:
                break
            start += limit
    except Exception as e:
        log.debug("Comments fetch failed for page %s: %s", page_id, e)
        return []

    return comments

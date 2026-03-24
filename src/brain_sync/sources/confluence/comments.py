"""Structured comment parsing for Confluence pages."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

import httpx

from brain_sync.sources.base import Comment
from brain_sync.sources.confluence.rest import (
    ConfluenceAuth,
    _absolute_wiki_url,
    _request,
    fetch_users_by_account_ids,
)

log = logging.getLogger(__name__)


async def fetch_structured_comments(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> list[Comment]:
    """Fetch page inline/footer comments, preserving threads and anchor metadata."""
    try:
        inline_items = await _fetch_comment_collection(
            f"/pages/{page_id}/inline-comments",
            auth=auth,
            client=client,
        )
        footer_items = await _fetch_comment_collection(
            f"/pages/{page_id}/footer-comments",
            auth=auth,
            client=client,
        )
    except Exception as e:
        log.debug("Comments fetch failed for page %s: %s", page_id, e)
        return []

    root_entries = [{"kind": "inline", "item": item} for item in inline_items] + [
        {"kind": "footer", "item": item} for item in footer_items
    ]

    try:
        child_lists = await _fetch_children_for_roots(root_entries, auth=auth, client=client)
    except Exception as e:
        log.debug("Child comments fetch failed for page %s: %s", page_id, e)
        child_lists = {}

    author_ids = _collect_author_ids(root_entries, child_lists)
    try:
        author_names = await fetch_users_by_account_ids(author_ids, auth, client)
    except Exception as e:
        log.debug("Author lookup failed for page %s: %s", page_id, e)
        author_names = {}

    comments = [
        _build_comment(entry["item"], entry["kind"], author_names, child_lists.get(entry["item"]["id"], []), auth)
        for entry in root_entries
    ]
    comments.sort(key=lambda comment: comment.created or "", reverse=True)
    return comments


async def _fetch_comment_collection(
    path: str,
    *,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> list[dict]:
    results: list[dict] = []
    cursor: str | None = None
    limit = 250
    while True:
        params: dict[str, str] = {"body-format": "storage", "limit": str(limit)}
        if cursor:
            params["cursor"] = cursor
        resp = await _request(client, auth, "GET", path, params=params)
        data = resp.json()
        results.extend(data.get("results", []))
        cursor = _next_cursor(data)
        if cursor is None:
            return results


async def _fetch_children_for_roots(
    root_entries: list[dict],
    *,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> dict[str, list[dict]]:
    children_by_parent: dict[str, list[dict]] = {}
    for entry in root_entries:
        item = entry["item"]
        parent_id = item["id"]
        path = f"/{entry['kind']}-comments/{parent_id}/children"
        children_by_parent[parent_id] = await _fetch_comment_collection(path, auth=auth, client=client)
    return children_by_parent


def _build_comment(
    item: dict,
    comment_type: str,
    author_names: dict[str, str],
    children: list[dict],
    auth: ConfluenceAuth,
) -> Comment:
    version = item.get("version", {})
    author_id = version.get("authorId")
    resolution_status = item.get("resolutionStatus")
    properties = item.get("properties", {})
    return Comment(
        id=item.get("id"),
        author=author_names.get(author_id, author_id or "Unknown"),
        author_id=author_id,
        created=version.get("createdAt", ""),
        content=_body_storage_value(item.get("body", {})),
        comment_type=comment_type,
        parent_id=item.get("parentCommentId"),
        status=item.get("status"),
        resolved=resolution_status == "resolved",
        resolution_status=resolution_status,
        anchor_text=properties.get("inlineOriginalSelection"),
        anchor_ref=properties.get("inlineMarkerRef"),
        webui_link=_absolute_wiki_url(auth.domain, item.get("_links", {}).get("webui", "")),
        replies=[
            _build_comment(child, comment_type, author_names, [], auth)
            for child in sorted(children, key=lambda child: child.get("version", {}).get("createdAt", ""))
        ],
    )


def _body_storage_value(body: dict) -> str:
    return body.get("storage", {}).get("value", "")


def _collect_author_ids(root_entries: list[dict], child_lists: dict[str, list[dict]]) -> list[str]:
    author_ids: set[str] = set()
    for entry in root_entries:
        author_id = entry["item"].get("version", {}).get("authorId")
        if author_id:
            author_ids.add(author_id)
        for child in child_lists.get(entry["item"]["id"], []):
            child_author_id = child.get("version", {}).get("authorId")
            if child_author_id:
                author_ids.add(child_author_id)
    return sorted(author_ids)


def _next_cursor(data: dict) -> str | None:
    next_link = data.get("_links", {}).get("next")
    if not next_link:
        return None
    query = parse_qs(urlparse(next_link).query)
    values = query.get("cursor")
    return values[0] if values else None

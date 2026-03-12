"""Google Docs REST client — fetch via HTML export with OAuth2."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from brain_sync.sources.googledocs.auth import GoogleOAuthCredentials

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 30.0

SEMANTIC_FINGERPRINT_PREFIX = "gdocs:v1:"


class FetchError(Exception):
    pass


async def fetch_doc_html(
    doc_id: str, auth: GoogleOAuthCredentials, client: httpx.AsyncClient
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
    doc_id: str, auth: GoogleOAuthCredentials, client: httpx.AsyncClient
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


async def fetch_doc_body(
    doc_id: str, auth: GoogleOAuthCredentials, client: httpx.AsyncClient
) -> tuple[str | None, str | None]:
    """Fetch Google Doc title and body text for semantic fingerprinting.

    Returns (title, canonical_text) on success, (None, None) on any HTTP error.
    Uses a tight field mask so only body content is returned (no rendered HTML).
    """
    token = await auth.get_token()
    url = f"https://docs.googleapis.com/v1/documents/{doc_id}"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "fields": (
            "title,"
            "body.content("
            "paragraph(elements(textRun(content)),paragraphStyle(namedStyleType),bullet),"
            "table(tableRows(tableCells(content(paragraph(elements(textRun(content)))))))"
            ")"
        )
    }
    try:
        response = await client.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        doc = response.json()
        title = doc.get("title")
        canonical_text = extract_canonical_text(doc)
        return title, canonical_text
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            log.debug("Google Doc not found (no access?): %s", doc_id)
        else:
            log.debug("Docs API body fetch failed for %s: %s", doc_id, e)
        return None, None
    except httpx.HTTPError:
        log.debug("Docs API body fetch failed for %s", doc_id, exc_info=True)
        return None, None


def extract_canonical_text(doc: dict) -> str:
    """Extract structured text from a Docs API document for semantic fingerprinting.

    Walks body.content recursively, normalising whitespace.  Heading text is
    prefixed with ``H:``, list items with ``LI:``, and table rows with ``T:``.
    Formatting-only changes (bold, colour, font size) do not affect the output.
    """
    parts: list[str] = []
    _walk_body(doc.get("body", {}).get("content", []), parts)
    text = "\n".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _walk_body(content: list[dict], parts: list[str]) -> None:
    for element in content:
        if "paragraph" in element:
            para = element["paragraph"]
            text = "".join(
                e.get("textRun", {}).get("content", "") for e in para.get("elements", [])
            ).strip()
            if not text:
                continue
            style = para.get("paragraphStyle", {}).get("namedStyleType")
            if style and style.startswith("HEADING"):
                parts.append(f"H:{text}")
            elif "bullet" in para:
                parts.append(f"LI:{text}")
            else:
                parts.append(text)
        elif "table" in element:
            for row in element["table"].get("tableRows", []):
                row_cells: list[str] = []
                for cell in row.get("tableCells", []):
                    cell_parts: list[str] = []
                    _walk_body(cell.get("content", []), cell_parts)
                    cell_text = " ".join(cell_parts).strip()
                    if cell_text:
                        row_cells.append(cell_text)
                if row_cells:
                    parts.append("T:" + "|".join(row_cells))


def compute_semantic_fingerprint(text: str) -> str:
    """Return a versioned SHA-256 fingerprint of canonical document text."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{SEMANTIC_FINGERPRINT_PREFIX}{digest}"


@dataclass(frozen=True)
class DocMetadata:
    """Lightweight Google Doc metadata returned by :func:`fetch_doc_metadata`."""

    title: str | None
    revision_id: str | None


async def fetch_doc_metadata(
    doc_id: str, auth: GoogleOAuthCredentials, client: httpx.AsyncClient
) -> DocMetadata:
    """Fetch Google Doc title and revisionId in a single lightweight API call.

    Uses the Docs API ``documents.get`` with a field mask so only metadata is
    returned, not the full document body.
    """
    token = await auth.get_token()
    url = f"https://docs.googleapis.com/v1/documents/{doc_id}"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"fields": "title,revisionId"}
    try:
        response = await client.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        log.debug("Docs API metadata for %s: %s", doc_id, data)
        return DocMetadata(title=data.get("title"), revision_id=data.get("revisionId"))
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            log.debug("Google Doc not found (no access?): %s", doc_id)
        else:
            log.debug("Docs API metadata fetch failed for %s: %s", doc_id, e)
        return DocMetadata(title=None, revision_id=None)
    except httpx.HTTPError:
        log.debug("Docs API metadata fetch failed for %s", doc_id, exc_info=True)
        return DocMetadata(title=None, revision_id=None)


def extract_title_from_html(html: str) -> str | None:
    """Extract <title> from Google Docs HTML export."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    tag = tree.css_first("title")
    if not tag or not tag.text():
        return None
    text = tag.text().strip()
    return text or None

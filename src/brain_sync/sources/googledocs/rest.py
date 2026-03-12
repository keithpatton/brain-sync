"""Google Docs REST client — fetch via Docs API tabs endpoint with OAuth2."""

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

SEMANTIC_FINGERPRINT_PREFIX = "gdocs:v2:"


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class TabData:
    """Content and identity of a single document tab."""

    tab_id: str
    title: str  # resolved: raw title or f"Untitled Tab ({tab_id})"
    body_content: list[dict]


@dataclass(frozen=True)
class TabsDocument:
    """Full Google Doc content across all tabs, as returned by the tabs API."""

    title: str | None
    tabs: list[TabData]  # order preserved as returned by API


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


async def fetch_all_tabs(
    doc_id: str, auth: GoogleOAuthCredentials, client: httpx.AsyncClient
) -> TabsDocument | None:
    """Fetch all tab content from a Google Doc via the Docs API tabs endpoint.

    Returns a TabsDocument containing all document tabs in the order returned
    by the API.  Non-document tab types are skipped.  Returns None on any HTTP
    error, network failure, or if the response contains no document tabs
    (to prevent blank-but-successful syncs).
    """
    token = await auth.get_token()
    url = f"https://docs.googleapis.com/v1/documents/{doc_id}"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "fields": (
            "title,"
            "tabs.tabProperties,"
            "tabs.documentTab.body.content("
            "paragraph(elements(textRun(content)),paragraphStyle(namedStyleType),bullet),"
            "table(tableRows(tableCells(content(paragraph(elements(textRun(content)))))))"
            ")"
        ),
        "includeTabsContent": "true",
    }
    try:
        response = await client.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            log.debug("Google Doc not found (no access?): %s", doc_id)
        else:
            log.debug("Docs API tabs fetch failed for %s: %s", doc_id, e)
        return None
    except httpx.HTTPError:
        log.debug("Docs API tabs fetch failed for %s", doc_id, exc_info=True)
        return None

    raw_tabs = data.get("tabs")
    if not raw_tabs:
        log.warning("Docs API returned no tabs for %s", doc_id)
        return None

    tabs: list[TabData] = []
    for raw_tab in raw_tabs:
        if "documentTab" not in raw_tab:
            # Skip non-document tab types
            continue
        props = raw_tab.get("tabProperties", {})
        tab_id = props.get("tabId", "unknown")
        raw_title = props.get("title", "").strip()
        title = raw_title or f"Untitled Tab ({tab_id})"
        body_content = raw_tab["documentTab"].get("body", {}).get("content", [])
        tabs.append(TabData(tab_id=tab_id, title=title, body_content=body_content))

    if not tabs:
        log.warning("Docs API returned no document tabs for %s", doc_id)
        return None

    return TabsDocument(title=data.get("title"), tabs=tabs)


def extract_canonical_text(tabs_doc: TabsDocument) -> str:
    """Extract structured text from all tabs for semantic fingerprinting.

    Each tab is prefixed with ``TAB:<title>`` so tab identity (including
    renames) contributes to the fingerprint.  Heading text is prefixed with
    ``H:``, list items with ``LI:``, and table rows with ``T:``.
    Formatting-only changes (bold, colour, font size) do not affect the output.
    """
    parts: list[str] = []
    for tab in tabs_doc.tabs:
        parts.append(f"TAB:{tab.title}")
        _walk_body(tab.body_content, parts)
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


_HEADING_LEVELS: dict[str, str] = {
    "HEADING_1": "#",
    "HEADING_2": "##",
    "HEADING_3": "###",
    "HEADING_4": "####",
    "HEADING_5": "#####",
    "HEADING_6": "######",
}


def _walk_body_markdown(content: list[dict], parts: list[str]) -> None:
    """Walk Docs API body content and emit standard markdown strings.

    Separate from _walk_body, which emits fingerprint notation (H:, LI:, T:).
    """
    for element in content:
        if "paragraph" in element:
            para = element["paragraph"]
            text = "".join(
                e.get("textRun", {}).get("content", "") for e in para.get("elements", [])
            ).strip()
            if not text:
                continue
            style = para.get("paragraphStyle", {}).get("namedStyleType", "")
            if style in _HEADING_LEVELS:
                parts.append(f"{_HEADING_LEVELS[style]} {text}")
            elif "bullet" in para:
                parts.append(f"- {text}")
            else:
                parts.append(text)
        elif "table" in element:
            rows = element["table"].get("tableRows", [])
            for i, row in enumerate(rows):
                row_cells: list[str] = []
                for cell in row.get("tableCells", []):
                    cell_parts: list[str] = []
                    _walk_body_markdown(cell.get("content", []), cell_parts)
                    row_cells.append(" ".join(cell_parts).strip())
                parts.append("| " + " | ".join(row_cells) + " |")
                if i == 0:
                    # Header separator row required for standard markdown tables
                    parts.append("| " + " | ".join("---" for _ in row_cells) + " |")


def generate_tabs_markdown(tabs_doc: TabsDocument) -> str:
    """Render all tabs of a Google Doc as markdown.

    Each tab is introduced with a level-2 heading.  Multiple tabs are
    separated by a horizontal rule.  Uses _walk_body_markdown (not _walk_body)
    to produce valid markdown rather than fingerprint notation.
    """
    sections: list[str] = []
    for tab in tabs_doc.tabs:
        parts: list[str] = [f"## {tab.title}", ""]
        _walk_body_markdown(tab.body_content, parts)
        sections.append("\n".join(parts))
    return "\n\n---\n\n".join(sections)


def extract_title_from_html(html: str) -> str | None:
    """Extract <title> from Google Docs HTML export."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    tag = tree.css_first("title")
    if not tag or not tag.text():
        return None
    text = tag.text().strip()
    return text or None

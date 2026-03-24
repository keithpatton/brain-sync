"""Google Docs REST client — fetch via Docs API tabs endpoint with OAuth2."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from brain_sync.sources.googledocs.auth import GoogleOAuthCredentials

log = logging.getLogger(__name__)

HTTP_TIMEOUT = 30.0

SEMANTIC_FINGERPRINT_PREFIX = "gdocs:v3:"


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class InlineImageInfo:
    """Metadata for an inline image object within a Google Doc."""

    object_id: str
    content_uri: str
    title: str | None = None
    description: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class TabData:
    """Content and identity of a single document tab."""

    tab_id: str
    title: str  # resolved: raw title or f"Untitled Tab ({tab_id})"
    number: str  # dotted position: "1", "2", "3.1", "3.1.1"
    body_content: list[dict]
    inline_objects: dict[str, InlineImageInfo] = field(default_factory=dict)


@dataclass(frozen=True)
class TabsDocument:
    """Full Google Doc content across all tabs, as returned by the tabs API."""

    title: str | None
    tabs: list[TabData]  # order preserved as returned by API


@dataclass(frozen=True)
class DriveDocMetadata:
    """Lightweight Google Drive metadata used for preflight change checks."""

    title: str | None
    version: str | None


async def fetch_doc_html(doc_id: str, auth: GoogleOAuthCredentials, client: httpx.AsyncClient) -> str:
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


async def fetch_drive_metadata(
    doc_id: str,
    auth: GoogleOAuthCredentials,
    client: httpx.AsyncClient,
) -> DriveDocMetadata | None:
    """Fetch lightweight Google Drive metadata for a doc by file ID.

    Uses Drive metadata for cheap change detection before falling back to the
    heavier Docs API content fetch. ``supportsAllDrives=true`` keeps shared-drive
    docs readable through the same code path.
    """
    token = await auth.get_token()
    url = f"https://www.googleapis.com/drive/v3/files/{doc_id}"
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "fields": "name,version",
        "supportsAllDrives": "true",
    }
    try:
        response = await client.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            log.debug("Drive metadata not found (no access?): %s", doc_id)
        else:
            log.debug("Drive metadata fetch failed for %s: %s", doc_id, e)
        return None
    except httpx.HTTPError:
        log.debug("Drive metadata fetch failed for %s", doc_id, exc_info=True)
        return None

    return DriveDocMetadata(
        title=data.get("name"),
        version=data.get("version"),
    )


async def fetch_doc_title(doc_id: str, auth: GoogleOAuthCredentials, client: httpx.AsyncClient) -> str | None:
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


def _flatten_tabs(raw_tabs: list[dict], prefix: str = "") -> list[tuple[str, dict]]:
    """Recursively flatten nested tabs, returning (number, raw_tab) pairs.

    Top-level: "1", "2", "3"
    Children of tab 3: "3.1", "3.2"
    Deeply nested: "3.1.1"
    """
    result: list[tuple[str, dict]] = []
    for i, raw_tab in enumerate(raw_tabs, 1):
        num = f"{prefix}{i}"
        result.append((num, raw_tab))
        children = raw_tab.get("childTabs", [])
        if children:
            result.extend(_flatten_tabs(children, prefix=f"{num}."))
    return result


def _extract_inline_objects(raw_inline_objects: dict) -> dict[str, InlineImageInfo]:
    """Extract InlineImageInfo from the Docs API inlineObjects map."""
    result: dict[str, InlineImageInfo] = {}
    for obj_id, obj_data in raw_inline_objects.items():
        props = obj_data.get("inlineObjectProperties", {})
        embedded = props.get("embeddedObject", {})
        image_props = embedded.get("imageProperties", {})
        content_uri = image_props.get("contentUri")
        if not content_uri:
            continue
        result[obj_id] = InlineImageInfo(
            object_id=obj_id,
            content_uri=content_uri,
            title=embedded.get("title") or None,
            description=embedded.get("description") or None,
            mime_type=None,  # MIME detected from Content-Type header during download
        )
    return result


async def fetch_all_tabs(doc_id: str, auth: GoogleOAuthCredentials, client: httpx.AsyncClient) -> TabsDocument | None:
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
        "fields": "title,tabs",
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
    for number, raw_tab in _flatten_tabs(raw_tabs):
        if "documentTab" not in raw_tab:
            # Skip non-document tab types
            continue
        props = raw_tab.get("tabProperties", {})
        tab_id = props.get("tabId", "unknown")
        raw_title = props.get("title", "").strip()
        title = raw_title or f"Untitled Tab ({tab_id})"
        doc_tab = raw_tab["documentTab"]
        body_content = doc_tab.get("body", {}).get("content", [])
        inline_objects = _extract_inline_objects(doc_tab.get("inlineObjects", {}))
        tabs.append(
            TabData(tab_id=tab_id, title=title, number=number, body_content=body_content, inline_objects=inline_objects)
        )

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
        parts.append(f"TAB:{tab.number}:{tab.title}")
        _walk_body(tab.body_content, parts)
    text = "\n".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _walk_body(content: list[dict], parts: list[str]) -> None:
    for element in content:
        if "paragraph" in element:
            para = element["paragraph"]
            text_parts: list[str] = []
            for e in para.get("elements", []):
                text = _extract_paragraph_element_text(e)
                if text:
                    text_parts.append(text)
                elif "inlineObjectElement" in e:
                    obj_id = e["inlineObjectElement"].get("inlineObjectId", "")
                    if obj_id:
                        parts.append(f"IMG:{obj_id}")
            text = "".join(text_parts).strip()
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


def _walk_body_markdown(
    content: list[dict],
    parts: list[str],
    inline_objects: dict[str, InlineImageInfo] | None = None,
    doc_id: str | None = None,
) -> None:
    """Walk Docs API body content and emit standard markdown strings.

    Separate from _walk_body, which emits fingerprint notation (H:, LI:, T:).
    When inline_objects and doc_id are provided, inlineObjectElement entries
    are rendered as ``![alt](attachment-ref:gdoc-image:{doc_id}:{objectId})``.
    """
    for element in content:
        if "paragraph" in element:
            para = element["paragraph"]
            # Build paragraph content handling both text runs and inline images
            inline_parts: list[str] = []
            for e in para.get("elements", []):
                text = _extract_paragraph_element_text(e)
                if text:
                    inline_parts.append(text)
                elif "inlineObjectElement" in e and inline_objects and doc_id:
                    obj_id = e["inlineObjectElement"].get("inlineObjectId", "")
                    img = inline_objects.get(obj_id)
                    if img:
                        alt = img.description or img.title or "image"
                        inline_parts.append(f"![{alt}](attachment-ref:gdoc-image:{doc_id}:{obj_id})")
            text = "".join(inline_parts).strip()
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
                    _walk_body_markdown(cell.get("content", []), cell_parts, inline_objects, doc_id)
                    row_cells.append(" ".join(cell_parts).strip())
                parts.append("| " + " | ".join(row_cells) + " |")
                if i == 0:
                    # Header separator row required for standard markdown tables
                    parts.append("| " + " | ".join("---" for _ in row_cells) + " |")


def _extract_paragraph_element_text(element: dict) -> str:
    """Return the display text for one Docs API paragraph element."""
    if "textRun" in element:
        return element["textRun"].get("content", "")
    if "person" in element:
        props = element["person"].get("personProperties", {})
        return props.get("name") or props.get("email") or ""
    if "dateElement" in element:
        props = element["dateElement"].get("dateElementProperties", {})
        return props.get("displayText") or props.get("timestamp") or ""
    if "richLink" in element:
        props = element["richLink"].get("richLinkProperties", {})
        return props.get("title") or props.get("uri") or ""
    return ""


def generate_tabs_markdown(tabs_doc: TabsDocument, doc_id: str | None = None) -> str:
    """Render all tabs of a Google Doc as markdown.

    Multi-tab documents use H1 headings with dotted numbering (``# Tab 1 — Title``).
    Single-tab documents keep ``## Title`` to avoid noise.
    Multiple tabs are separated by a horizontal rule.
    """
    multi = len(tabs_doc.tabs) > 1
    sections: list[str] = []
    for tab in tabs_doc.tabs:
        if multi:
            heading = f"# Tab {tab.number} \u2014 {tab.title}"
        else:
            heading = f"## {tab.title}"
        parts: list[str] = [heading, ""]
        _walk_body_markdown(tab.body_content, parts, tab.inline_objects, doc_id)
        sections.append("\n".join(parts))
    return "\n\n---\n\n".join(sections)


_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

_MAX_SLUG_LEN = 80


def image_filename(object_id: str, title: str | None, description: str | None, mime_type: str | None) -> str:
    """Compute a filename for an inline image: a{objectId}-{slug}.{ext}."""
    from pathlib import Path

    from brain_sync.sources import slugify

    # Slug priority: title → description → objectId
    raw = title or description or object_id
    slug = slugify(raw)[:_MAX_SLUG_LEN]

    # Extension: MIME-derived → title-derived → .bin
    ext = _MIME_TO_EXT.get(mime_type or "")
    if not ext and title:
        title_ext = Path(title).suffix.lower()
        if title_ext:
            ext = title_ext
    if not ext:
        ext = ".bin"

    return f"a{object_id}-{slug}{ext}"


def extract_title_from_html(html: str) -> str | None:
    """Extract <title> from Google Docs HTML export."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    tag = tree.css_first("title")
    if not tag or not tag.text():
        return None
    text = tag.text().strip()
    return text or None

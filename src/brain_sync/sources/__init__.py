from __future__ import annotations

import re
from enum import Enum


class SourceType(Enum):
    CONFLUENCE = "confluence"
    GOOGLE_DOCS = "googledocs"


class UnsupportedSourceError(Exception):
    pass


class URLParseError(Exception):
    pass


def detect_source_type(url: str) -> SourceType:
    if "atlassian.net/wiki/" in url:
        return SourceType.CONFLUENCE
    if "docs.google.com/document/" in url:
        return SourceType.GOOGLE_DOCS
    raise UnsupportedSourceError(f"Cannot determine source type for: {url}")


_CONFLUENCE_PAGE_ID_RE = re.compile(r"/pages/(\d+)")
_CONFLUENCE_VIEWPAGE_RE = re.compile(r"[?&]pageId=(\d+)")
_CONFLUENCE_FALLBACK_RE = re.compile(r"/(\d+)(?:[/?#]|$)")


def extract_confluence_page_id(url: str) -> str:
    m = _CONFLUENCE_PAGE_ID_RE.search(url)
    if not m:
        m = _CONFLUENCE_VIEWPAGE_RE.search(url)
    if not m:
        m = _CONFLUENCE_FALLBACK_RE.search(url)
    if not m:
        raise URLParseError(f"Cannot extract Confluence page ID from: {url}")
    return m.group(1)


def try_extract_confluence_page_id(url: str) -> str | None:
    """Like extract_confluence_page_id but returns None instead of raising."""
    try:
        return extract_confluence_page_id(url)
    except URLParseError:
        return None


_GDOCS_ID_RE = re.compile(r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)")


def extract_google_doc_id(url: str) -> str:
    m = _GDOCS_ID_RE.search(url)
    if not m:
        raise URLParseError(f"Cannot extract Google Doc ID from: {url}")
    return m.group(1)


def slugify(title: str) -> str:
    """Convert a document title to a safe, kebab-case filename stem."""
    s = title.lower()
    s = re.sub(r"[^\w\s-]", "", s)  # remove non-word chars except spaces/hyphens
    s = re.sub(r"[\s_]+", "-", s)  # spaces/underscores to hyphens
    s = re.sub(r"-{2,}", "-", s)  # collapse multiple hyphens
    s = s.strip("-")
    return s or "untitled"


def canonical_id(source_type: SourceType, url: str) -> str:
    """Return a stable canonical ID for a source URL."""
    if source_type == SourceType.CONFLUENCE:
        page_id = extract_confluence_page_id(url)
        return f"confluence:{page_id}"
    if source_type == SourceType.GOOGLE_DOCS:
        doc_id = extract_google_doc_id(url)
        return f"gdoc:{doc_id}"
    raise UnsupportedSourceError(f"Cannot create canonical ID for: {url}")


def canonical_filename(source_type: SourceType, doc_id: str, title: str | None) -> str:
    """Generate an ID-anchored, title-decorated filename.

    Examples:
        c123456-traveller-profile-service-erd.md
        g1A2B3C-product-prd.md
    """
    if source_type == SourceType.CONFLUENCE:
        prefix = f"c{doc_id}"
    elif source_type == SourceType.GOOGLE_DOCS:
        prefix = f"g{doc_id}"
    else:
        prefix = doc_id

    if title:
        slug = slugify(title)
        return f"{prefix}-{slug}.md"
    return f"{prefix}.md"

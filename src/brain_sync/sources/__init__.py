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
_CONFLUENCE_FALLBACK_RE = re.compile(r"/(\d+)(?:[/?#]|$)")


def extract_confluence_page_id(url: str) -> str:
    m = _CONFLUENCE_PAGE_ID_RE.search(url)
    if not m:
        m = _CONFLUENCE_FALLBACK_RE.search(url)
    if not m:
        raise URLParseError(f"Cannot extract Confluence page ID from: {url}")
    return m.group(1)


_GDOCS_ID_RE = re.compile(r"docs\.google\.com/document/d/([a-zA-Z0-9_-]+)")


def extract_google_doc_id(url: str) -> str:
    m = _GDOCS_ID_RE.search(url)
    if not m:
        raise URLParseError(f"Cannot extract Google Doc ID from: {url}")
    return m.group(1)


def slugify(title: str) -> str:
    """Convert a document title to a safe, kebab-case filename stem."""
    s = title.lower()
    s = re.sub(r"[^\w\s-]", "", s)       # remove non-word chars except spaces/hyphens
    s = re.sub(r"[\s_]+", "-", s)         # spaces/underscores to hyphens
    s = re.sub(r"-{2,}", "-", s)          # collapse multiple hyphens
    s = s.strip("-")
    return s or "untitled"

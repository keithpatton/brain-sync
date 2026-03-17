"""URL helpers with no source-adapter ownership."""

from __future__ import annotations

import re
from urllib.parse import unquote_plus, urlparse


def extract_title_from_url(url: str) -> str:
    """Extract a human-readable title from the last non-empty URL path segment."""
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return ""
    slug = unquote_plus(segments[-1]).replace("-", " ").replace("_", " ")
    slug = re.sub(r"\s+", " ", slug).strip()
    return slug.title() if slug else ""


__all__ = ["extract_title_from_url"]

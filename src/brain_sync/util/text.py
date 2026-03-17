"""Text helpers with no brain-sync domain ownership."""

from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Convert text to a safe, kebab-case filename stem."""
    slug = text.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


__all__ = ["slugify"]

"""Portable managed-markdown helpers shared across persistence callers.

This module owns the durable identity/header conventions for markdown files
materialized into the portable brain. It is intentionally neutral: repository,
pipeline, and doctor code may depend on it without creating workflow-layer
cycles.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from brain_sync.brain.fileops import read_bytes

MANAGED_HEADER_SOURCE = "<!-- brain-sync-source: {} -->"
MANAGED_HEADER_WARNING = "<!-- brain-sync-managed: local edits may be overwritten -->"

_MANAGED_HEADER_RE = re.compile(r"^<!-- brain-sync-(source|managed): .* -->\n", re.MULTILINE)
_EXTRACT_SOURCE_RE = re.compile(r"^<!-- brain-sync-source: (.+) -->\r?$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_MANAGED_FRONTMATTER_KEYS = (
    "brain_sync_source",
    "brain_sync_canonical_id",
    "brain_sync_source_url",
)


def _to_durable_source_type(source_type: str) -> str:
    if source_type == "googledocs":
        return "google_doc"
    return source_type


def split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Return parsed frontmatter and body, tolerating malformed YAML."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return dict(data), text[match.end() :]


def render_frontmatter(data: dict[str, object], body: str) -> str:
    """Render a YAML frontmatter block above body content."""
    if not data:
        return body.lstrip("\n")
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=False).strip()
    body = body.lstrip("\n")
    if body:
        return f"---\n{rendered}\n---\n\n{body}"
    return f"---\n{rendered}\n---\n"


def canonical_source_type_for_frontmatter(source_type: str | None, canonical_id: str) -> str:
    """Infer the durable source type string stored in managed frontmatter."""
    if source_type:
        return _to_durable_source_type(source_type)
    if canonical_id.startswith("gdoc:"):
        return "google_doc"
    return canonical_id.split(":", 1)[0]


def extract_source_id(path: Path) -> str | None:
    """Extract canonical_id from a managed markdown file, if present."""
    try:
        head = read_bytes(path)[:4096].decode("utf-8", errors="replace")
        frontmatter, _ = split_frontmatter(head)
        frontmatter_cid = frontmatter.get("brain_sync_canonical_id")
        if isinstance(frontmatter_cid, str):
            return frontmatter_cid
        match = _EXTRACT_SOURCE_RE.search(head)
        return match.group(1) if match else None
    except OSError:
        return None


def strip_managed_header(text: str) -> str:
    """Remove managed identity from YAML frontmatter and legacy HTML comments."""
    frontmatter, body = split_frontmatter(text)
    if frontmatter:
        for key in _MANAGED_FRONTMATTER_KEYS:
            frontmatter.pop(key, None)
        text = render_frontmatter(frontmatter, body)
    return _MANAGED_HEADER_RE.sub("", text).lstrip("\n")


def prepend_managed_header(
    canonical_id: str,
    markdown: str,
    *,
    source_type: str | None = None,
    source_url: str | None = None,
) -> str:
    """Write spec-aligned managed identity frontmatter, preserving user keys."""
    frontmatter, body = split_frontmatter(markdown)
    body = _MANAGED_HEADER_RE.sub("", body).lstrip("\n")
    frontmatter["brain_sync_source"] = canonical_source_type_for_frontmatter(source_type, canonical_id)
    frontmatter["brain_sync_canonical_id"] = canonical_id
    if source_url is not None:
        frontmatter["brain_sync_source_url"] = source_url
    return render_frontmatter(frontmatter, body)

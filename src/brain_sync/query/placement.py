"""Placement suggestion commands — suggest brain areas for new documents.

Uses AreaIndex.search() to find candidate folders, accumulating scores
across multiple query terms extracted from the document title and excerpt.

Also provides source classification helpers (SourceKind, classify_source)
and filename/excerpt utilities used by both CLI and MCP add workflows.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from urllib.parse import unquote_plus, urlparse

from brain_sync.query.area_index import AreaIndex
from brain_sync.sources import UnsupportedSourceError

log = logging.getLogger(__name__)

MAX_QUERY_TERMS = 8
MAX_EXCERPT_CHARS = 200
MAX_PLACEMENT_RESULTS = 10


# ---------------------------------------------------------------------------
# Source classification
# ---------------------------------------------------------------------------


class SourceKind(Enum):
    URL = "url"
    FILE = "file"


def classify_source(source: str) -> SourceKind:
    """Deterministic source classification: URL or existing file.

    Does NOT resolve symlinks — preserves relative paths as-is.
    """
    parsed = urlparse(source)
    if parsed.scheme in ("http", "https"):
        return SourceKind.URL
    if Path(source).exists():
        return SourceKind.FILE
    raise UnsupportedSourceError(f"Not a URL or existing file: {source}")


def extract_title_from_url(url: str) -> str:
    """Extract a human-readable title from a URL slug.

    Takes the last non-empty path segment, replaces hyphens/underscores
    with spaces, and decodes percent-encoding.
    """
    parsed = urlparse(url)
    segments = [s for s in parsed.path.split("/") if s]
    if not segments:
        return ""
    slug = segments[-1]
    slug = unquote_plus(slug)
    slug = slug.replace("-", " ").replace("_", " ")
    # Collapse multiple spaces
    slug = re.sub(r"\s+", " ", slug).strip()
    # Title-case each word
    return slug.title() if slug else ""


def extract_file_excerpt(path: Path, limit: int = 500) -> str:
    """Read the first N chars of a file for use as a placement excerpt."""
    suffix = path.suffix.lower()
    try:
        if suffix in {".md", ".txt"}:
            return path.read_text(encoding="utf-8", errors="ignore")[:limit]
        if suffix == ".docx":
            from brain_sync.sources.docx import docx_to_markdown

            return docx_to_markdown(path)[:limit]
    except Exception:
        log.debug("Could not extract excerpt from %s", path)
    return ""


@dataclass
class PlacementSelection:
    """Structured return from interactive placement."""

    path: str  # full relative path: "product/auth/api-gateway-design.md"
    cancelled: bool = False


STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "for",
        "is",
        "on",
        "with",
        "at",
        "by",
        "from",
        "this",
        "that",
        "it",
    }
)


@dataclass
class PlacementCandidate:
    """A suggested area for document placement."""

    path: str
    score: int
    reasoning: str


@dataclass
class SuggestPlacementResult:
    """Result of a placement suggestion query."""

    candidates: list[PlacementCandidate] = field(default_factory=list)
    query_terms: list[str] = field(default_factory=list)
    total_areas: int = 0


def _extract_query_terms(
    filename_stem: str,
    excerpt: str = "",
    max_excerpt_chars: int = MAX_EXCERPT_CHARS,
) -> list[str]:
    """Extract search terms from filename stem and excerpt.

    Filename stem words come first (primary signal), followed by excerpt
    words (secondary). Stop words are removed and the result is capped
    at MAX_QUERY_TERMS.
    """
    # Tokenize: split on non-alphanumeric, lowercase, strip empties
    stem_words = [w.lower() for w in re.split(r"[^a-zA-Z0-9]+", filename_stem) if w]
    excerpt_trimmed = excerpt[:max_excerpt_chars]
    excerpt_words = [w.lower() for w in re.split(r"[^a-zA-Z0-9]+", excerpt_trimmed) if w]

    # Combine, deduplicate preserving order, remove stop words
    seen: set[str] = set()
    terms: list[str] = []
    for word in stem_words + excerpt_words:
        if word in STOP_WORDS or word in seen:
            continue
        seen.add(word)
        terms.append(word)
        if len(terms) >= MAX_QUERY_TERMS:
            break

    return terms


def suggest_placement(
    index: AreaIndex,
    document_title: str,
    document_excerpt: str = "",
    source: str | None = None,
    subtree: str | None = None,
    max_results: int = 5,
) -> SuggestPlacementResult:
    """Suggest brain areas for placing a new document.

    Args:
        index: Pre-built AreaIndex to search against.
        document_title: Title or filename of the document.
        document_excerpt: Optional content snippet.
        source: URL or file path (passed through for future scoring).
        subtree: If provided, restrict to paths under this prefix.
        max_results: Max candidates to return (capped at 10).
    """
    max_results = min(max_results, MAX_PLACEMENT_RESULTS)
    query_terms = _extract_query_terms(document_title, document_excerpt)

    if not query_terms:
        return SuggestPlacementResult(
            candidates=[],
            query_terms=[],
            total_areas=len(index.entries),
        )

    # Multi-query accumulation
    accumulated: dict[str, int] = {}
    term_matches: dict[str, list[str]] = {}
    summary_previews: dict[str, str] = {}

    for term in query_terms:
        results = index.search(term, max_results=10)
        for r in results:
            path = r["path"]
            accumulated[path] = accumulated.get(path, 0) + r["score"]
            term_matches.setdefault(path, []).append(term)
            # Keep the first non-empty preview we see
            if path not in summary_previews and r.get("summary_preview"):
                summary_previews[path] = r["summary_preview"]

    # Subtree filtering
    if subtree:
        prefix = subtree.rstrip("/")
        accumulated = {p: s for p, s in accumulated.items() if p == prefix or p.startswith(prefix + "/")}

    # Sort by (-score, path) for deterministic ordering
    sorted_paths = sorted(accumulated.keys(), key=lambda p: (-accumulated[p], p))

    # Build candidates
    candidates: list[PlacementCandidate] = []
    for path in sorted_paths[:max_results]:
        matched = term_matches.get(path, [])
        preview = summary_previews.get(path, "")
        # Build reasoning
        parts: list[str] = []
        if matched:
            parts.append("Matched: " + ", ".join(matched))
        if preview:
            # First sentence or first 100 chars of preview
            first_line = preview.split("\n")[0].lstrip("# ").strip()
            if first_line:
                parts.append("Summary: " + first_line[:100])
        reasoning = ". ".join(parts) + "." if parts else ""

        candidates.append(
            PlacementCandidate(
                path=path,
                score=accumulated[path],
                reasoning=reasoning,
            )
        )

    return SuggestPlacementResult(
        candidates=candidates,
        query_terms=query_terms,
        total_areas=len(index.entries),
    )

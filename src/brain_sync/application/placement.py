"""Application-owned document placement workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brain_sync.application.query_index import AreaIndex, load_area_index
from brain_sync.query.placement import (
    extract_file_excerpt as extract_local_file_excerpt,
)
from brain_sync.query.placement import (
    extract_title_from_url,
    suggest_placement,
)
from brain_sync.sources import canonical_filename, detect_source_type, extract_id, title_resolution


@dataclass(frozen=True)
class PlacementCandidateView:
    path: str
    score: int
    reasoning: str


@dataclass(frozen=True)
class PlacementSuggestionResult:
    document_title: str
    suggested_filename: str | None
    candidates: list[PlacementCandidateView]
    query_terms: list[str]
    total_areas: int


class DocumentTitleRequiredError(ValueError):
    """Raised when placement cannot determine any document title."""

    pass


def suggest_document_placement(
    root: Path,
    *,
    document_title: str = "",
    document_excerpt: str = "",
    source_url: str | None = None,
    subtree: str | None = None,
    max_results: int = 5,
    current_index: AreaIndex | None = None,
    allow_url_title_fallback: bool = False,
    fallback_title: str | None = None,
) -> tuple[PlacementSuggestionResult, AreaIndex]:
    """Resolve title/filename inputs and suggest candidate areas."""
    resolved_title = document_title
    if not resolved_title and source_url:
        resolved_title = title_resolution.resolve_source_title_sync(source_url) or ""
        if not resolved_title and allow_url_title_fallback:
            resolved_title = extract_title_from_url(source_url) or ""
    if not resolved_title and fallback_title:
        resolved_title = fallback_title

    if not resolved_title:
        raise DocumentTitleRequiredError("Provide document_title or source_url")

    index = load_area_index(root, current=current_index)
    suggestions = suggest_placement(
        index,
        document_title=resolved_title,
        document_excerpt=document_excerpt,
        source=source_url,
        subtree=subtree,
        max_results=max_results,
    )

    suggested_filename: str | None = None
    if source_url:
        try:
            source_type = detect_source_type(source_url)
            document_id = extract_id(source_type, source_url)
            suggested_filename = canonical_filename(source_type, document_id, resolved_title)
        except Exception:
            suggested_filename = None

    return PlacementSuggestionResult(
        document_title=resolved_title,
        suggested_filename=suggested_filename,
        candidates=[
            PlacementCandidateView(path=candidate.path, score=candidate.score, reasoning=candidate.reasoning)
            for candidate in suggestions.candidates
        ],
        query_terms=suggestions.query_terms,
        total_areas=suggestions.total_areas,
    ), index


def extract_file_excerpt(path: Path, limit: int = 500) -> str:
    """Read a local file excerpt for application-owned placement workflows."""
    return extract_local_file_excerpt(path, limit=limit)

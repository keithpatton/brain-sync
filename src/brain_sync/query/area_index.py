"""In-memory search index over brain areas.

Extracted from mcp.py so that command-layer modules (e.g. placement) can
use AreaIndex without importing from an entry point. See CLAUDE.md module
dependency rule.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.brain.fileops import iterdir_paths, path_is_dir, path_is_file, read_text, rglob_paths
from brain_sync.brain.layout import MANAGED_DIRNAME, SUMMARY_FILENAME, area_summary_path
from brain_sync.brain.tree import get_child_dirs, is_content_dir

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUMMARY_INDEX_CHARS = 2000
MAX_PREVIEW_CHARS = 500
MAX_SEARCH_RESULTS = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_file_safe(path: Path, max_chars: int | None = None) -> str:
    """Read a text file safely with utf-8, ignoring decode errors."""
    try:
        text = read_text(path, encoding="utf-8", errors="ignore")
        if max_chars is not None and len(text) > max_chars:
            return text[:max_chars]
        return text
    except OSError as exc:
        log.debug("Failed to read %s: %s", path, exc)
        return ""


# ---------------------------------------------------------------------------
# Index entry and index
# ---------------------------------------------------------------------------


@dataclass
class AreaIndexEntry:
    """Index entry for a single brain area."""

    path: str
    path_parts: list[str]
    summary_first_para: str = ""  # first paragraph (used for preview)
    summary_body: str = ""  # full indexed text (used for search)
    summary_headings: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    has_knowledge: bool = False
    has_summary: bool = False


class AreaIndex:
    """In-memory search index over brain areas."""

    def __init__(self) -> None:
        self.entries: list[AreaIndexEntry] = []
        self._max_mtime: float = 0.0
        self._marked_stale = False

    @classmethod
    def build(cls, root: Path) -> AreaIndex:
        """Build a fresh index by walking knowledge/ for structure and co-located summaries."""
        index = cls()
        knowledge_root = root / "knowledge"

        if not path_is_dir(knowledge_root):
            return index

        max_mtime = 0.0

        def _walk(directory: Path, prefix: str) -> None:
            nonlocal max_mtime
            for child in iterdir_paths(directory):
                if not is_content_dir(child):
                    continue
                if child.name == "_core":
                    continue
                child_rel = prefix + "/" + child.name if prefix else child.name

                # Build entry
                entry = AreaIndexEntry(
                    path=child_rel,
                    path_parts=child_rel.split("/"),
                    has_knowledge=True,  # walking knowledge/, so it exists by definition
                )

                # Summary from knowledge/<area>/.brain-sync/insights/summary.md
                summary_path = area_summary_path(root, child_rel)
                if path_is_file(summary_path):
                    entry.has_summary = True
                    try:
                        mtime = summary_path.stat().st_mtime
                        if mtime > max_mtime:
                            max_mtime = mtime
                    except OSError:
                        pass
                    text = _read_file_safe(summary_path, SUMMARY_INDEX_CHARS)
                    if text:
                        entry.summary_body = text
                        # First paragraph: text up to first blank line (for preview)
                        paras = re.split(r"\n\s*\n", text, maxsplit=1)
                        entry.summary_first_para = paras[0][:MAX_PREVIEW_CHARS] if paras else ""
                        # Headings
                        entry.summary_headings = sorted(
                            line.lstrip("#").strip() for line in text.splitlines() if line.startswith("##")
                        )

                # Children from knowledge/
                child_content_dirs = get_child_dirs(child)
                entry.children = sorted(d.name for d in child_content_dirs)

                index.entries.append(entry)
                _walk(child, child_rel)

        _walk(knowledge_root, "")
        index._max_mtime = max_mtime
        log.debug("AreaIndex built: %d entries, max_mtime=%.1f", len(index.entries), max_mtime)
        return index

    def mark_stale(self) -> None:
        """Force the next lifecycle check to rebuild this cached index."""
        self._marked_stale = True

    def is_stale(self, root: Path) -> bool:
        """Check if the index needs rebuilding by scanning managed summary mtimes."""
        if self._marked_stale:
            return True
        knowledge_root = root / "knowledge"
        if not path_is_dir(knowledge_root):
            return bool(self.entries)
        max_mtime = 0.0
        for p in rglob_paths(knowledge_root, SUMMARY_FILENAME):
            if path_is_file(p) and MANAGED_DIRNAME in p.parts:
                try:
                    mtime = p.stat().st_mtime
                    if mtime > max_mtime:
                        max_mtime = mtime
                except OSError:
                    pass
        return max_mtime != self._max_mtime

    def search(self, query: str, max_results: int = 5) -> list[dict]:
        """Search the index, returning scored results."""
        max_results = min(max_results, MAX_SEARCH_RESULTS)
        query_lower = query.lower()
        scored: list[tuple[int, str, AreaIndexEntry]] = []

        for entry in self.entries:
            score = 0
            # Path segments — highest weight (x3)
            for part in entry.path_parts:
                if query_lower in part.lower():
                    score += 3

            # Summary body — medium weight (x2)
            if query_lower in entry.summary_body.lower():
                score += 2

            # Headings — base weight (x1)
            for heading in entry.summary_headings:
                if query_lower in heading.lower():
                    score += 1

            if score > 0:
                # Deterministic tie-break: (-score, path)
                scored.append((score, entry.path, entry))

        # Sort by (-score, path) for stable ordering
        scored.sort(key=lambda x: (-x[0], x[1]))

        results: list[dict] = []
        for score, _, entry in scored[:max_results]:
            results.append(
                {
                    "path": entry.path,
                    "summary_preview": entry.summary_first_para[:MAX_PREVIEW_CHARS],
                    "children": entry.children,
                    "has_knowledge": entry.has_knowledge,
                    "score": score,
                }
            )
        return results

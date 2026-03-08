"""brain-sync MCP server — complete brain interface via MCP tools.

Exposes brain-sync functionality as MCP tools so Claude Code and Claude
Desktop can interact with the brain without filesystem access.

Architecture: SKILL.md (WHAT/WHEN) → MCP tools (HOW) → brain_sync library

Usage:
    python -m brain_sync.mcp
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from brain_sync.commands import (
    SourceAlreadyExistsError,
    SourceNotFoundError,
    add_source,
    list_sources,
    move_source,
    remove_source,
    resolve_root,
)
from brain_sync.fileops import TEXT_EXTENSIONS
from brain_sync.fs_utils import get_child_dirs, is_content_dir, is_readable_file
from brain_sync.regen import regen_all, regen_path
from brain_sync.sources import UnsupportedSourceError

log = logging.getLogger(__name__)

server = FastMCP("brain-sync")

# Resolve once at startup — all tools use this root
_root = resolve_root()

# Prevent concurrent regeneration
_regen_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# Constants — token budget enforcement
# ---------------------------------------------------------------------------

TRUNCATION_MARKER = "[truncated — use brain_sync_open_file for full content]"
MAX_SUMMARY_CHARS = 12000        # ~3000 tokens
MAX_CHILD_SUMMARY_CHARS = 2000   # ~500 tokens each
MAX_CHILDREN = 5                 # max child summaries returned
MAX_INSIGHT_FILE_CHARS = 8000    # other insight artifacts
MAX_AREA_PAYLOAD = 40000         # total response chars — hard cap
MAX_AREAS_LISTED = 50
MAX_GLOBAL_CONTEXT_FILE_CHARS = 4000
MAX_PREVIEW_CHARS = 500
MAX_SEARCH_RESULTS = 10
MAX_FILE_CHARS = 16000
SUMMARY_INDEX_CHARS = 2000
ALLOWED_EXTENSIONS = frozenset({".md", ".txt", ".json", ".yaml", ".yml"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _truncate(text: str, limit: int) -> str:
    """Truncate text to limit chars, appending marker if truncated."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n" + TRUNCATION_MARKER


def _safe_resolve(root: Path, rel_path: str) -> Path | None:
    """Resolve a relative path within the brain root safely.

    Returns None if the resolved path escapes the root (including via symlinks).
    """
    try:
        resolved = (root / rel_path).resolve()
        if not resolved.is_relative_to(root.resolve()):
            return None
        return resolved
    except (OSError, ValueError):
        return None


def _read_file_safe(path: Path, max_chars: int | None = None) -> str:
    """Read a text file safely with utf-8, ignoring decode errors."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        if max_chars is not None:
            return _truncate(text, max_chars)
        return text
    except OSError:
        return ""


def _collect_global_context_structured(root: Path) -> dict[str, dict[str, str]]:
    """Load global context as structured dict for MCP responses.

    Returns {"knowledge_core": {...}, "schemas": {...}, "insights_core": {...}}.
    """
    result: dict[str, dict[str, str]] = {
        "knowledge_core": {},
        "schemas": {},
        "insights_core": {},
    }

    # 1. knowledge/_core
    core_dir = root / "knowledge" / "_core"
    if core_dir.is_dir():
        for p in sorted(core_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS and not p.name.startswith(("_", ".")):
                rel = str(p.relative_to(core_dir)).replace("\\", "/")
                result["knowledge_core"][rel] = _read_file_safe(p, MAX_GLOBAL_CONTEXT_FILE_CHARS)

    # 2. schemas
    schemas_dir = root / "schemas"
    if schemas_dir.is_dir():
        for p in sorted(schemas_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".md", ".txt"} and not p.name.startswith("."):
                rel = str(p.relative_to(schemas_dir)).replace("\\", "/")
                result["schemas"][rel] = _read_file_safe(p, MAX_GLOBAL_CONTEXT_FILE_CHARS)

    # 3. insights/_core (excluding journal/)
    insights_core = root / "insights" / "_core"
    if insights_core.is_dir():
        for p in sorted(insights_core.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".md", ".txt"} and not p.name.startswith("."):
                rel_parts = p.relative_to(insights_core).parts
                if "journal" in rel_parts:
                    continue
                rel = str(p.relative_to(insights_core)).replace("\\", "/")
                result["insights_core"][rel] = _read_file_safe(p, MAX_GLOBAL_CONTEXT_FILE_CHARS)

    return result


def _collect_areas(root: Path) -> list[dict]:
    """Collect all insight areas with summary existence status."""
    areas: list[dict] = []
    insights_root = root / "insights"
    if not insights_root.is_dir():
        return areas

    def _walk(directory: Path, prefix: str) -> None:
        for child in sorted(directory.iterdir()):
            if not is_content_dir(child):
                continue
            if child.name == "_core":
                continue
            child_rel = prefix + "/" + child.name if prefix else child.name
            has_summary = (child / "summary.md").is_file()
            areas.append({"path": child_rel, "has_summary": has_summary})
            _walk(child, child_rel)

    _walk(insights_root, "")
    return areas


# ---------------------------------------------------------------------------
# Search index — built at startup, rebuilt on staleness
# ---------------------------------------------------------------------------

@dataclass
class AreaIndexEntry:
    """Index entry for a single brain area."""
    path: str
    path_parts: list[str]
    summary_first_para: str = ""   # first paragraph (used for preview)
    summary_body: str = ""         # full indexed text (used for search)
    summary_headings: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    has_knowledge: bool = False
    has_summary: bool = False


class AreaIndex:
    """In-memory search index over brain areas."""

    def __init__(self) -> None:
        self.entries: list[AreaIndexEntry] = []
        self._max_mtime: float = 0.0

    @classmethod
    def build(cls, root: Path) -> AreaIndex:
        """Build a fresh index by walking insights/ and knowledge/."""
        index = cls()
        insights_root = root / "insights"
        knowledge_root = root / "knowledge"

        if not insights_root.is_dir():
            return index

        max_mtime = 0.0

        def _walk(directory: Path, prefix: str) -> None:
            nonlocal max_mtime
            for child in sorted(directory.iterdir()):
                if not is_content_dir(child):
                    continue
                if child.name == "_core":
                    continue
                child_rel = prefix + "/" + child.name if prefix else child.name

                # Build entry
                entry = AreaIndexEntry(
                    path=child_rel,
                    path_parts=child_rel.split("/"),
                )

                # Summary — single pass: read file, extract first para + headings, track mtime
                summary_path = child / "summary.md"
                if summary_path.is_file():
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
                            line.lstrip("#").strip()
                            for line in text.splitlines()
                            if line.startswith("##")
                        )

                # Children
                child_content_dirs = get_child_dirs(child)
                entry.children = sorted(d.name for d in child_content_dirs)

                # Knowledge presence
                knowledge_dir = knowledge_root / child_rel
                if knowledge_dir.is_dir():
                    entry.has_knowledge = any(is_readable_file(p) for p in knowledge_dir.iterdir())

                index.entries.append(entry)
                _walk(child, child_rel)

        _walk(insights_root, "")
        index._max_mtime = max_mtime
        log.debug("AreaIndex built: %d entries, max_mtime=%.1f", len(index.entries), max_mtime)
        return index

    def is_stale(self, root: Path) -> bool:
        """Check if the index needs rebuilding by scanning summary.md mtimes."""
        insights_root = root / "insights"
        if not insights_root.is_dir():
            return bool(self.entries)  # stale if we have entries but no insights dir
        max_mtime = 0.0
        for p in insights_root.rglob("summary.md"):
            if p.is_file():
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
            # Path segments — highest weight (×3)
            for part in entry.path_parts:
                if query_lower in part.lower():
                    score += 3

            # Summary body — medium weight (×2)
            if query_lower in entry.summary_body.lower():
                score += 2

            # Headings — base weight (×1)
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
            results.append({
                "path": entry.path,
                "summary_preview": entry.summary_first_para[:MAX_PREVIEW_CHARS],
                "children": entry.children,
                "has_knowledge": entry.has_knowledge,
                "score": score,
            })
        return results


# Module-level index — built once at startup
_area_index = AreaIndex.build(_root)


def _get_index() -> AreaIndex:
    """Get the area index, rebuilding if stale."""
    global _area_index
    if _area_index.is_stale(_root):
        log.debug("Area index stale, rebuilding")
        _area_index = AreaIndex.build(_root)
    return _area_index


# ---------------------------------------------------------------------------
# Source management tools (existing)
# ---------------------------------------------------------------------------

@server.tool(
    name="brain_sync_list",
    description="List registered brain-sync sources. Optionally filter by path prefix.",
)
def brain_sync_list(filter_path: str | None = None) -> dict:
    """List registered sync sources."""
    sources = list_sources(root=_root, filter_path=filter_path)
    result = {
        "status": "ok",
        "sources": [asdict(s) for s in sources],
        "count": len(sources),
    }
    log.debug("brain_sync_list(filter_path=%r) → %d sources", filter_path, len(sources))
    return result


@server.tool(
    name="brain_sync_add",
    description=(
        "Register a URL for syncing to the brain. "
        "Supports Confluence pages and Google Docs. "
        "Set target_path to the knowledge subfolder (e.g. 'initiatives/my-project')."
    ),
)
def brain_sync_add(
    url: str,
    target_path: str,
    include_links: bool = False,
    include_children: bool = False,
    include_attachments: bool = False,
) -> dict:
    """Register a source URL for syncing."""
    try:
        result = add_source(
            root=_root,
            url=url,
            target_path=target_path,
            include_links=include_links,
            include_children=include_children,
            include_attachments=include_attachments,
        )
        return {"status": "ok", **asdict(result)}
    except SourceAlreadyExistsError as e:
        return {
            "status": "error",
            "error": "source_already_exists",
            "canonical_id": e.canonical_id,
            "source_url": e.source_url,
            "target_path": e.target_path,
        }
    except UnsupportedSourceError:
        return {
            "status": "error",
            "error": "unsupported_url",
            "url": url,
        }


@server.tool(
    name="brain_sync_remove",
    description=(
        "Unregister a sync source by canonical ID or URL. "
        "Set delete_files=true to also remove the knowledge folder."
    ),
)
def brain_sync_remove(source: str, delete_files: bool = False) -> dict:
    """Unregister a sync source."""
    try:
        result = remove_source(
            root=_root,
            source=source,
            delete_files=delete_files,
        )
        return {"status": "ok", **asdict(result)}
    except SourceNotFoundError:
        return {
            "status": "error",
            "error": "source_not_found",
            "source": source,
        }


@server.tool(
    name="brain_sync_move",
    description="Move a sync source to a new knowledge path.",
)
def brain_sync_move(source: str, to_path: str) -> dict:
    """Move a sync source to a new knowledge path."""
    try:
        result = move_source(
            root=_root,
            source=source,
            to_path=to_path,
        )
        return {"status": "ok", **asdict(result)}
    except SourceNotFoundError:
        return {
            "status": "error",
            "error": "source_not_found",
            "source": source,
        }


@server.tool(
    name="brain_sync_regen",
    description=(
        "Regenerate insight summaries. "
        "Pass a knowledge path to regenerate a specific area, "
        "or omit path to regenerate all areas."
    ),
)
async def brain_sync_regen(path: str | None = None) -> dict:
    """Regenerate insight summaries."""
    async with _regen_lock:
        if path:
            count = await regen_path(_root, path)
        else:
            count = await regen_all(_root)

        return {
            "status": "ok",
            "summaries_regenerated": count,
            "path": path or "all",
        }


# ---------------------------------------------------------------------------
# Brain query tools (new)
# ---------------------------------------------------------------------------

@server.tool(
    name="brain_sync_query",
    description=(
        "Primary brain entrypoint. Search for areas matching a query. "
        "Set include_global=True to also load core context (knowledge/_core, "
        "schemas, insights/_core). Use brain_sync_open_area to drill into a match."
    ),
)
def brain_sync_query(
    query: str,
    include_global: bool = False,
    max_results: int = 5,
) -> dict:
    """Search the brain for areas matching a query."""
    index = _get_index()
    matches = index.search(query, max_results=max_results)

    result: dict = {
        "status": "ok",
        "matches": matches,
    }

    if include_global:
        result["global_context"] = _collect_global_context_structured(_root)

    # Areas listing (capped)
    all_areas = _collect_areas(_root)
    total = len(all_areas)
    truncated = total > MAX_AREAS_LISTED
    result["areas"] = all_areas[:MAX_AREAS_LISTED]
    result["areas_truncated"] = truncated
    result["total_areas"] = total

    log.debug("brain_sync_query(query=%r, include_global=%s) → %d matches, %d areas",
              query, include_global, len(matches), total)
    return result


@server.tool(
    name="brain_sync_get_context",
    description=(
        "Load global brain context: knowledge/_core, schemas, insights/_core. "
        "Use when you need broad brain orientation. For area-specific queries, "
        "use brain_sync_query instead."
    ),
)
def brain_sync_get_context() -> dict:
    """Load global brain context for orientation."""
    global_context = _collect_global_context_structured(_root)
    all_areas = _collect_areas(_root)
    total = len(all_areas)
    truncated = total > MAX_AREAS_LISTED

    result = {
        "status": "ok",
        "global_context": global_context,
        "areas": all_areas[:MAX_AREAS_LISTED],
        "areas_truncated": truncated,
        "total_areas": total,
    }
    log.debug("brain_sync_get_context() → %d areas", total)
    return result


@server.tool(
    name="brain_sync_open_area",
    description=(
        "Load full insight context for a brain area. Returns summary, insight artifacts, "
        "and child area listing. Use after brain_sync_query to drill into a specific area."
    ),
)
def brain_sync_open_area(
    path: str,
    include_children: bool = False,
    include_knowledge_list: bool = False,
) -> dict:
    """Load full insight context for a brain area."""
    insights_dir = _safe_resolve(_root, "insights/" + path)
    if insights_dir is None or not insights_dir.is_dir():
        return {"status": "error", "error": "not_found", "path": path}

    knowledge_dir = _safe_resolve(_root, "knowledge/" + path)
    payload_size = 0

    # Read insight files (excluding journal/)
    insights: dict[str, str] = {}
    summary_content = ""
    for p in sorted(insights_dir.iterdir()):
        if not p.is_file() or p.suffix.lower() not in {".md", ".txt"}:
            continue
        if p.name.startswith("."):
            continue
        rel_parts = p.relative_to(insights_dir).parts
        if "journal" in rel_parts:
            continue

        if p.name == "summary.md":
            content = _read_file_safe(p, MAX_SUMMARY_CHARS)
            summary_content = content
        else:
            content = _read_file_safe(p, MAX_INSIGHT_FILE_CHARS)

        insights[p.name] = content
        payload_size += len(content)

    # Children listing (always)
    child_dirs = get_child_dirs(insights_dir)
    children: list[dict] = []
    for d in sorted(child_dirs, key=lambda d: d.name):
        children.append({
            "name": d.name,
            "has_summary": (d / "summary.md").is_file(),
        })
    total_children = len(children)

    # Child summaries (optional, capped)
    child_summaries: dict[str, str] = {}
    children_truncated = False
    if include_children:
        for i, d in enumerate(sorted(child_dirs, key=lambda d: d.name)):
            if i >= MAX_CHILDREN:
                children_truncated = True
                break
            summary_path = d / "summary.md"
            if summary_path.is_file():
                content = _read_file_safe(summary_path, MAX_CHILD_SUMMARY_CHARS)
                child_summaries[d.name] = content
                payload_size += len(content)

    # Knowledge file listing (optional)
    knowledge_files: list[str] = []
    if include_knowledge_list and knowledge_dir is not None and knowledge_dir.is_dir():
        for p in sorted(knowledge_dir.iterdir()):
            if is_readable_file(p):
                knowledge_files.append(p.name)

    # Enforce MAX_AREA_PAYLOAD — progressive degradation
    if payload_size > MAX_AREA_PAYLOAD:
        # Step 1: Drop non-summary insight artifacts
        for key in list(insights.keys()):
            if key != "summary.md":
                payload_size -= len(insights[key])
                insights[key] = TRUNCATION_MARKER
                payload_size += len(TRUNCATION_MARKER)

    if payload_size > MAX_AREA_PAYLOAD:
        # Step 2: Truncate child summaries further
        for key in list(child_summaries.keys()):
            old_len = len(child_summaries[key])
            reduced = MAX_CHILD_SUMMARY_CHARS // 2
            child_summaries[key] = _truncate(child_summaries[key], reduced)
            payload_size -= old_len - len(child_summaries[key])

    if payload_size > MAX_AREA_PAYLOAD:
        # Step 3: Truncate summary as last resort
        if "summary.md" in insights:
            old_len = len(insights["summary.md"])
            insights["summary.md"] = _truncate(insights["summary.md"], MAX_AREA_PAYLOAD // 2)
            payload_size -= old_len - len(insights["summary.md"])

    result: dict = {
        "status": "ok",
        "path": path,
        "insights": insights,
        "children": children,
        "total_children": total_children,
    }
    if include_children:
        result["child_summaries"] = child_summaries
        result["children_truncated"] = children_truncated
    if include_knowledge_list:
        result["knowledge_files"] = knowledge_files

    log.debug("brain_sync_open_area(%r) → %d insight files, %d children, payload %d chars",
              path, len(insights), total_children, payload_size)
    return result


@server.tool(
    name="brain_sync_open_file",
    description=(
        "Read a specific text file from the brain by relative path "
        "(e.g. 'insights/_core/summary.md', 'knowledge/initiatives/AAA/doc.md'). "
        "Returns file content. Supports .md, .txt, .json, .yaml, .yml files only."
    ),
)
def brain_sync_open_file(path: str) -> dict:
    """Read a specific file from the brain."""
    resolved = _safe_resolve(_root, path)
    if resolved is None:
        return {"status": "error", "error": "not_found", "path": path}

    if not resolved.is_file():
        return {"status": "error", "error": "not_found", "path": path}

    ext = resolved.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {"status": "error", "error": "unsupported_type", "path": path, "extension": ext}

    content = _read_file_safe(resolved, MAX_FILE_CHARS)
    log.debug("brain_sync_open_file(%r) → %d chars", path, len(content))
    return {"status": "ok", "path": path, "content": content}


if __name__ == "__main__":
    server.run(transport="stdio")

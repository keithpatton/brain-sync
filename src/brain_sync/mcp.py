"""brain-sync MCP server — complete brain interface via MCP tools.

Exposes brain-sync functionality as MCP tools so Claude Code and Claude
Desktop can interact with the brain without filesystem access.

Architecture: SKILL.md (WHAT/WHEN) → MCP tools (HOW) → brain_sync library

Runtime state ownership: All environment-dependent state (root path, area index,
concurrency locks) lives in BrainRuntime, initialised via the server lifespan.
Module-level definitions must remain pure (constants, helpers, tool registrations).

Usage:
    python -m brain_sync.mcp
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from brain_sync.application import (
    SourceAlreadyExistsError,
    SourceNotFoundError,
    add_source,
    list_sources,
    move_source,
    reconcile_sources,
    remove_source,
    resolve_root,
    update_source,
)
from brain_sync.application.placement import suggest_placement
from brain_sync.area_index import AreaIndex
from brain_sync.brain.fileops import iterdir_paths, path_exists, path_is_dir, path_is_file, read_text
from brain_sync.brain.layout import SUMMARY_FILENAME, area_insights_dir, area_summary_path
from brain_sync.brain.repository import BrainRepository, BrainRepositoryInvariantError
from brain_sync.brain.tree import get_child_dirs, is_content_dir, is_readable_file, normalize_path
from brain_sync.regen import RegenFailed, regen_all, regen_path
from brain_sync.regen_lifecycle import regen_session
from brain_sync.sources import UnsupportedSourceError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — token budget enforcement
# ---------------------------------------------------------------------------

TRUNCATION_MARKER = "[truncated — call brain_sync_open_file(path=..., offset=N) to read more]"
MAX_SUMMARY_CHARS = 12000  # ~3000 tokens
MAX_CHILD_SUMMARY_CHARS = 2000  # ~500 tokens each
MAX_CHILDREN = 5  # max child summaries returned
MAX_INSIGHT_FILE_CHARS = 8000  # other insight artifacts
MAX_AREA_PAYLOAD = 40000  # total response chars — hard cap
MAX_AREAS_LISTED = 50
MAX_GLOBAL_CONTEXT_FILE_CHARS = 4000
MAX_FILE_CHARS = 1_000_000
DEFAULT_FILE_CHARS = 200_000
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
        text = read_text(path, encoding="utf-8", errors="ignore")
        if max_chars is not None:
            return _truncate(text, max_chars)
        return text
    except OSError as exc:
        log.debug("Failed to read %s: %s", path, exc)
        return ""


def _collect_global_context_structured(root: Path) -> dict[str, str | bool]:
    """Load global context for MCP responses.

    Global context is `_core`'s distilled meaning: its managed summary when
    present. Raw `knowledge/_core/` files remain available through
    ``brain_sync_open_file()`` but are not returned here.
    """
    summary_path = area_summary_path(root, "_core")
    rel_path = "knowledge/_core/.brain-sync/insights/summary.md"
    if path_is_file(summary_path):
        return {
            "path": rel_path,
            "content": _read_file_safe(summary_path, MAX_GLOBAL_CONTEXT_FILE_CHARS),
            "present": True,
        }
    return {
        "path": rel_path,
        "content": "",
        "present": False,
    }


def _collect_areas(root: Path) -> list[dict]:
    """Collect all insight areas with summary existence status."""
    areas: list[dict] = []
    knowledge_root = root / "knowledge"
    if not path_is_dir(knowledge_root):
        return areas

    def _walk(directory: Path, prefix: str) -> None:
        for child in iterdir_paths(directory):
            if not is_content_dir(child):
                continue
            if child.name == "_core":
                continue
            child_rel = prefix + "/" + child.name if prefix else child.name
            has_summary = path_is_file(area_summary_path(root, child_rel))
            areas.append({"path": child_rel, "has_summary": has_summary})
            _walk(child, child_rel)

    _walk(knowledge_root, "")
    return areas


# ---------------------------------------------------------------------------
# Runtime state — initialised at server startup, not at import time
# ---------------------------------------------------------------------------


@dataclass
class BrainRuntime:
    """Single owner of MCP process state.

    All variables whose values depend on filesystem state, configuration,
    or runtime execution live here. Module-level variables in mcp.py must
    remain pure definitions (constants, helper functions, tool registrations).
    """

    root: Path
    area_index: AreaIndex
    regen_lock: asyncio.Lock


@asynccontextmanager
async def _brain_lifespan(_app: FastMCP) -> AsyncIterator[BrainRuntime]:
    root = resolve_root()
    area_index = AreaIndex.build(root)
    regen_lock = asyncio.Lock()
    log.info("brain-sync MCP started, root=%s", root)
    yield BrainRuntime(root=root, area_index=area_index, regen_lock=regen_lock)


server = FastMCP("brain-sync", lifespan=_brain_lifespan)


def _runtime(ctx: Context) -> BrainRuntime:
    """Extract BrainRuntime from the MCP request context."""
    return ctx.request_context.lifespan_context  # type: ignore[return-value]


def _get_index(rt: BrainRuntime) -> AreaIndex:
    """Get the area index, rebuilding if stale."""
    if rt.area_index.is_stale(rt.root):
        log.debug("Area index stale, rebuilding")
        rt.area_index = AreaIndex.build(rt.root)
    return rt.area_index


# ---------------------------------------------------------------------------
# Source management tools
# ---------------------------------------------------------------------------


@server.tool(
    name="brain_sync_list",
    description="List registered brain-sync sources. Optionally filter by path prefix.",
)
def brain_sync_list(ctx: Context, filter_path: str | None = None) -> dict:
    """List registered sync sources."""
    rt = _runtime(ctx)
    sources = list_sources(root=rt.root, filter_path=filter_path)
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
        "Register a URL for syncing. Supports Confluence pages and Google Docs. "
        "target_path is required — call suggest_placement first to determine it, "
        "present the candidates to the user, and use their chosen path."
    ),
)
def brain_sync_add(
    ctx: Context,
    source: str,
    target_path: str,
    fetch_children: bool = False,
    sync_attachments: bool = False,
    child_path: str | None = None,
) -> dict:
    """Register a source URL for syncing."""
    from urllib.parse import urlparse

    rt = _runtime(ctx)

    # URL-only: reject non-URLs with helpful hint
    parsed = urlparse(source)
    if parsed.scheme not in ("http", "https"):
        return {
            "status": "error",
            "error": "not_a_url",
            "message": "Use brain_sync_add_file for local files (.md or .txt)",
        }

    try:
        result = add_source(
            root=rt.root,
            url=source,
            target_path=target_path,
            fetch_children=fetch_children,
            sync_attachments=sync_attachments,
            child_path=child_path,
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
        return {"status": "error", "error": "unsupported_url", "source": source}


@server.tool(
    name="brain_sync_add_file",
    description=(
        "Add a local file to the brain. Supports .md and .txt files. "
        "Save attachments to a temp file first, then call this tool. "
        "target_path is required — call suggest_placement first to determine it. "
        "copy defaults to true (safe for temp files). If false, the source file is moved instead of copied."
    ),
)
def brain_sync_add_file(
    ctx: Context,
    source: str,
    target_path: str,
    copy: bool = True,
) -> dict:
    """Add a local file to the brain."""
    from brain_sync.brain.fileops import ADDFILE_EXTENSIONS

    rt = _runtime(ctx)
    repository = BrainRepository(rt.root)

    file_path = Path(source).resolve()
    if not file_path.exists():
        return {"status": "error", "error": "file_not_found", "source": source}

    ext = file_path.suffix.lower()
    if ext not in ADDFILE_EXTENSIONS:
        return {
            "status": "error",
            "error": "unsupported_file_type",
            "message": f"Unsupported file type: {ext}. add-file supports: {', '.join(sorted(ADDFILE_EXTENSIONS))}",
        }

    try:
        dest = repository.add_local_file(file_path, target_path, copy=copy)
    except BrainRepositoryInvariantError as exc:
        return {"status": "error", "error": "collision", "message": str(exc)}

    action = "copied" if copy else "moved"

    rel = normalize_path(dest.relative_to(rt.root))
    return {"status": "ok", "action": action, "path": rel}


@server.tool(
    name="brain_sync_remove_file",
    description=(
        "Remove a local (non-synced) file from knowledge/. "
        "path is relative to knowledge/ (e.g. 'area/notes.md'). "
        "Does not affect synced sources — use brain_sync_remove for those. "
        "Insights will be updated on next regen cycle."
    ),
)
def brain_sync_remove_file(ctx: Context, path: str) -> dict:
    """Remove a file from knowledge/."""
    rt = _runtime(ctx)
    repository = BrainRepository(rt.root)
    target = rt.root / "knowledge" / path
    try:
        deleted = repository.delete_local_file(path)
    except BrainRepositoryInvariantError as exc:
        if path_exists(target) and not path_is_file(target):
            return {"status": "error", "error": "not_a_file", "path": path}
        return {"status": "error", "error": "invalid_path", "message": str(exc)}
    if not deleted:
        if path_exists(target) and not path_is_file(target):
            return {"status": "error", "error": "not_a_file", "path": path}
        return {"status": "error", "error": "file_not_found", "path": path}
    return {"status": "ok", "path": path, "hint": "Insights will update on next regen."}


@server.tool(
    name="brain_sync_remove",
    description=(
        "Unregister a sync source by canonical ID or URL. Set delete_files=true to also remove the knowledge folder."
    ),
)
def brain_sync_remove(ctx: Context, source: str, delete_files: bool = False) -> dict:
    """Unregister a sync source."""
    rt = _runtime(ctx)
    try:
        result = remove_source(
            root=rt.root,
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
    name="brain_sync_update",
    description=(
        "Update settings for a registered source. "
        "Pass only the flags you want to change — omitted flags are left unchanged. "
        "Use fetch_children (one-shot) and sync_attachments / no sync_attachments toggles. "
        "child_path controls where discovered children are placed."
    ),
)
def brain_sync_update(
    ctx: Context,
    source: str,
    fetch_children: bool | None = None,
    sync_attachments: bool | None = None,
    child_path: str | None = None,
) -> dict:
    """Update config flags for an existing sync source."""
    rt = _runtime(ctx)
    try:
        result = update_source(
            root=rt.root,
            source=source,
            fetch_children=fetch_children,
            sync_attachments=sync_attachments,
            child_path=child_path if child_path is not None else ...,  # type: ignore[arg-type]
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
def brain_sync_move(ctx: Context, source: str, to_path: str) -> dict:
    """Move a sync source to a new knowledge path."""
    rt = _runtime(ctx)
    try:
        result = move_source(
            root=rt.root,
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
    name="brain_sync_reconcile",
    description=(
        "Reconcile DB target paths with the filesystem. "
        "If files were moved manually in knowledge/, this updates the DB to match. "
        "Also runs automatically on brain-sync run startup."
    ),
)
def brain_sync_reconcile(ctx: Context) -> dict:
    """Reconcile DB target paths with where files actually are on disk."""
    rt = _runtime(ctx)
    result = reconcile_sources(root=rt.root)
    return {
        "status": "ok",
        "updated": [asdict(e) for e in result.updated],
        "not_found": result.not_found,
        "unchanged": result.unchanged,
    }


@server.tool(
    name="brain_sync_regen",
    description=(
        "Regenerate insight summaries. "
        "Pass a knowledge path to regenerate a specific area, "
        "or omit path to regenerate all areas."
    ),
)
async def brain_sync_regen(ctx: Context, path: str | None = None) -> dict:
    """Regenerate insight summaries."""
    rt = _runtime(ctx)
    async with rt.regen_lock:
        async with regen_session(rt.root) as session:
            try:
                if path:
                    path = normalize_path(path)
                    count = await regen_path(rt.root, path, owner_id=session.owner_id, session_id=session.session_id)
                else:
                    count = await regen_all(rt.root, owner_id=session.owner_id, session_id=session.session_id)
                return {
                    "status": "ok",
                    "summaries_regenerated": count,
                    "path": path or "all",
                }
            except Exception as e:
                return {
                    "status": "error",
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "path": path or "all",
                    # v1 heuristic: RegenFailed (exhausted retries, validation)
                    # is treated as non-retryable. In practice a RegenFailed
                    # from a transient upstream issue could be retryable, and
                    # some non-RegenFailed errors may not be.
                    "retryable": not isinstance(e, RegenFailed),
                }


# ---------------------------------------------------------------------------
# Placement suggestion tool
# ---------------------------------------------------------------------------


@server.tool(
    name="brain_sync_suggest_placement",
    description=(
        "Suggest brain areas for placing a new document. "
        "Pass the document title (or filename) and optionally an excerpt. "
        "Alternatively pass source_url to auto-resolve the title (works for Google Docs). "
        "Use subtree to restrict suggestions to a specific area. "
        "Always present the returned candidates to the user as a numbered list "
        "and let them choose before calling brain_sync_add."
    ),
)
def brain_sync_suggest_placement(
    ctx: Context,
    document_title: str = "",
    document_excerpt: str = "",
    source_url: str | None = None,
    subtree: str | None = None,
    max_results: int = 5,
) -> dict:
    """Suggest placement areas for a new document."""
    # Title resolution: explicit title wins, else resolve from URL
    if not document_title and source_url:
        from brain_sync.sources.title_resolution import resolve_source_title_sync

        document_title = resolve_source_title_sync(source_url) or ""

    if not document_title:
        return {"status": "error", "error": "no_title", "message": "Provide document_title or source_url"}

    rt = _runtime(ctx)
    index = _get_index(rt)
    result = suggest_placement(
        index,
        document_title=document_title,
        document_excerpt=document_excerpt,
        subtree=subtree,
        max_results=max_results,
    )

    # Compute canonical filename when source_url is available
    suggested_filename: str | None = None
    if source_url:
        try:
            from brain_sync.sources import canonical_filename, detect_source_type, extract_id

            st = detect_source_type(source_url)
            did = extract_id(st, source_url)
            suggested_filename = canonical_filename(st, did, document_title)
        except Exception:
            pass  # best-effort

    response: dict = {
        "status": "ok",
        "candidates": [{"path": c.path, "score": c.score, "reasoning": c.reasoning} for c in result.candidates],
        "query_terms": result.query_terms,
        "total_areas": result.total_areas,
        "suggested_filename": suggested_filename,
    }

    if not result.candidates:
        response["hint"] = "No matching areas. Consider creating a new area."

    log.debug(
        "brain_sync_suggest_placement(title=%r) → %d candidates",
        document_title,
        len(result.candidates),
    )
    return response


# ---------------------------------------------------------------------------
# Brain query tools
# ---------------------------------------------------------------------------


@server.tool(
    name="brain_sync_query",
    description=(
        "Primary brain entrypoint. Search for areas matching a query. "
        "Set include_global=True to also load global context from "
        "knowledge/_core/.brain-sync/insights/summary.md. "
        "Use brain_sync_open_area to drill into a match."
    ),
)
def brain_sync_query(
    ctx: Context,
    query: str,
    include_global: bool = False,
    max_results: int = 5,
) -> dict:
    """Search the brain for areas matching a query."""
    rt = _runtime(ctx)
    index = _get_index(rt)
    matches = index.search(query, max_results=max_results)

    result: dict = {
        "status": "ok",
        "matches": matches,
    }

    if include_global:
        result["global_context"] = _collect_global_context_structured(rt.root)

    # Areas listing (capped)
    all_areas = _collect_areas(rt.root)
    total = len(all_areas)
    truncated = total > MAX_AREAS_LISTED
    result["areas"] = all_areas[:MAX_AREAS_LISTED]
    result["areas_truncated"] = truncated
    result["total_areas"] = total

    log.debug(
        "brain_sync_query(query=%r, include_global=%s) → %d matches, %d areas",
        query,
        include_global,
        len(matches),
        total,
    )
    return result


@server.tool(
    name="brain_sync_get_context",
    description=(
        "Load global brain context from knowledge/_core/.brain-sync/insights/summary.md. "
        "Use when you need broad brain orientation. Raw knowledge/_core files remain available "
        "through brain_sync_open_file(path='knowledge/_core/...') when needed. "
        "For area-specific queries, use brain_sync_query instead."
    ),
)
def brain_sync_get_context(ctx: Context) -> dict:
    """Load global brain context for orientation."""
    rt = _runtime(ctx)
    global_context = _collect_global_context_structured(rt.root)
    all_areas = _collect_areas(rt.root)
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
    ctx: Context,
    path: str,
    include_children: bool = False,
    include_knowledge_list: bool = False,
) -> dict:
    """Load full insight context for a brain area."""
    rt = _runtime(ctx)
    insights_dir = area_insights_dir(rt.root, path)
    if insights_dir is None or not path_is_dir(insights_dir):
        return {"status": "error", "error": "not_found", "path": path}

    knowledge_dir = _safe_resolve(rt.root, "knowledge/" + path)
    payload_size = 0

    # Read insight files (excluding journal/)
    insights: dict[str, str] = {}
    for p in iterdir_paths(insights_dir):
        if not path_is_file(p) or p.suffix.lower() not in {".md", ".txt"}:
            continue
        if p.name.startswith("."):
            continue
        rel_parts = p.relative_to(insights_dir).parts
        if "journal" in rel_parts:
            continue

        if p.name == SUMMARY_FILENAME:
            content = _read_file_safe(p, MAX_SUMMARY_CHARS)
        else:
            content = _read_file_safe(p, MAX_INSIGHT_FILE_CHARS)

        insights[p.name] = content
        payload_size += len(content)

    # Children listing (always)
    child_dirs = get_child_dirs(knowledge_dir) if knowledge_dir is not None and path_is_dir(knowledge_dir) else []
    children: list[dict] = []
    for d in sorted(child_dirs, key=lambda d: d.name):
        child_path = f"{path}/{d.name}" if path else d.name
        children.append(
            {
                "name": d.name,
                "has_summary": path_is_file(area_summary_path(rt.root, child_path)),
            }
        )
    total_children = len(children)

    # Child summaries (optional, capped)
    child_summaries: dict[str, str] = {}
    children_truncated = False
    if include_children:
        for i, d in enumerate(sorted(child_dirs, key=lambda d: d.name)):
            if i >= MAX_CHILDREN:
                children_truncated = True
                break
            child_path = f"{path}/{d.name}" if path else d.name
            summary_path = area_summary_path(rt.root, child_path)
            if path_is_file(summary_path):
                content = _read_file_safe(summary_path, MAX_CHILD_SUMMARY_CHARS)
                child_summaries[d.name] = content
                payload_size += len(content)

    # Knowledge file listing (optional)
    knowledge_files: list[str] = []
    if include_knowledge_list and knowledge_dir is not None and path_is_dir(knowledge_dir):
        for p in iterdir_paths(knowledge_dir):
            if is_readable_file(p):
                knowledge_files.append(p.name)

    # Enforce MAX_AREA_PAYLOAD — progressive degradation
    if payload_size > MAX_AREA_PAYLOAD:
        # Step 1: Drop non-summary insight artifacts
        for key in list(insights.keys()):
            if key != SUMMARY_FILENAME:
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
        if SUMMARY_FILENAME in insights:
            old_len = len(insights[SUMMARY_FILENAME])
            insights[SUMMARY_FILENAME] = _truncate(insights[SUMMARY_FILENAME], MAX_AREA_PAYLOAD // 2)
            payload_size -= old_len - len(insights[SUMMARY_FILENAME])

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

    log.debug(
        "brain_sync_open_area(%r) → %d insight files, %d children, payload %d chars",
        path,
        len(insights),
        total_children,
        payload_size,
    )
    return result


@server.tool(
    name="brain_sync_open_file",
    description=(
        "Read a specific text file from the brain by relative path "
        "(e.g. 'knowledge/_core/.brain-sync/insights/summary.md', 'knowledge/initiatives/AAA/doc.md'). "
        "Returns file content. Supports .md, .txt, .json, .yaml, .yml files only. "
        "For large files, use offset (0-based char position) to paginate. "
        "Default limit is 200000 chars per call."
    ),
)
def brain_sync_open_file(
    ctx: Context,
    path: str,
    offset: int = 0,
    limit: int = DEFAULT_FILE_CHARS,
) -> dict:
    """Read a specific file from the brain with pagination support."""
    rt = _runtime(ctx)
    resolved = _safe_resolve(rt.root, path)
    if resolved is None:
        return {"status": "error", "error": "not_found", "path": path}

    if not path_is_file(resolved):
        return {"status": "error", "error": "not_found", "path": path}

    ext = resolved.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {"status": "error", "error": "unsupported_type", "path": path, "extension": ext}

    limit = min(limit, MAX_FILE_CHARS)
    offset = max(0, offset)

    # Read full file — seek() on text-mode files uses opaque positions
    # (not character offsets), so we must read-then-slice for correctness.
    # Knowledge files are at most ~500 KB; this is fine.
    text = read_text(resolved, encoding="utf-8", errors="replace")

    if offset >= len(text):
        return {
            "status": "ok",
            "path": path,
            "content": "",
            "offset": offset,
            "limit": limit,
            "truncated": False,
        }

    raw = text[offset : offset + limit + 512]

    # Align to newline boundary to preserve Markdown structure
    if len(raw) > limit:
        last_nl = raw.rfind("\n", 0, limit)
        chunk = raw[: last_nl + 1] if last_nl != -1 else raw[:limit]
        has_more = True
    else:
        chunk = raw
        has_more = False

    next_offset = offset + len(chunk)

    result: dict = {
        "status": "ok",
        "path": path,
        "content": chunk,
        "offset": offset,
        "limit": limit,
        "truncated": has_more,
    }
    if has_more:
        result["next_offset"] = next_offset
        result["hint"] = f'Call brain_sync_open_file(path="{path}", offset={next_offset}) to continue.'

    log.debug("brain_sync_open_file(%r, offset=%d) → %d chars, truncated=%s", path, offset, len(chunk), has_more)
    return result


# ---------------------------------------------------------------------------
# Token usage tool
# ---------------------------------------------------------------------------


@server.tool(
    name="brain_sync_doctor",
    description=(
        "Check brain consistency and optionally repair. "
        "mode: 'check' (default), 'fix' (auto-repair drift), "
        "'rebuild_db' (rebuild source sync progress from manifests, preserves regen state), "
        "'deregister_missing' (finalize all missing sources)."
    ),
)
def brain_sync_doctor(ctx: Context, mode: str = "check") -> dict:
    """Diagnose brain health and optionally repair."""
    from brain_sync.application.doctor import Severity, deregister_missing, doctor, rebuild_db

    rt = _runtime(ctx)
    try:
        if mode == "rebuild_db":
            result = rebuild_db(rt.root)
        elif mode == "deregister_missing":
            result = deregister_missing(rt.root)
        elif mode == "fix":
            result = doctor(rt.root, fix=True)
        else:
            result = doctor(rt.root, fix=False)

        non_ok = [
            {
                "check": f.check,
                "severity": f.severity.value,
                "message": f.message,
                "canonical_id": f.canonical_id,
                "knowledge_path": f.knowledge_path,
                "fix_applied": f.fix_applied,
            }
            for f in result.findings
            if f.severity != Severity.OK
        ]
        return {
            "status": "ok",
            "healthy": result.is_healthy,
            "summary": {
                "ok": result.ok_count,
                "drift": result.drift_count,
                "would_trigger_regen": result.would_trigger_regen_count,
                "would_trigger_fetch": result.would_trigger_fetch_count,
                "corruption": result.corruption_count,
            },
            "findings": non_ok,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@server.tool(
    name="brain_sync_usage",
    description=(
        "Show token usage summary for LLM invocations. "
        "Returns totals, per-operation breakdown, and per-day breakdown. "
        "Defaults to the last 7 days."
    ),
)
def brain_sync_usage(ctx: Context, days: int = 7) -> dict:
    """Return token usage telemetry summary."""
    from brain_sync.runtime.token_tracking import get_usage_summary

    rt = _runtime(ctx)
    try:
        summary = get_usage_summary(rt.root, days=days)
        return {"status": "ok", "days": days, **summary}
    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    from brain_sync.logging_config import setup_logging
    from brain_sync.runtime.config import load_config

    log_level = load_config().get("log_level", "INFO")
    setup_logging(log_level)
    server.run(transport="stdio")

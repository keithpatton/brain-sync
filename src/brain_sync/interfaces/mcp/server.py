"""brain-sync MCP server — complete brain interface via MCP tools.

Exposes brain-sync functionality as MCP tools so Claude Code and Claude
Desktop can interact with the brain without filesystem access.

Architecture: SKILL.md (WHAT/WHEN) → MCP tools (HOW) → brain_sync library

Runtime state ownership: All environment-dependent state (root path, area index,
concurrency locks) lives in BrainRuntime, initialised via the server lifespan.
Module-level definitions must remain pure (constants, helpers, tool registrations).

Usage:
    python -m brain_sync.interfaces.mcp.server
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from brain_sync.application.browse import (
    DEFAULT_FILE_CHARS as DEFAULT_FILE_CHARS,
)
from brain_sync.application.browse import (
    MAX_AREAS_LISTED as MAX_AREAS_LISTED,
)
from brain_sync.application.browse import (
    MAX_CHILDREN as MAX_CHILDREN,
)
from brain_sync.application.browse import (
    MAX_FILE_CHARS as MAX_FILE_CHARS,
)
from brain_sync.application.browse import (
    MAX_SUMMARY_CHARS as MAX_SUMMARY_CHARS,
)
from brain_sync.application.browse import (
    TRUNCATION_MARKER as TRUNCATION_MARKER,
)
from brain_sync.application.browse import (
    AreaNotFoundError,
    BrainFileNotFoundError,
    UnsupportedBrainFileTypeError,
    get_brain_context,
    open_area,
    open_file,
    query_brain,
)
from brain_sync.application.local_files import (
    InvalidKnowledgePathError,
    KnowledgeFileNotFoundError,
    KnowledgePathIsDirectoryError,
    LocalFileCollisionError,
    LocalFileNotFoundError,
    UnsupportedLocalFileTypeError,
    add_local_file,
    remove_local_file,
)
from brain_sync.application.placement import DocumentTitleRequiredError, suggest_document_placement
from brain_sync.application.query_index import AreaIndex
from brain_sync.application.reconcile import reconcile_brain
from brain_sync.application.regen import RegenFailed, run_regen
from brain_sync.application.roots import resolve_root
from brain_sync.application.sources import (
    InvalidChildDiscoveryRequestError,
    SourceAlreadyExistsError,
    SourceNotFoundError,
    UnsupportedSourceUrlError,
    add_source,
    list_sources,
    move_source,
    remove_source,
    update_source,
)
from brain_sync.application.status import get_usage_summary

log = logging.getLogger(__name__)


def _drop_none_values(payload: dict) -> dict:
    """Remove top-level keys whose values are None."""
    return {key: value for key, value in payload.items() if value is not None}


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
    """Return the MCP-cached area index."""
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
    except InvalidChildDiscoveryRequestError as e:
        return {"status": "error", "error": "invalid_child_discovery_request", "message": str(e)}
    except UnsupportedSourceUrlError:
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
    rt = _runtime(ctx)
    try:
        result = add_local_file(rt.root, source=Path(source), target_path=target_path, copy=copy)
        return {"status": "ok", **asdict(result)}
    except LocalFileNotFoundError:
        return {"status": "error", "error": "file_not_found", "source": source}
    except UnsupportedLocalFileTypeError as exc:
        return {"status": "error", "error": "unsupported_file_type", "message": str(exc)}
    except LocalFileCollisionError as exc:
        return {"status": "error", "error": "collision", "message": str(exc)}
    except InvalidKnowledgePathError as exc:
        return {"status": "error", "error": "invalid_path", "message": str(exc)}


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
    try:
        result = remove_local_file(rt.root, path=path)
        return {"status": "ok", **asdict(result)}
    except KnowledgePathIsDirectoryError:
        return {"status": "error", "error": "not_a_file", "path": path}
    except InvalidKnowledgePathError as exc:
        return {"status": "error", "error": "invalid_path", "message": str(exc)}
    except KnowledgeFileNotFoundError:
        return {"status": "error", "error": "file_not_found", "path": path}


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
        "child_path controls where discovered children are placed for the active pending request."
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
    except InvalidChildDiscoveryRequestError as e:
        return {"status": "error", "error": "invalid_child_discovery_request", "message": str(e)}


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
    result = reconcile_brain(rt.root)
    return {
        "status": "ok",
        "updated": [asdict(entry) for entry in result.updated],
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
        try:
            count = await run_regen(rt.root, path)
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
    rt = _runtime(ctx)
    try:
        result, index = suggest_document_placement(
            rt.root,
            document_title=document_title,
            document_excerpt=document_excerpt,
            source_url=source_url,
            subtree=subtree,
            max_results=max_results,
            current_index=_get_index(rt),
        )
    except DocumentTitleRequiredError:
        return {"status": "error", "error": "no_title", "message": "Provide document_title or source_url"}

    rt.area_index = index

    response: dict = {
        "status": "ok",
        "candidates": [{"path": c.path, "score": c.score, "reasoning": c.reasoning} for c in result.candidates],
        "query_terms": result.query_terms,
        "total_areas": result.total_areas,
        "suggested_filename": result.suggested_filename,
    }

    if not result.candidates:
        response["hint"] = "No matching areas. Consider creating a new area."

    log.debug(
        "brain_sync_suggest_placement(title=%r) → %d candidates",
        result.document_title,
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
    result, index = query_brain(
        rt.root,
        query=query,
        include_global=include_global,
        max_results=max_results,
        current_index=_get_index(rt),
    )
    rt.area_index = index
    payload = _drop_none_values({"status": "ok", **asdict(result)})

    log.debug(
        "brain_sync_query(query=%r, include_global=%s) → %d matches, %d areas",
        query,
        include_global,
        len(result.matches),
        result.total_areas,
    )
    return payload


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
    result = get_brain_context(rt.root)
    log.debug("brain_sync_get_context() → %d areas", result.total_areas)
    return _drop_none_values({"status": "ok", **asdict(result)})


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
    try:
        result = open_area(
            rt.root,
            path=path,
            include_children=include_children,
            include_knowledge_list=include_knowledge_list,
        )
    except AreaNotFoundError:
        return {"status": "error", "error": "not_found", "path": path}

    log.debug(
        "brain_sync_open_area(%r) → %d insight files, %d children",
        path,
        len(result.insights),
        result.total_children,
    )
    return _drop_none_values({"status": "ok", **asdict(result)})


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
    try:
        result = open_file(rt.root, path=path, offset=offset, limit=limit)
    except BrainFileNotFoundError:
        return {"status": "error", "error": "not_found", "path": path}
    except UnsupportedBrainFileTypeError as exc:
        return {"status": "error", "error": "unsupported_type", "path": path, "extension": exc.extension}

    log.debug(
        "brain_sync_open_file(%r, offset=%d) → %d chars, truncated=%s",
        path,
        result.offset,
        len(result.content),
        result.truncated,
    )
    return _drop_none_values({"status": "ok", **asdict(result)})


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
    rt = _runtime(ctx)
    try:
        summary = get_usage_summary(rt.root, days=days)
        return {"status": "ok", **asdict(summary)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


if __name__ == "__main__":
    from brain_sync.runtime.config import load_config
    from brain_sync.util.logging import setup_logging

    log_level = load_config().get("log_level", "INFO")
    setup_logging(log_level)
    server.run(transport="stdio")

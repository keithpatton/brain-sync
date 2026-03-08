"""brain-sync MCP server — thin wrapper over commands and regen APIs.

Exposes brain-sync functionality as MCP tools so Claude Code can call
them directly without Bash/subprocess permission prompts.

Usage:
    python -m brain_sync.mcp
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict

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
from brain_sync.regen import regen_all, regen_path
from brain_sync.sources import UnsupportedSourceError

server = FastMCP("brain-sync")

# Resolve once at startup — all tools use this root
_root = resolve_root()

# Prevent concurrent regeneration
_regen_lock = asyncio.Lock()


@server.tool(
    name="brain_sync_list",
    description="List registered brain-sync sources. Optionally filter by path prefix.",
)
def brain_sync_list(filter_path: str | None = None) -> dict:
    """List registered sync sources."""
    sources = list_sources(root=_root, filter_path=filter_path)
    return {
        "status": "ok",
        "sources": [asdict(s) for s in sources],
        "count": len(sources),
    }


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


if __name__ == "__main__":
    server.run(transport="stdio")

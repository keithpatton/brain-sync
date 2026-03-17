"""Application-owned regen workflows and helpers."""

from __future__ import annotations

from pathlib import Path

from brain_sync.brain.tree import normalize_path
from brain_sync.regen import RegenFailed, classify_folder_change, invalidate_global_context_cache, regen_all, regen_path
from brain_sync.regen.lifecycle import regen_session

__all__ = [
    "RegenFailed",
    "classify_folder_change",
    "invalidate_global_context_cache",
    "run_regen",
]


async def run_regen(root: Path, knowledge_path: str | None = None) -> int:
    """Run a shared regen workflow for CLI and MCP.

    Full-tree regen reclaims stale ownership on entry. Single-path regen leaves
    unrelated stale rows alone.
    """
    normalized_path = normalize_path(knowledge_path) if knowledge_path else None
    async with regen_session(root, reclaim_stale=not normalized_path) as session:
        if normalized_path:
            return await regen_path(root, normalized_path, owner_id=session.owner_id, session_id=session.session_id)
        return await regen_all(root, owner_id=session.owner_id, session_id=session.session_id)

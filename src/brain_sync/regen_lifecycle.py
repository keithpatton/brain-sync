"""Shared lifecycle wrapper for regen invocations.

All entry points (daemon, CLI, MCP) use ``regen_session`` to get
consistent owner-scoped state tracking, stale recovery, and cleanup.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from brain_sync.state import (
    reclaim_stale_running_states,
    release_owned_running_states,
)

log = logging.getLogger(__name__)


@dataclass
class RegenSession:
    owner_id: str
    session_id: str
    root: Path


@asynccontextmanager
async def regen_session(
    root: Path,
    reclaim_stale: bool = False,
    stale_threshold_secs: float = 600.0,
) -> AsyncGenerator[RegenSession, None]:
    """Async context manager providing owner-scoped regen lifecycle.

    On enter:
        - Generate a unique ``owner_id`` for this invocation.
        - If ``reclaim_stale=True``, reclaim orphaned 'running' states from
          prior crashes (time-based, safe for concurrent processes).

    On exit (finally):
        - Release only the running states owned by this session's ``owner_id``.
        - ``KeyboardInterrupt`` and ``asyncio.CancelledError`` are re-raised
          after cleanup.
    """
    owner_id = uuid4().hex
    session_id = uuid4().hex
    session = RegenSession(owner_id=owner_id, session_id=session_id, root=root)

    if reclaim_stale:
        count = reclaim_stale_running_states(root, stale_threshold_secs)
        if count:
            log.info(
                "Reclaimed %d stale 'running' insight states from prior run",
                count,
            )

    try:
        yield session
    finally:
        try:
            released = release_owned_running_states(root, owner_id)
            if released:
                log.info(
                    "Released %d owned 'running' insight states on session exit",
                    released,
                )
        except Exception:
            log.exception("Failed to release owned running states on session exit")

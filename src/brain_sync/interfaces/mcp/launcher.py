"""Bootstrap-capable MCP launcher for shared plugin/runtime use."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP

from brain_sync.application.init import init_brain
from brain_sync.application.launcher import (
    get_runtime_status,
    restart_daemon,
    start_daemon,
    stop_daemon,
)
from brain_sync.application.query_index import AreaIndex, load_area_index
from brain_sync.application.roots import attach_root, get_setup_status
from brain_sync.interfaces.mcp.server import register_full_tools
from brain_sync.runtime.repository import ensure_lifecycle_session

log = logging.getLogger(__name__)

_full_tools_registered = False


@dataclass
class LauncherRuntime:
    """Single owner of MCP launcher process state."""

    root: Path | None
    area_index: AreaIndex | None
    regen_lock: asyncio.Lock
    lifecycle_session_id: str | None
    auto_start_daemon: bool


def _path_value(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _setup_payload(status) -> dict:
    return {
        "ready": status.ready,
        "configured_active_root": _path_value(status.configured_active_root),
        "usable_active_root": _path_value(status.usable_active_root),
        "registered_roots": [str(path) for path in status.registered_roots],
        "reason": status.reason,
        "message": status.message,
    }


def _daemon_payload(status) -> dict:
    return {
        "state": status.state,
        "snapshot_status": status.snapshot_status,
        "controller_kind": status.controller_kind,
        "pid": status.pid,
        "daemon_id": status.daemon_id,
        "daemon_root": status.daemon_root,
        "active_root": _path_value(status.active_root),
        "started_at": status.started_at,
        "updated_at": status.updated_at,
        "stopped_at": status.stopped_at,
        "healthy": status.healthy,
        "adoptable": status.adoptable,
        "competing_start_refused": status.competing_start_refused,
        "stop_supported": status.stop_supported,
        "restart_supported": status.restart_supported,
        "reason": status.reason,
    }


def _content_payload(content) -> dict | None:
    if content is None:
        return None
    return {
        "source_count": content.source_count,
        "insight_states_by_status": dict(content.insight_states_by_status),
        "usage_available": content.usage_available,
        "usage": {
            "days": content.usage.days,
            "total_input": content.usage.total_input,
            "total_output": content.usage.total_output,
            "total_tokens": content.usage.total_tokens,
            "total_invocations": content.usage.total_invocations,
            "by_operation": list(content.usage.by_operation),
            "by_day": list(content.usage.by_day),
        },
    }


def _runtime_status_payload() -> dict:
    status = get_runtime_status()
    payload = {
        "status": "ok",
        "setup": _setup_payload(status.setup),
        "daemon": _daemon_payload(status.daemon),
    }
    content = _content_payload(status.content)
    if content is not None:
        payload["content"] = content
    return payload


def _daemon_admin_payload(result) -> dict:
    payload = {
        "status": "ok",
        "result": result.result,
        "adopted": result.adopted,
        "daemon": _daemon_payload(result.daemon),
    }
    if result.message:
        payload["message"] = result.message
    return payload


def _ensure_full_tools_registered() -> None:
    global _full_tools_registered
    if _full_tools_registered:
        return
    register_full_tools(server)
    _full_tools_registered = True


def _activate_runtime(rt: LauncherRuntime, root: Path) -> None:
    _ensure_full_tools_registered()
    rt.root = root
    rt.area_index = load_area_index(root, current=rt.area_index)
    rt.lifecycle_session_id = ensure_lifecycle_session(root, owner_kind="mcp")
    rt.auto_start_daemon = True


@asynccontextmanager
async def _launcher_lifespan(_app: FastMCP) -> AsyncIterator[LauncherRuntime]:
    runtime = LauncherRuntime(
        root=None,
        area_index=None,
        regen_lock=asyncio.Lock(),
        lifecycle_session_id=None,
        auto_start_daemon=False,
    )
    setup = get_setup_status()
    if setup.ready and setup.usable_active_root is not None:
        _activate_runtime(runtime, setup.usable_active_root)
        log.info("brain-sync MCP launcher started in full mode, root=%s", runtime.root)
    else:
        log.info("brain-sync MCP launcher started in bootstrap mode")
    yield runtime


server = FastMCP("brain-sync", lifespan=_launcher_lifespan)


def _runtime(ctx: Context) -> LauncherRuntime:
    return ctx.request_context.lifespan_context  # type: ignore[return-value]


@server.tool(
    name="brain_sync_setup_status",
    description="Report whether an active usable brain root is attached and ready for full MCP use.",
)
def brain_sync_setup_status() -> dict:
    return {
        "status": "ok",
        "setup": _setup_payload(get_setup_status()),
    }


@server.tool(
    name="brain_sync_init",
    description="Initialize a new brain root, attach it as the active runtime root, and unlock full MCP tools.",
)
def brain_sync_init(ctx: Context, root: str, model: str | None = None) -> dict:
    runtime = _runtime(ctx)
    result = init_brain(Path(root), model=model)
    _activate_runtime(runtime, result.root)
    return {
        "status": "ok",
        "root": str(result.root),
        "was_existing": result.was_existing,
        "dirs_created": list(result.dirs_created),
        "setup": _setup_payload(get_setup_status()),
    }


@server.tool(
    name="brain_sync_attach_root",
    description="Attach an existing initialized brain root and make it the active runtime root for this config dir.",
)
def brain_sync_attach_root(ctx: Context, root: str) -> dict:
    runtime = _runtime(ctx)
    result = attach_root(Path(root))
    _activate_runtime(runtime, result.root)
    return {
        "status": "ok",
        "root": str(result.root),
        "previous_active_root": _path_value(result.previous_active_root),
        "registered_roots": [str(path) for path in result.registered_roots],
        "setup": _setup_payload(get_setup_status()),
    }


@server.tool(
    name="brain_sync_status",
    description="Show bootstrap readiness plus current daemon and sync status for the active runtime.",
)
def brain_sync_status() -> dict:
    return _runtime_status_payload()


@server.tool(
    name="brain_sync_start",
    description="Start or adopt the shared background daemon for the active runtime root.",
)
def brain_sync_start() -> dict:
    return _daemon_admin_payload(start_daemon())


@server.tool(
    name="brain_sync_stop",
    description="Stop the shared launcher-background daemon when remote control is supported in v1.",
)
def brain_sync_stop() -> dict:
    return _daemon_admin_payload(stop_daemon())


@server.tool(
    name="brain_sync_restart",
    description="Restart the shared launcher-background daemon when remote control is supported in v1.",
)
def brain_sync_restart() -> dict:
    return _daemon_admin_payload(restart_daemon())


# Advertise the full tool surface from process start so MCP clients that cache
# the initial tool list can still use full tools after init/attach in the same
# long-lived launcher session. The tools themselves remain fail-closed until a
# usable active root exists.
_ensure_full_tools_registered()


def main() -> None:
    from brain_sync.runtime.config import load_config
    from brain_sync.util.logging import setup_logging

    log_level = load_config().get("log_level", "INFO")
    setup_logging(log_level)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

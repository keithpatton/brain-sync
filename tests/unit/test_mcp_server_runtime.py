from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.query_index import load_area_index
from brain_sync.application.roots import SetupStatus
from brain_sync.interfaces.mcp.launcher import LauncherRuntime
from brain_sync.interfaces.mcp.server import BrainRuntime, _sync_runtime_root

pytestmark = pytest.mark.unit


def _not_ready_setup() -> SetupStatus:
    return SetupStatus(
        configured_active_root=None,
        usable_active_root=None,
        registered_roots=(),
        reason="no_active_root",
        message="No active brain root is registered in config.json.",
    )


def test_sync_runtime_root_keeps_explicit_runtime_without_global_setup(tmp_path) -> None:
    root = tmp_path / "brain"
    init_brain(root)
    runtime = BrainRuntime(
        root=root,
        area_index=load_area_index(root),
        regen_lock=asyncio.Lock(),
        lifecycle_session_id="mcp:session-1",
    )

    with patch("brain_sync.interfaces.mcp.server.get_setup_status", return_value=_not_ready_setup()):
        _sync_runtime_root(runtime)

    assert runtime.root == root
    assert runtime.lifecycle_session_id == "mcp:session-1"


def test_sync_runtime_root_requires_setup_for_unbound_launcher_runtime() -> None:
    runtime = LauncherRuntime(
        root=None,
        area_index=None,
        regen_lock=asyncio.Lock(),
        lifecycle_session_id=None,
        auto_start_daemon=False,
    )

    with patch("brain_sync.interfaces.mcp.server.get_setup_status", return_value=_not_ready_setup()):
        with pytest.raises(RuntimeError, match="brain_sync_attach_root"):
            _sync_runtime_root(runtime)


def test_sync_runtime_root_rebinds_launcher_runtime_to_active_root(tmp_path) -> None:
    old_root = tmp_path / "brain-old"
    new_root = tmp_path / "brain-new"
    init_brain(old_root)
    init_brain(new_root)
    runtime = LauncherRuntime(
        root=old_root,
        area_index=load_area_index(old_root),
        regen_lock=asyncio.Lock(),
        lifecycle_session_id="mcp:session-1",
        auto_start_daemon=True,
    )
    ready_setup = SetupStatus(
        configured_active_root=new_root,
        usable_active_root=new_root,
        registered_roots=(new_root,),
        reason=None,
        message="Active brain root is ready.",
    )

    with (
        patch("brain_sync.interfaces.mcp.server.get_setup_status", return_value=ready_setup),
        patch("brain_sync.interfaces.mcp.server.ensure_lifecycle_session", return_value="mcp:session-2"),
    ):
        _sync_runtime_root(runtime)

    assert runtime.root == new_root
    assert runtime.lifecycle_session_id == "mcp:session-2"

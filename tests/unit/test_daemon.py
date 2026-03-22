from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest

import brain_sync.runtime.repository as runtime_repository
from brain_sync.application.init import init_brain
from brain_sync.application.source_state import SourceState, SyncState, load_state
from brain_sync.application.sources import add_source
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import read_source_manifest
from brain_sync.runtime.child_requests import load_child_discovery_request
from brain_sync.runtime.repository import DaemonAlreadyRunningError, load_source_lifecycle_runtime
from brain_sync.sources.base import RemoteSourceMissingError
from brain_sync.sync.daemon import _sync_scheduler_state, run

pytestmark = pytest.mark.unit


@dataclass
class _FakeSourceReconcileResult:
    updated: list[Any]
    not_found: list[str]
    marked_missing: list[str] | None = None
    deleted: list[str] | None = None
    reappeared: list[str] | None = None

    def __post_init__(self) -> None:
        if self.marked_missing is None:
            self.marked_missing = []
        if self.deleted is None:
            self.deleted = []
        if self.reappeared is None:
            self.reappeared = []


@dataclass
class _FakeTreeReconcileResult:
    orphans_cleaned: list[str]
    content_changed: list[str]
    enqueued_paths: list[str]


class _FakeScheduler:
    def __init__(self) -> None:
        self._scheduled_keys: set[str] = set()
        self._popped = False
        self.immediate_calls: list[str] = []
        self.persisted_calls: list[str] = []
        self.removed_calls: list[str] = []

    def schedule_from_persisted(self, canonical_id: str, _next_check_utc: str, _interval_seconds: int) -> None:
        self._scheduled_keys.add(canonical_id)
        self.persisted_calls.append(canonical_id)

    def schedule_immediate(self, canonical_id: str) -> None:
        self._scheduled_keys.add(canonical_id)
        self.immediate_calls.append(canonical_id)

    def pop_due(self) -> list[str]:
        if self._popped:
            return []
        self._popped = True
        return sorted(self._scheduled_keys)

    def remove(self, canonical_id: str) -> None:
        self._scheduled_keys.discard(canonical_id)
        self.removed_calls.append(canonical_id)

    def reschedule(self, _canonical_id: str, _interval: int) -> None:
        pass

    def next_due_in(self) -> None:
        return None


class _FakeWatcher:
    def __init__(self, _root: Path) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def drain_moves(self) -> list[Any]:
        return []

    def drain_events(self) -> set[Path]:
        return set()


class _DeletingWatcher:
    def __init__(self, root: Path) -> None:
        self._file = root / "knowledge" / "area" / "c12345-test-page.md"
        self._emitted = False

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def drain_moves(self) -> list[Any]:
        return []

    def drain_events(self) -> set[Path]:
        if self._emitted:
            return set()
        self._file.unlink()
        self._emitted = True
        return {self._file.parent}


class _TwoEventWatcher:
    def __init__(self, root: Path) -> None:
        self._events = [
            root / "knowledge" / "area",
            root / "knowledge" / "other",
        ]

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def drain_moves(self) -> list[Any]:
        return []

    def drain_events(self) -> set[Path]:
        if not self._events:
            return set()
        return {self._events.pop(0)}


class _FakeRegenQueue:
    def __init__(self, **_: Any) -> None:
        pass

    def enqueue(self, _knowledge_path: str) -> None:
        pass

    async def process_ready(self) -> int:
        return 0

    def next_fire_in(self) -> None:
        return None


@asynccontextmanager
async def _fake_regen_session(_root: Path, reclaim_stale: bool = True):
    yield SimpleNamespace(owner_id="owner-1", session_id="session-1")


async def _run_daemon_once(root: Path, fetch_children_flags: list[bool], *, missing: bool = False) -> None:
    async def _fake_process_source(
        _source_state,
        _http_client,
        root=None,
        *,
        fetch_children=False,
        lifecycle_owner_id=None,
    ):
        fetch_children_flags.append(fetch_children)
        assert lifecycle_owner_id is not None
        if missing:
            raise RemoteSourceMissingError(source_type="confluence", source_id="12345", details="404")
        return False, []

    async def _stop_after_tick(_seconds: float) -> None:
        raise asyncio.CancelledError()

    with (
        patch(
            "brain_sync.sync.daemon.reconcile_sources",
            return_value=_FakeSourceReconcileResult(updated=[], not_found=[]),
        ),
        patch(
            "brain_sync.sync.daemon.reconcile_knowledge_tree",
            return_value=_FakeTreeReconcileResult(orphans_cleaned=[], content_changed=[], enqueued_paths=[]),
        ),
        patch("brain_sync.sync.daemon.Scheduler", _FakeScheduler),
        patch("brain_sync.sync.daemon.KnowledgeWatcher", _FakeWatcher),
        patch("brain_sync.sync.daemon.RegenQueue", _FakeRegenQueue),
        patch("brain_sync.sync.daemon.process_source", side_effect=_fake_process_source),
        patch("brain_sync.regen.lifecycle.regen_session", _fake_regen_session),
        patch("brain_sync.sync.daemon.asyncio.sleep", side_effect=_stop_after_tick),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run(root)


@pytest.mark.asyncio
async def test_daemon_consumes_and_clears_child_discovery_request_once(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)

    result = add_source(
        root,
        url="test://doc/child-request",
        target_path="area",
        fetch_children=True,
        child_path="children",
    )

    observed_flags: list[bool] = []

    await _run_daemon_once(root, observed_flags)
    assert observed_flags == [True]
    assert load_child_discovery_request(root, result.canonical_id) is None

    await _run_daemon_once(root, observed_flags)
    assert observed_flags == [True, False]


@pytest.mark.asyncio
async def test_daemon_routes_upstream_404_into_missing_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)

    result = add_source(
        root,
        url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Page",
        target_path="area",
    )

    observed_flags: list[bool] = []

    await _run_daemon_once(root, observed_flags, missing=True)

    manifest = read_source_manifest(root, result.canonical_id)
    assert manifest is not None
    assert manifest.knowledge_state == "missing"
    runtime_state = load_source_lifecycle_runtime(root, result.canonical_id)
    assert runtime_state is not None
    assert runtime_state.missing_confirmation_count >= 1
    assert result.canonical_id not in load_state(root).sources


@pytest.mark.asyncio
async def test_daemon_uses_non_finalizing_reconcile_for_watcher_events(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    add_source(root, url="test://doc/reconcile-mode", target_path="area")
    (root / "knowledge" / "other").mkdir(parents=True)

    observed_finalize_flags: list[bool] = []

    def _fake_reconcile(root_arg: Path, *, finalize_missing: bool = True, lifecycle_session_id: str | None = None):
        assert root_arg == root
        assert lifecycle_session_id is not None
        observed_finalize_flags.append(finalize_missing)
        return _FakeSourceReconcileResult(updated=[], not_found=[])

    async def _stop_after_tick(_seconds: float) -> None:
        raise asyncio.CancelledError()

    with (
        patch("brain_sync.sync.daemon.reconcile_sources", side_effect=_fake_reconcile),
        patch(
            "brain_sync.sync.daemon.reconcile_knowledge_tree",
            return_value=_FakeTreeReconcileResult(orphans_cleaned=[], content_changed=[], enqueued_paths=[]),
        ),
        patch("brain_sync.sync.daemon.Scheduler", _FakeScheduler),
        patch("brain_sync.sync.daemon.KnowledgeWatcher", _TwoEventWatcher),
        patch("brain_sync.sync.daemon.RegenQueue", _FakeRegenQueue),
        patch("brain_sync.sync.daemon.process_source", return_value=(False, [])),
        patch("brain_sync.regen.lifecycle.regen_session", _fake_regen_session),
        patch("brain_sync.sync.daemon.asyncio.sleep", side_effect=_stop_after_tick),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run(root)

    assert observed_finalize_flags == [False, False]


def test_sync_scheduler_state_removes_stale_keys_and_restarts_reappeared_sources_immediately() -> None:
    scheduler = _FakeScheduler()
    scheduler._scheduled_keys = {"confluence:12345", "confluence:99999"}
    state = SyncState(
        sources={
            "confluence:12345": SourceState(
                canonical_id="confluence:12345",
                source_url="https://example.com/12345",
                source_type="confluence",
                knowledge_path="area/c12345.md",
            )
        }
    )

    _sync_scheduler_state(state, cast(Any, scheduler))

    assert "confluence:99999" in scheduler.removed_calls
    assert scheduler.immediate_calls == ["confluence:12345"]


@pytest.mark.asyncio
async def test_daemon_marks_live_local_delete_missing_before_due_poll(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)

    result = add_source(
        root,
        url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Page",
        target_path="area",
    )
    materialized = root / "knowledge" / "area" / "c12345-test-page.md"
    materialized.parent.mkdir(parents=True, exist_ok=True)
    materialized.write_text(prepend_managed_header(result.canonical_id, "# Page"), encoding="utf-8")
    manifest = read_source_manifest(root, result.canonical_id)
    assert manifest is not None
    manifest.knowledge_state = "materialized"
    manifest.knowledge_path = "area/c12345-test-page.md"
    manifest.content_hash = "sha256:abc"
    manifest.remote_fingerprint = "rev-1"
    manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
    from brain_sync.brain.manifest import write_source_manifest

    write_source_manifest(root, manifest)

    async def _process_source_should_not_run(*_args, **_kwargs):
        raise AssertionError("watcher-triggered reconcile should remove missing sources before polling")

    async def _stop_after_tick(_seconds: float) -> None:
        raise asyncio.CancelledError()

    with (
        patch(
            "brain_sync.sync.daemon.reconcile_knowledge_tree",
            return_value=_FakeTreeReconcileResult(orphans_cleaned=[], content_changed=[], enqueued_paths=[]),
        ),
        patch("brain_sync.sync.daemon.Scheduler", _FakeScheduler),
        patch("brain_sync.sync.daemon.KnowledgeWatcher", _DeletingWatcher),
        patch("brain_sync.sync.daemon.RegenQueue", _FakeRegenQueue),
        patch("brain_sync.sync.daemon.process_source", side_effect=_process_source_should_not_run),
        patch("brain_sync.regen.lifecycle.regen_session", _fake_regen_session),
        patch("brain_sync.sync.daemon.asyncio.sleep", side_effect=_stop_after_tick),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run(root)

    manifest = read_source_manifest(root, result.canonical_id)
    assert manifest is not None
    assert manifest.knowledge_state == "missing"
    runtime_state = load_source_lifecycle_runtime(root, result.canonical_id)
    assert runtime_state is not None
    assert runtime_state.missing_confirmation_count >= 1
    assert result.canonical_id not in load_state(root).sources


@pytest.mark.asyncio
async def test_daemon_refuses_second_active_daemon(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)

    with (
        patch("brain_sync.sync.daemon.acquire_daemon_start_guard", side_effect=DaemonAlreadyRunningError(4242)),
        patch("brain_sync.sync.daemon.write_daemon_status") as mock_status,
    ):
        with pytest.raises(DaemonAlreadyRunningError):
            await run(root)

    mock_status.assert_not_called()


@pytest.mark.asyncio
async def test_daemon_startup_prunes_operational_events_before_loading_state(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()

    call_order: list[str] = []

    def _stop_after_state_load(_root: Path) -> Any:
        call_order.append("load_active_sync_state")
        raise RuntimeError("stop after startup pruning")

    with (
        patch("brain_sync.sync.daemon.acquire_daemon_start_guard", return_value=SimpleNamespace(daemon_id="daemon-1")),
        patch("brain_sync.sync.daemon.release_daemon_start_guard"),
        patch("brain_sync.sync.daemon.write_daemon_status"),
        patch("brain_sync.sync.daemon.ensure_lifecycle_session", return_value="session-1"),
        patch(
            "brain_sync.sync.daemon.reconcile_sources",
            return_value=_FakeSourceReconcileResult(updated=[], not_found=[]),
        ),
        patch(
            "brain_sync.sync.daemon.reconcile_knowledge_tree",
            return_value=_FakeTreeReconcileResult(orphans_cleaned=[], content_changed=[], enqueued_paths=[]),
        ),
        patch(
            "brain_sync.sync.daemon.prune_token_events",
            side_effect=lambda *, retention_days: call_order.append("prune_token_events"),
        ),
        patch(
            "brain_sync.sync.daemon.prune_operational_events",
            side_effect=lambda *, retention_days: call_order.append("prune_operational_events"),
        ),
        patch("brain_sync.sync.daemon.load_active_sync_state", side_effect=_stop_after_state_load),
    ):
        with pytest.raises(RuntimeError, match="stop after startup pruning"):
            await run(root)

    assert call_order == [
        "prune_token_events",
        "prune_operational_events",
        "load_active_sync_state",
    ]


@pytest.mark.asyncio
async def test_daemon_startup_treats_operational_event_prune_failure_as_non_fatal(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()

    call_order: list[str] = []
    runtime_repository._event_failure_logged = False

    def _stop_after_state_load(_root: Path) -> Any:
        call_order.append("load_active_sync_state")
        raise RuntimeError("stop after non-fatal prune failure")

    def _boom() -> Any:
        raise sqlite3.OperationalError("disk full")

    def _prune_operational_events(*, retention_days: int) -> int:
        call_order.append("prune_operational_events")
        return runtime_repository.prune_operational_events(retention_days=retention_days)

    with (
        patch("brain_sync.sync.daemon.acquire_daemon_start_guard", return_value=SimpleNamespace(daemon_id="daemon-1")),
        patch("brain_sync.sync.daemon.release_daemon_start_guard"),
        patch("brain_sync.sync.daemon.write_daemon_status"),
        patch("brain_sync.sync.daemon.ensure_lifecycle_session", return_value="session-1"),
        patch(
            "brain_sync.sync.daemon.reconcile_sources",
            return_value=_FakeSourceReconcileResult(updated=[], not_found=[]),
        ),
        patch(
            "brain_sync.sync.daemon.reconcile_knowledge_tree",
            return_value=_FakeTreeReconcileResult(orphans_cleaned=[], content_changed=[], enqueued_paths=[]),
        ),
        patch(
            "brain_sync.sync.daemon.prune_token_events",
            side_effect=lambda *, retention_days: call_order.append("prune_token_events"),
        ),
        patch("brain_sync.sync.daemon.prune_operational_events", side_effect=_prune_operational_events),
        patch("brain_sync.sync.daemon.load_active_sync_state", side_effect=_stop_after_state_load),
        patch("brain_sync.runtime.repository._connect_runtime", side_effect=_boom),
    ):
        with pytest.raises(RuntimeError, match="stop after non-fatal prune failure"):
            await run(root)

    assert call_order == [
        "prune_token_events",
        "prune_operational_events",
        "load_active_sync_state",
    ]

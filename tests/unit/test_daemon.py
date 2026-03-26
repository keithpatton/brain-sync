from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast
from unittest.mock import patch

import pytest

import brain_sync.runtime.repository as runtime_repository
from brain_sync.application.init import init_brain
from brain_sync.application.source_state import SourceState, SyncState, load_state
from brain_sync.application.sources import add_source
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import read_source_manifest
from brain_sync.runtime.child_requests import load_child_discovery_request
from brain_sync.runtime.repository import (
    DaemonAlreadyRunningError,
    SyncProgress,
    load_source_lifecycle_runtime,
    load_sync_progress,
    save_source_sync_progress,
)
from brain_sync.sources.base import RemoteSourceMissingError
from brain_sync.sync.daemon import _order_due_batch, _sync_scheduler_state, run
from brain_sync.sync.lifecycle import sync_active_source_once

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


def _source_state(
    canonical_id: str,
    *,
    knowledge_state: str,
    materialized_utc: str | None = None,
) -> SourceState:
    return SourceState(
        canonical_id=canonical_id,
        source_url=f"https://example.com/{canonical_id.rsplit(':', 1)[-1]}",
        source_type="confluence",
        knowledge_path=f"area/{canonical_id.rsplit(':', 1)[-1]}.md",
        knowledge_state=knowledge_state,
        materialized_utc=materialized_utc,
    )


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
        patch("brain_sync.sync.lifecycle.process_source", side_effect=_fake_process_source),
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
async def test_daemon_persists_last_checked_utc_after_processing_source(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)

    result = add_source(
        root,
        url="test://doc/persist-last-checked",
        target_path="area",
    )
    checked_utc = "2026-03-25T08:49:06+00:00"

    async def _fake_process_source(
        source_state,
        _http_client,
        root=None,
        *,
        fetch_children=False,
        lifecycle_owner_id=None,
    ):
        assert root is not None
        assert fetch_children is False
        assert lifecycle_owner_id is not None
        source_state.last_checked_utc = checked_utc
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
        patch("brain_sync.sync.lifecycle.process_source", side_effect=_fake_process_source),
        patch("brain_sync.regen.lifecycle.regen_session", _fake_regen_session),
        patch("brain_sync.sync.daemon.asyncio.sleep", side_effect=_stop_after_tick),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run(root)

    progress = load_sync_progress(root)
    assert progress[result.canonical_id].last_checked_utc == checked_utc


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
        patch("brain_sync.sync.lifecycle.process_source", return_value=(False, [])),
        patch("brain_sync.regen.lifecycle.regen_session", _fake_regen_session),
        patch("brain_sync.sync.daemon.asyncio.sleep", side_effect=_stop_after_tick),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run(root)

    assert observed_finalize_flags == [False, False]


def test_order_due_batch_prioritizes_awaiting_before_stale() -> None:
    due_keys = ["confluence:200", "confluence:100"]
    sources = {
        "confluence:100": _source_state("confluence:100", knowledge_state="awaiting"),
        "confluence:200": _source_state(
            "confluence:200",
            knowledge_state="stale",
            materialized_utc="2026-03-20T09:00:00+00:00",
        ),
    }

    assert _order_due_batch(due_keys, sources) == ["confluence:100", "confluence:200"]


def test_order_due_batch_prioritizes_stale_before_settled_sources() -> None:
    due_keys = ["confluence:300", "confluence:200"]
    sources = {
        "confluence:200": _source_state(
            "confluence:200",
            knowledge_state="stale",
            materialized_utc="2026-03-20T09:00:00+00:00",
        ),
        "confluence:300": _source_state(
            "confluence:300",
            knowledge_state="materialized",
            materialized_utc="2026-03-21T09:00:00+00:00",
        ),
    }

    assert _order_due_batch(due_keys, sources) == ["confluence:200", "confluence:300"]


def test_order_due_batch_prefers_newer_materialized_sources() -> None:
    due_keys = ["confluence:old", "confluence:new"]
    sources = {
        "confluence:new": _source_state(
            "confluence:new",
            knowledge_state="materialized",
            materialized_utc="2026-03-22T09:00:00+00:00",
        ),
        "confluence:old": _source_state(
            "confluence:old",
            knowledge_state="materialized",
            materialized_utc="2026-03-20T09:00:00+00:00",
        ),
    }

    assert _order_due_batch(due_keys, sources) == ["confluence:new", "confluence:old"]


def test_order_due_batch_uses_canonical_id_as_deterministic_tie_breaker() -> None:
    due_keys = ["confluence:beta", "confluence:alpha"]
    sources = {
        "confluence:alpha": _source_state(
            "confluence:alpha",
            knowledge_state="materialized",
            materialized_utc="2026-03-22T09:00:00+00:00",
        ),
        "confluence:beta": _source_state(
            "confluence:beta",
            knowledge_state="materialized",
            materialized_utc="2026-03-22T09:00:00+00:00",
        ),
    }

    assert _order_due_batch(due_keys, sources) == ["confluence:alpha", "confluence:beta"]


def test_order_due_batch_sorts_settled_sources_without_materialized_utc_last() -> None:
    due_keys = ["confluence:none-b", "confluence:dated", "confluence:none-a"]
    sources = {
        "confluence:dated": _source_state(
            "confluence:dated",
            knowledge_state="materialized",
            materialized_utc="2026-03-22T09:00:00+00:00",
        ),
        "confluence:none-a": _source_state("confluence:none-a", knowledge_state="materialized"),
        "confluence:none-b": _source_state("confluence:none-b", knowledge_state="materialized"),
    }

    assert _order_due_batch(due_keys, sources) == [
        "confluence:dated",
        "confluence:none-a",
        "confluence:none-b",
    ]


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


def test_sync_scheduler_state_reloads_persisted_due_time_for_existing_key() -> None:
    scheduler = _FakeScheduler()
    scheduler._scheduled_keys = {"confluence:12345"}
    state = SyncState(
        sources={
            "confluence:12345": SourceState(
                canonical_id="confluence:12345",
                source_url="https://example.com/12345",
                source_type="confluence",
                knowledge_path="area/c12345.md",
                next_check_utc="2026-03-26T00:00:00+00:00",
                interval_seconds=1800,
            )
        }
    )

    _sync_scheduler_state(state, cast(Any, scheduler))

    assert scheduler.removed_calls == ["confluence:12345"]
    assert scheduler.persisted_calls == ["confluence:12345"]
    assert scheduler.immediate_calls == []


@pytest.mark.asyncio
async def test_sync_active_source_once_prefers_remote_last_changed_over_materialized_time(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)

    result = add_source(
        root,
        url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Page",
        target_path="area",
    )
    manifest = read_source_manifest(root, result.canonical_id)
    assert manifest is not None
    manifest.knowledge_state = "materialized"
    manifest.knowledge_path = "area/c12345-page.md"
    manifest.content_hash = "sha256:abc"
    manifest.remote_fingerprint = "rev-1"
    manifest.materialized_utc = "2026-03-26T00:00:00+00:00"
    from brain_sync.brain.manifest import write_source_manifest

    write_source_manifest(root, manifest)
    save_source_sync_progress(
        root,
        result.canonical_id,
        SyncProgress(
            canonical_id=result.canonical_id,
            remote_last_changed_utc="2025-11-01T00:00:00+00:00",
        ),
    )

    async def _fake_process_source(
        source_state,
        _http_client,
        root=None,
        *,
        fetch_children=False,
        lifecycle_owner_id=None,
    ):
        assert root is not None
        assert fetch_children is False
        assert lifecycle_owner_id is not None
        source_state.last_checked_utc = "2026-03-26T01:00:00+00:00"
        return False, []

    with patch("brain_sync.sync.lifecycle.process_source", side_effect=_fake_process_source):
        outcome = await sync_active_source_once(root, result.canonical_id, object())

    assert outcome.result_state == "unchanged"
    assert outcome.current_interval_secs == 24 * 3600


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
        patch("brain_sync.sync.lifecycle.process_source", side_effect=_process_source_should_not_run),
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
async def test_daemon_processes_due_batch_in_sorted_priority_order(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)

    awaiting = add_source(
        root,
        url="https://acme.atlassian.net/wiki/spaces/ENG/pages/100/Awaiting",
        target_path="area",
    )
    stale = add_source(
        root,
        url="https://acme.atlassian.net/wiki/spaces/ENG/pages/200/Stale",
        target_path="area",
    )
    newest = add_source(
        root,
        url="https://acme.atlassian.net/wiki/spaces/ENG/pages/300/Newest",
        target_path="area",
    )
    oldest = add_source(
        root,
        url="https://acme.atlassian.net/wiki/spaces/ENG/pages/400/Oldest",
        target_path="area",
    )

    manifest_updates: list[tuple[str, Literal["stale", "materialized"], str]] = [
        (stale.canonical_id, "stale", "2026-03-20T09:00:00+00:00"),
        (newest.canonical_id, "materialized", "2026-03-22T09:00:00+00:00"),
        (oldest.canonical_id, "materialized", "2026-03-19T09:00:00+00:00"),
    ]
    for canonical_id, knowledge_state, materialized_utc in manifest_updates:
        manifest = read_source_manifest(root, canonical_id)
        assert manifest is not None
        manifest.knowledge_state = knowledge_state
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = materialized_utc
        from brain_sync.brain.manifest import write_source_manifest

        write_source_manifest(root, manifest)

    due_order = [
        oldest.canonical_id,
        stale.canonical_id,
        awaiting.canonical_id,
        newest.canonical_id,
    ]
    processed: list[str] = []

    class _PriorityProofScheduler(_FakeScheduler):
        def pop_due(self) -> list[str]:
            if self._popped:
                return []
            self._popped = True
            return list(due_order)

    async def _fake_process_source(
        source_state,
        _http_client,
        root=None,
        *,
        fetch_children=False,
        lifecycle_owner_id=None,
    ):
        assert root is not None
        assert fetch_children is False
        assert lifecycle_owner_id is not None
        processed.append(source_state.canonical_id)
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
        patch("brain_sync.sync.daemon.Scheduler", _PriorityProofScheduler),
        patch("brain_sync.sync.daemon.KnowledgeWatcher", _FakeWatcher),
        patch("brain_sync.sync.daemon.RegenQueue", _FakeRegenQueue),
        patch("brain_sync.sync.lifecycle.process_source", side_effect=_fake_process_source),
        patch("brain_sync.regen.lifecycle.regen_session", _fake_regen_session),
        patch("brain_sync.sync.daemon.asyncio.sleep", side_effect=_stop_after_tick),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run(root)

    assert processed == [
        awaiting.canonical_id,
        stale.canonical_id,
        newest.canonical_id,
        oldest.canonical_id,
    ]


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

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.source_state import load_state
from brain_sync.application.sources import add_source
from brain_sync.brain.manifest import read_source_manifest
from brain_sync.runtime.child_requests import load_child_discovery_request
from brain_sync.sources.base import RemoteSourceMissingError
from brain_sync.sync.daemon import run

pytestmark = pytest.mark.unit


@dataclass
class _FakeSourceReconcileResult:
    updated: list[Any]
    not_found: list[str]


@dataclass
class _FakeTreeReconcileResult:
    orphans_cleaned: list[str]
    content_changed: list[str]
    enqueued_paths: list[str]


class _FakeScheduler:
    def __init__(self) -> None:
        self._scheduled_keys: set[str] = set()
        self._popped = False

    def schedule_from_persisted(self, canonical_id: str, _next_check_utc: str, _interval_seconds: int) -> None:
        self._scheduled_keys.add(canonical_id)

    def schedule_immediate(self, canonical_id: str) -> None:
        self._scheduled_keys.add(canonical_id)

    def pop_due(self) -> list[str]:
        if self._popped:
            return []
        self._popped = True
        return sorted(self._scheduled_keys)

    def remove(self, canonical_id: str) -> None:
        self._scheduled_keys.discard(canonical_id)

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
    async def _fake_process_source(_source_state, _http_client, root=None, *, fetch_children=False):
        fetch_children_flags.append(fetch_children)
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
    assert manifest.status == "missing"
    assert result.canonical_id not in load_state(root).sources

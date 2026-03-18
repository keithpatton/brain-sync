from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.insights import InsightState, save_insight_state
from brain_sync.application.query_index import invalidate_area_index, load_area_index
from brain_sync.application.reconcile import reconcile_knowledge_tree
from brain_sync.application.sources import add_source, move_source, remove_source, update_source
from brain_sync.application.sync_events import enqueue_regen_path
from brain_sync.regen.queue import RegenQueue
from brain_sync.runtime.repository import (
    clear_child_discovery_request,
    load_operational_events,
    record_operational_event,
    save_child_discovery_request,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    init_brain(root)
    return root


def test_record_operational_event_persists_stable_fields(brain: Path) -> None:
    record_operational_event(
        event_type="regen.completed",
        session_id="session-1",
        owner_id="owner-1",
        canonical_id="test:123",
        knowledge_path="area\\sub",
        outcome="regenerated",
        duration_ms=123,
        details={"kind": "unit"},
    )

    events = load_operational_events(brain)

    assert len(events) == 1
    event = events[0]
    assert event.event_type == "regen.completed"
    assert event.created_utc.endswith("+00:00")
    assert event.session_id == "session-1"
    assert event.owner_id == "owner-1"
    assert event.canonical_id == "test:123"
    assert event.knowledge_path == "area/sub"
    assert event.outcome == "regenerated"
    assert event.duration_ms == 123
    assert json.loads(event.details_json or "{}") == {"kind": "unit"}


def test_record_operational_event_is_non_fatal_on_db_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom():
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr("brain_sync.runtime.repository._connect_runtime", _boom)

    record_operational_event(event_type="regen.failed", outcome="failed")


def test_operational_events_are_append_only(brain: Path) -> None:
    record_operational_event(event_type="event.one", outcome="first")
    record_operational_event(event_type="event.two", outcome="second")

    events = load_operational_events(brain)

    assert [(event.event_type, event.outcome) for event in events] == [
        ("event.one", "first"),
        ("event.two", "second"),
    ]


def test_source_lifecycle_events_are_emitted(brain: Path) -> None:
    added = add_source(root=brain, url="test://doc/source-1", target_path="area")
    update_source(root=brain, source=added.canonical_id, fetch_children=True, child_path="children")
    move_source(root=brain, source=added.canonical_id, to_path="area-moved")
    remove_source(root=brain, source=added.canonical_id, delete_files=False)

    event_types = [event.event_type for event in load_operational_events(brain)]

    assert "source.registered" in event_types
    assert "source.updated" in event_types
    assert "source.moved" in event_types
    assert "source.removed" in event_types


def test_child_request_and_query_index_events_are_emitted(brain: Path) -> None:
    save_child_discovery_request(brain, "test:123", fetch_children=True, child_path="children")
    clear_child_discovery_request(brain, "test:123")

    load_area_index(brain)
    invalidate_area_index(brain, knowledge_paths=["area"], reason="test")
    load_area_index(brain)

    event_types = [event.event_type for event in load_operational_events(brain)]

    assert "source.child_request.saved" in event_types
    assert "source.child_request.cleared" in event_types
    assert "query.index.rebuilt" in event_types
    assert "query.index.invalidated" in event_types


def test_reconcile_events_are_emitted(brain: Path) -> None:
    (brain / "knowledge" / "new-area").mkdir(parents=True, exist_ok=True)
    (brain / "knowledge" / "new-area" / "doc.md").write_text("content", encoding="utf-8")
    save_insight_state(brain, InsightState(knowledge_path="gone", content_hash="abc", regen_status="idle"))

    result = reconcile_knowledge_tree(brain)
    event_types = [event.event_type for event in load_operational_events(brain)]

    assert "gone" in result.orphans_cleaned
    assert "new-area" in result.enqueued_paths
    assert "reconcile.orphan_cleaned" in event_types
    assert "reconcile.path_enqueued" in event_types


def test_regen_enqueued_event_is_not_duplicated(brain: Path) -> None:
    queue = RegenQueue(root=brain, owner_id="owner-1", session_id="session-1")

    enqueue_regen_path(brain, knowledge_path="area", enqueue=queue.enqueue, reason="watcher_change")

    events = load_operational_events(brain, event_type="regen.enqueued")

    assert len(events) == 1
    assert events[0].knowledge_path == "area"


def test_queue_does_not_duplicate_engine_completed_event(
    brain: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = RegenQueue(root=brain, owner_id="owner-1", session_id="session-1")

    async def _fake_regen_path(root: Path, knowledge_path: str, **_: object) -> int:
        record_operational_event(
            event_type="regen.completed",
            session_id="session-1",
            owner_id="owner-1",
            knowledge_path=knowledge_path,
            outcome="regenerated",
        )
        return 1

    monkeypatch.setattr("brain_sync.regen.queue.regen_path", _fake_regen_path)

    count = asyncio.run(queue._process_single("area"))

    events = load_operational_events(brain, event_type="regen.completed")

    assert count == 1
    assert len(events) == 1
    assert events[0].knowledge_path == "area"
    assert events[0].outcome == "regenerated"


def test_queue_does_not_duplicate_engine_failed_event(
    brain: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = RegenQueue(root=brain, owner_id="owner-1", session_id="session-1")

    async def _fake_regen_path(root: Path, knowledge_path: str, **_: object) -> int:
        record_operational_event(
            event_type="regen.failed",
            session_id="session-1",
            owner_id="owner-1",
            knowledge_path=knowledge_path,
            outcome="failed",
            details={"error": "boom"},
        )
        raise RuntimeError("boom")

    monkeypatch.setattr("brain_sync.regen.queue.regen_path", _fake_regen_path)

    count = asyncio.run(queue._process_single("area"))

    events = load_operational_events(brain, event_type="regen.failed")

    assert count == 0
    assert len(events) == 1
    assert events[0].knowledge_path == "area"
    assert events[0].outcome == "failed"

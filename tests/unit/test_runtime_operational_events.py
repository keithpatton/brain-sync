from __future__ import annotations

import asyncio
import inspect
import json
import sqlite3
from pathlib import Path

import pytest

import brain_sync.runtime.repository as state_module
from brain_sync.application.init import init_brain
from brain_sync.application.insights import InsightState, save_insight_state
from brain_sync.application.query_index import invalidate_area_index, load_area_index
from brain_sync.application.reconcile import reconcile_knowledge_tree
from brain_sync.application.sources import add_source, migrate_sources, move_source, remove_source, update_source
from brain_sync.application.sync_events import enqueue_regen_path
from brain_sync.regen.queue import RegenQueue
from brain_sync.runtime.operational_events import (
    CATALOG_EVENT_TYPE_NAMES,
    FIELD_LOCKED_EVENT_FIELDS,
    OPERATIONAL_EVENTS_RETENTION_DAYS,
    OperationalEventType,
)
from brain_sync.runtime.operational_events import (
    load_retention_days as load_operational_event_retention_days,
)
from brain_sync.runtime.repository import (
    clear_child_discovery_request,
    load_operational_events,
    prune_operational_events,
    record_brain_operational_event,
    save_child_discovery_request,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    init_brain(root)
    return root


def _runtime_conn() -> sqlite3.Connection:
    return sqlite3.connect(str(state_module.RUNTIME_DB_FILE))


def _event_details(event: state_module.OperationalEvent) -> dict[str, object]:
    return json.loads(event.details_json or "{}")


def _assert_locked_fields(event: state_module.OperationalEvent) -> None:
    required_fields = FIELD_LOCKED_EVENT_FIELDS[OperationalEventType(event.event_type)]
    details = _event_details(event)

    for field in required_fields:
        if field.startswith("details."):
            detail_key = field.split(".", 1)[1]
            assert detail_key in details
            continue
        assert getattr(event, field) is not None


def test_record_operational_event_persists_stable_fields(brain: Path) -> None:
    record_brain_operational_event(
        brain,
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
    def _boom(_root: Path):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr("brain_sync.runtime.repository._connect", _boom)

    record_brain_operational_event(Path("brain"), event_type="regen.failed", outcome="failed")


def test_operational_events_are_append_only(brain: Path) -> None:
    record_brain_operational_event(brain, event_type="event.one", outcome="first")
    record_brain_operational_event(brain, event_type="event.two", outcome="second")

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

    events = load_operational_events(brain)
    events_by_type = {event.event_type: event for event in events}

    assert events_by_type["source.registered"].canonical_id == added.canonical_id
    assert events_by_type["source.registered"].outcome == "registered"
    _assert_locked_fields(events_by_type["source.registered"])

    assert events_by_type["source.updated"].canonical_id == added.canonical_id
    assert events_by_type["source.updated"].outcome == "updated"
    _assert_locked_fields(events_by_type["source.updated"])

    moved_event = events_by_type["source.moved"]
    assert moved_event.canonical_id == added.canonical_id
    assert moved_event.outcome == "moved"
    assert _event_details(moved_event)["old_path"] == "area"
    assert _event_details(moved_event)["new_path"] == "area-moved"
    _assert_locked_fields(moved_event)

    assert events_by_type["source.removed"].canonical_id == added.canonical_id
    assert events_by_type["source.removed"].outcome == "removed"
    _assert_locked_fields(events_by_type["source.removed"])


def test_migrate_sources_emits_locked_source_updated_rows(brain: Path) -> None:
    added = add_source(root=brain, url="test://doc/source-migrate", target_path="area", sync_attachments=True)
    legacy_dir = brain / "knowledge" / "area" / "_sync-context" / "attachments"
    legacy_dir.mkdir(parents=True, exist_ok=True)
    (legacy_dir / "legacy.bin").write_bytes(b"legacy")

    result = migrate_sources(brain)

    events = load_operational_events(brain, event_type=OperationalEventType.SOURCE_UPDATED)

    assert result.sources_migrated == 1
    assert result.files_migrated == 1
    assert events
    assert events[-1].canonical_id == added.canonical_id
    assert events[-1].outcome == "migrated_legacy_context"
    _assert_locked_fields(events[-1])


def test_child_request_and_query_index_events_are_emitted(brain: Path) -> None:
    save_child_discovery_request(brain, "test:123", fetch_children=True, child_path="children")
    clear_child_discovery_request(brain, "test:123")

    load_area_index(brain)
    invalidate_area_index(brain, knowledge_paths=["area"], reason="test")
    load_area_index(brain)

    saved_events = load_operational_events(brain, event_type=OperationalEventType.SOURCE_CHILD_REQUEST_SAVED)
    cleared_events = load_operational_events(brain, event_type=OperationalEventType.SOURCE_CHILD_REQUEST_CLEARED)
    rebuilt_events = load_operational_events(brain, event_type=OperationalEventType.QUERY_INDEX_REBUILT)
    invalidated_events = load_operational_events(brain, event_type=OperationalEventType.QUERY_INDEX_INVALIDATED)

    assert saved_events[-1].canonical_id == "test:123"
    assert saved_events[-1].outcome == "saved"
    _assert_locked_fields(saved_events[-1])

    assert cleared_events[-1].canonical_id == "test:123"
    assert cleared_events[-1].outcome == "cleared"
    _assert_locked_fields(cleared_events[-1])

    assert rebuilt_events[-1].outcome == "rebuilt"
    _assert_locked_fields(rebuilt_events[-1])

    assert invalidated_events[-1].outcome == "test"
    assert _event_details(invalidated_events[-1])["knowledge_paths"] == ["area"]
    _assert_locked_fields(invalidated_events[-1])


def test_reconcile_events_are_emitted(brain: Path) -> None:
    (brain / "knowledge" / "new-area").mkdir(parents=True, exist_ok=True)
    (brain / "knowledge" / "new-area" / "doc.md").write_text("content", encoding="utf-8")
    save_insight_state(brain, InsightState(knowledge_path="gone", content_hash="abc", regen_status="idle"))

    result = reconcile_knowledge_tree(brain)
    assert "gone" in result.orphans_cleaned
    assert "new-area" in result.enqueued_paths

    cleaned_events = load_operational_events(brain, event_type=OperationalEventType.RECONCILE_ORPHAN_CLEANED)
    enqueued_events = load_operational_events(brain, event_type=OperationalEventType.RECONCILE_PATH_ENQUEUED)

    assert cleaned_events[-1].knowledge_path == "gone"
    assert cleaned_events[-1].outcome == "cleaned"
    _assert_locked_fields(cleaned_events[-1])

    assert enqueued_events[-1].knowledge_path == "new-area"
    assert enqueued_events[-1].outcome == "enqueued"
    _assert_locked_fields(enqueued_events[-1])


def test_regen_enqueued_event_is_not_duplicated(brain: Path) -> None:
    queue = RegenQueue(root=brain, owner_id="owner-1", session_id="session-1")

    enqueue_regen_path(brain, knowledge_path="area", enqueue=queue.enqueue, reason="watcher_change")

    events = load_operational_events(brain, event_type="regen.enqueued")

    assert len(events) == 1
    assert events[0].knowledge_path == "area"
    assert events[0].outcome == "watcher_change"
    _assert_locked_fields(events[0])


def test_queue_does_not_duplicate_engine_completed_event(
    brain: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = RegenQueue(root=brain, owner_id="owner-1", session_id="session-1")

    async def _fake_regen_path(root: Path, knowledge_path: str, **_: object) -> int:
        record_brain_operational_event(
            root,
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
    _assert_locked_fields(events[0])


def test_queue_does_not_duplicate_engine_failed_event(
    brain: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queue = RegenQueue(root=brain, owner_id="owner-1", session_id="session-1")

    async def _fake_regen_path(root: Path, knowledge_path: str, **_: object) -> int:
        record_brain_operational_event(
            root,
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
    assert _event_details(events[0])["error"] == "boom"
    _assert_locked_fields(events[0])


def test_brain_scoped_events_fail_closed_for_temp_root_with_machine_local_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    temp_root = tmp_path / "brain"

    monkeypatch.delenv("BRAIN_SYNC_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.setenv("USERPROFILE", str(home_dir))
    monkeypatch.setenv("APPDATA", str(home_dir / "AppData" / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(home_dir / "AppData" / "Local"))

    record_brain_operational_event(
        temp_root,
        event_type="source.local_file.added",
        knowledge_path="area",
        outcome="added",
    )

    runtime_db = home_dir / ".brain-sync" / "db" / "brain-sync.sqlite"
    assert not runtime_db.exists()


def test_operational_event_catalog_matches_approved_set() -> None:
    assert CATALOG_EVENT_TYPE_NAMES == {
        "query.index.invalidated",
        "query.index.rebuilt",
        "reconcile.missing_marked",
        "reconcile.orphan_cleaned",
        "reconcile.path_enqueued",
        "reconcile.path_updated",
        "regen.completed",
        "regen.enqueued",
        "regen.failed",
        "regen.started",
        "source.child_registered",
        "source.child_request.cleared",
        "source.child_request.saved",
        "source.finalization_lease_conflict",
        "source.finalization_not_found",
        "source.finalization_not_missing",
        "source.finalized",
        "source.local_file.added",
        "source.local_file.removed",
        "source.missing_confirmed",
        "source.missing_marked",
        "source.moved",
        "source.rediscovered",
        "source.registered",
        "source.removed",
        "source.updated",
        "watcher.move_applied",
        "watcher.move_observed",
        "watcher.structure_observed",
    }


def test_field_locked_operational_event_matrix_matches_approved_contract() -> None:
    assert {event_type.value: fields for event_type, fields in FIELD_LOCKED_EVENT_FIELDS.items()} == {
        "regen.started": {"knowledge_path", "session_id", "owner_id"},
        "regen.completed": {"knowledge_path", "session_id", "owner_id", "outcome"},
        "regen.failed": {"knowledge_path", "session_id", "owner_id", "outcome", "details.error"},
        "regen.enqueued": {"knowledge_path", "outcome"},
        "query.index.invalidated": {"outcome", "details.knowledge_paths"},
        "query.index.rebuilt": {"outcome"},
        "watcher.structure_observed": {"knowledge_path", "outcome"},
        "watcher.move_observed": {"knowledge_path", "outcome", "details.src", "details.dest"},
        "watcher.move_applied": {"knowledge_path", "outcome", "details.src", "details.dest"},
        "reconcile.path_updated": {"canonical_id", "outcome", "details.old_path", "details.new_path"},
        "reconcile.path_enqueued": {"knowledge_path", "outcome"},
        "reconcile.orphan_cleaned": {"knowledge_path", "outcome"},
        "reconcile.missing_marked": {"canonical_id", "outcome"},
        "source.updated": {"canonical_id", "outcome"},
        "source.registered": {"canonical_id", "outcome"},
        "source.removed": {"canonical_id", "outcome"},
        "source.moved": {"canonical_id", "outcome", "details.old_path", "details.new_path"},
        "source.missing_marked": {"canonical_id", "outcome"},
        "source.missing_confirmed": {"canonical_id", "outcome"},
        "source.rediscovered": {"canonical_id", "outcome"},
        "source.child_registered": {"canonical_id", "knowledge_path", "outcome", "details.parent_canonical_id"},
        "source.child_request.saved": {"canonical_id", "outcome"},
        "source.child_request.cleared": {"canonical_id", "outcome"},
    }


def test_operational_event_retention_defaults_to_90_days(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("brain_sync.runtime.operational_events.runtime_config.load_config", lambda: {})

    assert load_operational_event_retention_days() == OPERATIONAL_EVENTS_RETENTION_DAYS


def test_prune_operational_events_deletes_old_rows(brain: Path) -> None:
    state_module._connect(brain).close()
    conn = _runtime_conn()
    conn.execute(
        "INSERT INTO operational_events (event_type, created_utc) VALUES (?, ?)",
        ("source.registered", "2025-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    deleted = prune_operational_events(retention_days=90)

    assert deleted == 1


def test_prune_operational_events_keeps_recent_rows(brain: Path) -> None:
    record_brain_operational_event(brain, event_type="source.registered", canonical_id="test:123", outcome="registered")

    deleted = prune_operational_events(retention_days=90)

    assert deleted == 0
    conn = _runtime_conn()
    remaining = conn.execute("SELECT COUNT(*) FROM operational_events").fetchone()[0]
    conn.close()
    assert remaining == 1


def test_prune_operational_events_signature_is_config_dir_scoped_not_root_scoped() -> None:
    assert "root" not in inspect.signature(prune_operational_events).parameters

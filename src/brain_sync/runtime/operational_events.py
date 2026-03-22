"""Shared operational-event catalog and config helpers.

This module centralizes the current production operational-event names and the
field-locked regression contract. Persistence remains owned by
``brain_sync.runtime.repository``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final

import brain_sync.runtime.config as runtime_config

OPERATIONAL_EVENTS_RETENTION_DAYS: Final = 90


@unique
class OperationalEventType(StrEnum):
    QUERY_INDEX_INVALIDATED = "query.index.invalidated"
    QUERY_INDEX_REBUILT = "query.index.rebuilt"
    RECONCILE_MISSING_MARKED = "reconcile.missing_marked"
    RECONCILE_ORPHAN_CLEANED = "reconcile.orphan_cleaned"
    RECONCILE_PATH_ENQUEUED = "reconcile.path_enqueued"
    RECONCILE_PATH_UPDATED = "reconcile.path_updated"
    REGEN_COMPLETED = "regen.completed"
    REGEN_ENQUEUED = "regen.enqueued"
    REGEN_FAILED = "regen.failed"
    REGEN_STARTED = "regen.started"
    SOURCE_CHILD_REGISTERED = "source.child_registered"
    SOURCE_CHILD_REQUEST_CLEARED = "source.child_request.cleared"
    SOURCE_CHILD_REQUEST_SAVED = "source.child_request.saved"
    SOURCE_FINALIZATION_LEASE_CONFLICT = "source.finalization_lease_conflict"
    SOURCE_FINALIZATION_NOT_FOUND = "source.finalization_not_found"
    SOURCE_FINALIZATION_NOT_MISSING = "source.finalization_not_missing"
    SOURCE_FINALIZED = "source.finalized"
    SOURCE_LOCAL_FILE_ADDED = "source.local_file.added"
    SOURCE_LOCAL_FILE_REMOVED = "source.local_file.removed"
    SOURCE_MISSING_CONFIRMED = "source.missing_confirmed"
    SOURCE_MISSING_MARKED = "source.missing_marked"
    SOURCE_MOVED = "source.moved"
    SOURCE_REDISCOVERED = "source.rediscovered"
    SOURCE_REGISTERED = "source.registered"
    SOURCE_REMOVED = "source.removed"
    SOURCE_UPDATED = "source.updated"
    WATCHER_MOVE_APPLIED = "watcher.move_applied"
    WATCHER_MOVE_OBSERVED = "watcher.move_observed"
    WATCHER_STRUCTURE_OBSERVED = "watcher.structure_observed"


@dataclass(frozen=True)
class OperationalEventSpec:
    event_type: OperationalEventType
    required_fields: frozenset[str] = frozenset()

    @property
    def field_locked(self) -> bool:
        return bool(self.required_fields)


FIELD_LOCKED_EVENT_FIELDS: Final[dict[OperationalEventType, frozenset[str]]] = {
    OperationalEventType.REGEN_STARTED: frozenset(
        {"knowledge_path", "session_id", "owner_id", "details.reason", "details.evaluation_outcome"}
    ),
    OperationalEventType.REGEN_COMPLETED: frozenset(
        {"knowledge_path", "session_id", "owner_id", "outcome", "details.reason", "details.propagates_up"}
    ),
    OperationalEventType.REGEN_FAILED: frozenset(
        {"knowledge_path", "session_id", "owner_id", "outcome", "details.error", "details.reason", "details.phase"}
    ),
    OperationalEventType.REGEN_ENQUEUED: frozenset({"knowledge_path", "outcome"}),
    OperationalEventType.QUERY_INDEX_INVALIDATED: frozenset({"outcome", "details.knowledge_paths"}),
    OperationalEventType.QUERY_INDEX_REBUILT: frozenset({"outcome"}),
    OperationalEventType.WATCHER_STRUCTURE_OBSERVED: frozenset({"knowledge_path", "outcome"}),
    OperationalEventType.WATCHER_MOVE_OBSERVED: frozenset({"knowledge_path", "outcome", "details.src", "details.dest"}),
    OperationalEventType.WATCHER_MOVE_APPLIED: frozenset({"knowledge_path", "outcome", "details.src", "details.dest"}),
    OperationalEventType.RECONCILE_PATH_UPDATED: frozenset(
        {"canonical_id", "outcome", "details.old_path", "details.new_path"}
    ),
    OperationalEventType.RECONCILE_PATH_ENQUEUED: frozenset({"knowledge_path", "outcome"}),
    OperationalEventType.RECONCILE_ORPHAN_CLEANED: frozenset({"knowledge_path", "outcome"}),
    OperationalEventType.RECONCILE_MISSING_MARKED: frozenset({"canonical_id", "outcome"}),
    OperationalEventType.SOURCE_UPDATED: frozenset({"canonical_id", "outcome"}),
    OperationalEventType.SOURCE_REGISTERED: frozenset({"canonical_id", "outcome"}),
    OperationalEventType.SOURCE_REMOVED: frozenset({"canonical_id", "outcome"}),
    OperationalEventType.SOURCE_MOVED: frozenset({"canonical_id", "outcome", "details.old_path", "details.new_path"}),
    OperationalEventType.SOURCE_MISSING_MARKED: frozenset({"canonical_id", "outcome"}),
    OperationalEventType.SOURCE_MISSING_CONFIRMED: frozenset({"canonical_id", "outcome"}),
    OperationalEventType.SOURCE_REDISCOVERED: frozenset({"canonical_id", "outcome"}),
    OperationalEventType.SOURCE_CHILD_REGISTERED: frozenset(
        {"canonical_id", "knowledge_path", "outcome", "details.parent_canonical_id"}
    ),
    OperationalEventType.SOURCE_CHILD_REQUEST_SAVED: frozenset({"canonical_id", "outcome"}),
    OperationalEventType.SOURCE_CHILD_REQUEST_CLEARED: frozenset({"canonical_id", "outcome"}),
}

OPERATIONAL_EVENT_SPECS: Final[dict[OperationalEventType, OperationalEventSpec]] = {
    event_type: OperationalEventSpec(
        event_type=event_type,
        required_fields=FIELD_LOCKED_EVENT_FIELDS.get(event_type, frozenset()),
    )
    for event_type in OperationalEventType
}
CATALOG_EVENT_TYPE_NAMES: Final[frozenset[str]] = frozenset(event_type.value for event_type in OperationalEventType)


def event_type_name(event_type: OperationalEventType | str) -> str:
    return event_type.value if isinstance(event_type, OperationalEventType) else event_type


def required_fields_for(event_type: OperationalEventType) -> frozenset[str]:
    return OPERATIONAL_EVENT_SPECS[event_type].required_fields


def load_retention_days() -> int:
    """Read operational_events retention period from config, defaulting to 90 days."""
    cfg = runtime_config.load_config()
    operational_events = cfg.get("operational_events", {})
    if not isinstance(operational_events, dict):
        return OPERATIONAL_EVENTS_RETENTION_DAYS
    retention_days = operational_events.get("retention_days", OPERATIONAL_EVENTS_RETENTION_DAYS)
    if isinstance(retention_days, bool) or not isinstance(retention_days, int):
        return OPERATIONAL_EVENTS_RETENTION_DAYS
    return retention_days


__all__ = [
    "CATALOG_EVENT_TYPE_NAMES",
    "FIELD_LOCKED_EVENT_FIELDS",
    "OPERATIONAL_EVENTS_RETENTION_DAYS",
    "OPERATIONAL_EVENT_SPECS",
    "OperationalEventSpec",
    "OperationalEventType",
    "event_type_name",
    "load_retention_days",
    "required_fields_for",
]

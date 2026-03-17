"""Application-owned cross-plane state models.

These models represent composed views assembled from portable brain state and
machine-local runtime state for application workflows and transports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from os import PathLike
from typing import ClassVar

from brain_sync.brain.tree import normalize_path


class _PathNormalized:
    """Mixin that normalizes persisted knowledge and target paths."""

    _PATH_FIELDS: ClassVar[set[str]] = set()

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._PATH_FIELDS and isinstance(value, str | PathLike):
            value = normalize_path(str(value))
        super().__setattr__(name, value)


@dataclass
class SourceState(_PathNormalized):
    _PATH_FIELDS: ClassVar[set[str]] = {"target_path"}

    canonical_id: str
    source_url: str
    source_type: str
    last_checked_utc: str | None = None
    last_changed_utc: str | None = None
    current_interval_secs: int = 1800
    content_hash: str | None = None
    metadata_fingerprint: str | None = None
    next_check_utc: str | None = None
    interval_seconds: int | None = None
    target_path: str = ""
    sync_attachments: bool = False


@dataclass
class SyncState:
    sources: dict[str, SourceState] = field(default_factory=dict)


@dataclass
class InsightState(_PathNormalized):
    _PATH_FIELDS: ClassVar[set[str]] = {"knowledge_path"}

    knowledge_path: str
    content_hash: str | None = None
    summary_hash: str | None = None
    structure_hash: str | None = None
    regen_started_utc: str | None = None
    last_regen_utc: str | None = None
    regen_status: str = "idle"
    owner_id: str | None = None
    error_reason: str | None = None


__all__ = ["InsightState", "SourceState", "SyncState"]

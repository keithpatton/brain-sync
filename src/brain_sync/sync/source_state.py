"""Sync-owned source state projections.

Builds the active polling view and the administrative registry view from the
portable source manifests plus machine-local runtime state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import ClassVar

from brain_sync.brain.manifest import SourceManifest, read_all_source_manifests
from brain_sync.brain.tree import normalize_path
from brain_sync.runtime.repository import (
    load_all_child_discovery_requests,
    load_sync_progress,
    save_sync_progress,
)


class _PathNormalized:
    _PATH_FIELDS: ClassVar[set[str]] = set()

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._PATH_FIELDS and isinstance(value, str | PathLike):
            value = normalize_path(str(value))
        super().__setattr__(name, value)


@dataclass
class SourceState(_PathNormalized):
    _PATH_FIELDS: ClassVar[set[str]] = {"knowledge_path"}

    canonical_id: str
    source_url: str
    source_type: str
    knowledge_path: str = ""
    knowledge_state: str = "awaiting"
    sync_attachments: bool = False
    content_hash: str | None = None
    remote_fingerprint: str | None = None
    materialized_utc: str | None = None
    last_checked_utc: str | None = None
    current_interval_secs: int = 1800
    next_check_utc: str | None = None
    interval_seconds: int | None = None

    @property
    def target_path(self) -> str:
        return normalize_path(Path(self.knowledge_path).parent)

    @target_path.setter
    def target_path(self, value: str) -> None:
        filename = Path(self.knowledge_path).name
        normalized = normalize_path(value)
        self.knowledge_path = normalize_path(Path(normalized) / filename) if normalized else filename

    @property
    def metadata_fingerprint(self) -> str | None:
        return self.remote_fingerprint

    @metadata_fingerprint.setter
    def metadata_fingerprint(self, value: str | None) -> None:
        self.remote_fingerprint = value

    @property
    def last_changed_utc(self) -> str | None:
        return self.materialized_utc

    @last_changed_utc.setter
    def last_changed_utc(self, value: str | None) -> None:
        self.materialized_utc = value

    @property
    def missing_since_utc(self) -> str | None:
        return None

    @missing_since_utc.setter
    def missing_since_utc(self, value: str | None) -> None:
        del value


@dataclass
class SyncState:
    sources: dict[str, SourceState] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceAdminView:
    canonical_id: str
    source_url: str
    target_path: str
    knowledge_state: str = "materialized"
    last_checked_utc: str | None = None
    last_changed_utc: str | None = None
    current_interval_secs: int = 1800
    fetch_children: bool = False
    sync_attachments: bool = False


def seed_source_state_from_manifest(manifest: SourceManifest) -> SourceState:
    return SourceState(
        canonical_id=manifest.canonical_id,
        source_url=manifest.source_url,
        source_type=manifest.source_type,
        knowledge_path=manifest.knowledge_path,
        knowledge_state=manifest.knowledge_state,
        sync_attachments=manifest.sync_attachments,
        content_hash=manifest.content_hash,
        remote_fingerprint=manifest.remote_fingerprint,
        materialized_utc=manifest.materialized_utc,
    )


def load_active_sync_state(root: Path) -> SyncState:
    progress_by_source = load_sync_progress(root)
    manifests = read_all_source_manifests(root)

    merged: dict[str, SourceState] = {}
    for canonical_id, manifest in manifests.items():
        if manifest.knowledge_state == "missing":
            continue

        state = seed_source_state_from_manifest(manifest)
        progress = progress_by_source.get(canonical_id)
        if progress is not None:
            state.last_checked_utc = progress.last_checked_utc
            state.current_interval_secs = progress.current_interval_secs
            state.next_check_utc = progress.next_check_utc
            state.interval_seconds = progress.interval_seconds
        merged[canonical_id] = state

    return SyncState(sources=merged)


def save_active_sync_state(root: Path, state: SyncState) -> None:
    save_sync_progress(root, state)


def load_admin_source_views(root: Path, *, filter_path: str | None = None) -> list[SourceAdminView]:
    progress_by_source = load_sync_progress(root)
    child_requests = load_all_child_discovery_requests(root)

    results: list[SourceAdminView] = []
    for canonical_id, manifest in sorted(read_all_source_manifests(root).items()):
        target_path = manifest.target_path
        if filter_path and not target_path.startswith(filter_path):
            continue
        progress = progress_by_source.get(canonical_id)
        request = child_requests.get(canonical_id)
        results.append(
            SourceAdminView(
                canonical_id=canonical_id,
                source_url=manifest.source_url,
                target_path=target_path,
                knowledge_state=manifest.knowledge_state,
                last_checked_utc=progress.last_checked_utc if progress is not None else None,
                last_changed_utc=manifest.materialized_utc,
                current_interval_secs=progress.current_interval_secs if progress is not None else 1800,
                fetch_children=request.fetch_children if request is not None else False,
                sync_attachments=manifest.sync_attachments,
            )
        )
    return results

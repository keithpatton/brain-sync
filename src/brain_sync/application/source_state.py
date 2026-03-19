"""Application-owned source state projection.

Composes portable source manifests with machine-local polling state into
source views used by orchestration and transports.
"""

from __future__ import annotations

from pathlib import Path

from brain_sync.application.state_models import SourceState, SyncState
from brain_sync.brain.manifest import SourceManifest, read_all_source_manifests
from brain_sync.runtime.repository import load_sync_progress, save_sync_progress

__all__ = ["SourceState", "SyncState", "load_state", "save_state", "seed_source_state_from_manifest"]


def seed_source_state_from_manifest(manifest: SourceManifest) -> SourceState:
    """Create a source view from portable durable state alone."""
    return SourceState(
        canonical_id=manifest.canonical_id,
        source_url=manifest.source_url,
        source_type=manifest.source_type,
        knowledge_path=manifest.knowledge_path,
        knowledge_state=manifest.knowledge_state,
        sync_attachments=manifest.sync_attachments,
        missing_since_utc=manifest.missing_since_utc,
        content_hash=manifest.content_hash,
        remote_fingerprint=manifest.remote_fingerprint,
        materialized_utc=manifest.materialized_utc,
    )


def load_state(root: Path) -> SyncState:
    """Return application-facing source state by composing manifests with polling progress."""
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


def save_state(root: Path, state: SyncState) -> None:
    """Persist runtime polling state for application-owned source views."""
    save_sync_progress(root, state)

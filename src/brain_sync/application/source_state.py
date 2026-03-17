"""Application-owned source state projection.

Composes portable source manifests with machine-local sync progress into
source views used by orchestration and transports.
"""

from __future__ import annotations

import logging
from pathlib import Path

from brain_sync.application.state_models import SourceState, SyncState
from brain_sync.brain.fileops import path_is_file, read_text
from brain_sync.brain.managed_markdown import strip_managed_header
from brain_sync.brain.manifest import SourceManifest, read_all_source_manifests
from brain_sync.brain.tree import normalize_path
from brain_sync.runtime.repository import load_sync_progress, save_sync_progress

log = logging.getLogger(__name__)

__all__ = ["SourceState", "SyncState", "load_state", "save_state", "seed_source_state_from_hint"]


def seed_source_state_from_hint(root: Path, manifest: SourceManifest, target_path: str) -> SourceState:
    """Create a source view from portable intent, seeding runtime progress when safe."""
    state = SourceState(
        canonical_id=manifest.canonical_id,
        source_url=manifest.source_url,
        source_type=manifest.source_type,
        target_path=target_path,
        sync_attachments=manifest.sync_attachments,
    )

    if manifest.sync_hint and manifest.sync_hint.content_hash and manifest.materialized_path:
        local_file = root / "knowledge" / manifest.materialized_path
        if path_is_file(local_file):
            from brain_sync.brain.fileops import content_hash as compute_hash

            try:
                raw = read_text(local_file, encoding="utf-8")
                body = strip_managed_header(raw)
                local_hash = compute_hash(body.encode("utf-8"))
                if local_hash == manifest.sync_hint.content_hash:
                    state.content_hash = manifest.sync_hint.content_hash
                    state.last_checked_utc = manifest.sync_hint.last_synced_utc
                    if manifest.sync_hint.last_synced_utc:
                        from datetime import datetime, timedelta

                        try:
                            last = datetime.fromisoformat(manifest.sync_hint.last_synced_utc)
                            state.next_check_utc = (last + timedelta(seconds=1800)).isoformat()
                            state.interval_seconds = 1800
                        except (ValueError, TypeError):
                            pass
                    log.info("Seeded %s from sync_hint (hash match)", manifest.canonical_id)
            except OSError:
                pass

    return state


def _target_path_for_manifest(manifest: SourceManifest) -> str:
    target_path = manifest.target_path
    if not target_path and manifest.materialized_path:
        target_path = normalize_path(Path(manifest.materialized_path).parent)
    return target_path


def load_state(root: Path) -> SyncState:
    """Return application-facing source state by composing manifests with sync progress."""
    progress_by_source = load_sync_progress(root)
    manifests = read_all_source_manifests(root)

    merged: dict[str, SourceState] = {}
    for canonical_id, manifest in manifests.items():
        if manifest.status == "missing":
            continue

        target_path = _target_path_for_manifest(manifest)
        progress = progress_by_source.get(canonical_id)
        if progress is None:
            merged[canonical_id] = seed_source_state_from_hint(root, manifest, target_path)
            continue

        merged[canonical_id] = SourceState(
            canonical_id=canonical_id,
            source_url=manifest.source_url,
            source_type=manifest.source_type,
            target_path=target_path,
            sync_attachments=manifest.sync_attachments,
            last_checked_utc=progress.last_checked_utc,
            last_changed_utc=progress.last_changed_utc,
            current_interval_secs=progress.current_interval_secs,
            content_hash=progress.content_hash,
            metadata_fingerprint=progress.metadata_fingerprint,
            next_check_utc=progress.next_check_utc,
            interval_seconds=progress.interval_seconds,
        )

    return SyncState(sources=merged)


def save_state(root: Path, state: SyncState) -> None:
    """Persist runtime sync progress for application-owned source views."""
    save_sync_progress(root, state)

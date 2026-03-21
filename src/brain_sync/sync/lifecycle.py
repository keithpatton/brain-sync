"""Sync-owned source lifecycle orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from brain_sync.brain.manifest import (
    MANIFEST_VERSION,
    SourceManifest,
    derive_provisional_knowledge_path,
    read_all_source_manifests,
    read_source_manifest,
)
from brain_sync.brain.repository import BrainRepository
from brain_sync.brain.tree import normalize_path
from brain_sync.regen import classify_folder_change
from brain_sync.runtime.repository import (
    ChildDiscoveryRequest,
    SourceLifecycleRuntime,
    acquire_source_lifecycle_lease,
    clear_child_discovery_request,
    clear_source_lifecycle_lease,
    delete_source,
    delete_source_lifecycle_runtime,
    ensure_lifecycle_session,
    ensure_source_polling,
    load_all_source_lifecycle_runtime,
    load_child_discovery_request,
    load_source_lifecycle_runtime,
    load_sync_progress,
    record_operational_event,
    record_source_missing_confirmation,
    rename_knowledge_path_prefix,
    renew_source_lifecycle_lease,
    save_child_discovery_request,
    save_source_lifecycle_runtime,
)
from brain_sync.sources import UnsupportedSourceError, canonical_id, detect_source_type, slugify
from brain_sync.sync.pipeline import (
    ChildDiscoveryResult,
    PreparedSourceSync,
    SourceLifecycleLeaseConflictError,
    prepare_source_sync,
)
from brain_sync.sync.source_state import (
    SourceAdminView,
    SourceState,
    SyncState,
    load_active_sync_state,
    load_admin_source_views,
)
from brain_sync.sync.watcher import FolderMove

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AddResult:
    canonical_id: str
    source_url: str
    target_path: str
    fetch_children: bool
    sync_attachments: bool
    child_path: str | None = None


@dataclass(frozen=True)
class RemoveResult:
    result_state: str
    source: str
    canonical_id: str | None = None
    source_url: str | None = None
    target_path: str | None = None
    files_deleted: bool = False
    lease_owner: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class MoveResult:
    result_state: str
    source: str
    new_path: str
    canonical_id: str | None = None
    old_path: str | None = None
    files_moved: bool = False
    lease_owner: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class UpdateResult:
    canonical_id: str
    source_url: str
    fetch_children: bool
    sync_attachments: bool
    child_path: str | None = None


@dataclass(frozen=True)
class MissingObservationResult:
    canonical_id: str
    knowledge_path: str
    knowledge_state: str
    missing_confirmation_count: int
    newly_missing: bool


@dataclass(frozen=True)
class SourceSyncResult:
    changed: bool
    discovered_children: list[ChildDiscoveryResult]


@dataclass
class ReconcileEntry:
    canonical_id: str
    old_path: str
    new_path: str


@dataclass
class ReconcileResult:
    updated: list[ReconcileEntry]
    not_found: list[str]
    unchanged: int
    marked_missing: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    reappeared: list[str] = field(default_factory=list)
    orphan_rows_pruned: int = 0


class SourceAlreadyExistsError(Exception):
    def __init__(self, canonical_id: str, source_url: str, target_path: str):
        self.canonical_id = canonical_id
        self.source_url = source_url
        self.target_path = target_path
        super().__init__(f"Source already registered: {canonical_id}")


class SourceNotFoundError(Exception):
    def __init__(self, source: str):
        self.source = source
        super().__init__(f"Source not found: {source}")


class InvalidChildDiscoveryRequestError(ValueError):
    def __init__(self, child_path: str | None):
        self.child_path = child_path
        super().__init__(
            "child_path requires an active child-discovery request; pass fetch_children=True "
            "or update an already-pending request"
        )


class UnsupportedSourceUrlError(ValueError):
    def __init__(self, source: str):
        self.source = source
        super().__init__(f"Unsupported source URL: {source}")


def _record_query_index_invalidated(*, knowledge_paths: list[str], reason: str) -> None:
    normalized_paths = [normalize_path(path) for path in knowledge_paths]
    record_operational_event(
        event_type="query.index.invalidated",
        knowledge_path=normalized_paths[0] if len(normalized_paths) == 1 else None,
        outcome=reason,
        details={"knowledge_paths": normalized_paths},
    )


def _resolve_source(state: SyncState, source: str) -> str | None:
    if source in state.sources:
        return source
    for resolved_canonical_id, source_state in state.sources.items():
        if source_state.source_url == source:
            return resolved_canonical_id
    return None


def _resolve_source_or_manifest(state: SyncState, root: Path, source: str) -> tuple[str, str, str]:
    canonical_id = _resolve_source(state, source)
    if canonical_id is not None:
        source_state = state.sources[canonical_id]
        return canonical_id, source_state.source_url, source_state.target_path

    manifest = read_source_manifest(root, source)
    if manifest is not None:
        return manifest.canonical_id, manifest.source_url, manifest.target_path

    for manifest in read_all_source_manifests(root).values():
        if manifest.source_url == source:
            return manifest.canonical_id, manifest.source_url, manifest.target_path

    raise SourceNotFoundError(source)


def _try_resolve_source_or_manifest(state: SyncState, root: Path, source: str) -> tuple[str, str, str] | None:
    try:
        return _resolve_source_or_manifest(state, root, source)
    except SourceNotFoundError:
        return None


def _lease_expiry() -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(seconds=30)).isoformat()


def _lease_is_active(runtime_state: SourceLifecycleRuntime) -> bool:
    from datetime import UTC, datetime

    if runtime_state.lease_owner is None:
        return False
    if runtime_state.lease_expires_utc is None:
        return True
    try:
        return datetime.fromisoformat(runtime_state.lease_expires_utc) >= datetime.now(UTC)
    except ValueError:
        return True


def _owner_id(kind: str) -> str:
    import os
    import uuid

    return f"{kind}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _conflicting_active_lease(
    root: Path,
    canonical_id: str,
    *,
    owner_id: str | None = None,
) -> SourceLifecycleRuntime | None:
    runtime_state = load_source_lifecycle_runtime(root, canonical_id)
    if runtime_state is None or not _lease_is_active(runtime_state):
        return None
    if owner_id is not None and runtime_state.lease_owner == owner_id:
        return None
    return runtime_state


def _empty_lifecycle_row(runtime_state: SourceLifecycleRuntime) -> bool:
    return (
        runtime_state.lease_owner is None
        and runtime_state.lease_expires_utc is None
        and runtime_state.local_missing_first_observed_utc is None
        and runtime_state.local_missing_last_confirmed_utc is None
        and runtime_state.missing_confirmation_count == 0
    )


def _deregister_source(
    root: Path,
    *,
    canonical_id: str,
    target_path: str,
    delete_materialized_file: bool,
    delete_attachments: bool,
) -> bool:
    repository = BrainRepository(root)
    files_deleted = False

    if delete_materialized_file:
        files_deleted = repository.remove_source_owned_files(target_path, canonical_id)

    if delete_attachments and not delete_materialized_file:
        files_deleted = repository.remove_source_managed_artifacts(target_path, canonical_id) or files_deleted

    delete_source(root, canonical_id)
    delete_source_lifecycle_runtime(root, canonical_id)
    clear_child_discovery_request(root, canonical_id)
    repository.delete_source_registration(canonical_id)
    return files_deleted


def _revalidate_runtime_row(root: Path, manifest: SourceManifest | None) -> SourceLifecycleRuntime | None:
    if manifest is None:
        return None
    runtime_state = load_source_lifecycle_runtime(root, manifest.canonical_id)
    if runtime_state is None:
        return None
    if _lease_is_active(runtime_state):
        return runtime_state
    if runtime_state.lease_owner is not None or runtime_state.lease_expires_utc is not None:
        runtime_state = SourceLifecycleRuntime(
            canonical_id=runtime_state.canonical_id,
            local_missing_first_observed_utc=runtime_state.local_missing_first_observed_utc,
            local_missing_last_confirmed_utc=runtime_state.local_missing_last_confirmed_utc,
            missing_confirmation_count=runtime_state.missing_confirmation_count,
        )
        if manifest.knowledge_state == "missing" or runtime_state.missing_confirmation_count > 0:
            save_source_lifecycle_runtime(root, runtime_state)
        else:
            delete_source_lifecycle_runtime(root, manifest.canonical_id)
            return None
    if manifest.knowledge_state != "missing" and runtime_state.lease_owner is None:
        delete_source_lifecycle_runtime(root, manifest.canonical_id)
        return None
    return runtime_state


def check_source_exists(root: Path, url: str) -> SourceAlreadyExistsError | None:
    try:
        source_type = detect_source_type(url)
    except UnsupportedSourceError as exc:
        raise UnsupportedSourceUrlError(url) from exc
    canonical = canonical_id(source_type, url)
    manifest = read_source_manifest(root, canonical)
    if manifest is not None:
        return SourceAlreadyExistsError(canonical, manifest.source_url, manifest.target_path)
    return None


def add_source(
    root: Path,
    *,
    url: str,
    target_path: str,
    fetch_children: bool = False,
    sync_attachments: bool = False,
    child_path: str | None = None,
) -> AddResult:
    repository = BrainRepository(root)

    existing = check_source_exists(root, url)
    if existing is not None:
        raise existing
    if child_path is not None and not fetch_children:
        raise InvalidChildDiscoveryRequestError(child_path)

    try:
        source_type = detect_source_type(url)
    except UnsupportedSourceError as exc:
        raise UnsupportedSourceUrlError(url) from exc
    canonical = canonical_id(source_type, url)

    provisional_knowledge_path = derive_provisional_knowledge_path(target_path, canonical)
    repository.save_source_manifest(
        SourceManifest(
            version=MANIFEST_VERSION,
            canonical_id=canonical,
            source_url=url,
            source_type=source_type.value,
            sync_attachments=sync_attachments,
            knowledge_path=provisional_knowledge_path,
            knowledge_state="awaiting",
        )
    )
    ensure_source_polling(root, canonical)
    if fetch_children:
        save_child_discovery_request(
            root,
            canonical,
            fetch_children=fetch_children,
            child_path=child_path,
        )
    repository.ensure_knowledge_dir(target_path)
    _record_query_index_invalidated(knowledge_paths=[target_path], reason="source_registered")
    record_operational_event(
        event_type="source.registered",
        canonical_id=canonical,
        knowledge_path=target_path,
        outcome="registered",
        details={"source_url": url, "sync_attachments": sync_attachments, "fetch_children": fetch_children},
    )
    return AddResult(
        canonical_id=canonical,
        source_url=url,
        target_path=target_path,
        fetch_children=fetch_children,
        sync_attachments=sync_attachments,
        child_path=child_path,
    )


def remove_source(
    root: Path,
    *,
    source: str,
    delete_files: bool = False,
) -> RemoveResult:
    owner_id = _owner_id("remove")
    state = load_active_sync_state(root)
    resolved = _try_resolve_source_or_manifest(state, root, source)
    if resolved is None:
        return RemoveResult(
            result_state="not_found",
            source=source,
            message=f"Source not found: {source}",
        )
    canonical, source_url, target_path = resolved
    acquired, existing = acquire_source_lifecycle_lease(
        root,
        canonical,
        owner_id,
        lease_expires_utc=_lease_expiry(),
    )
    if not acquired:
        return RemoveResult(
            result_state="lease_conflict",
            source=source,
            canonical_id=canonical,
            source_url=source_url,
            target_path=target_path,
            lease_owner=existing.lease_owner if existing is not None else None,
            message=f"Source lifecycle lease is already held for {canonical}",
        )

    try:
        files_deleted = _deregister_source(
            root,
            canonical_id=canonical,
            target_path=target_path,
            delete_materialized_file=True,
            delete_attachments=True,
        )
        _record_query_index_invalidated(knowledge_paths=[target_path], reason="source_removed")
        record_operational_event(
            event_type="source.removed",
            canonical_id=canonical,
            knowledge_path=target_path,
            outcome="removed",
            details={"delete_files": delete_files, "files_deleted": files_deleted},
        )
        return RemoveResult(
            result_state="removed",
            source=source,
            canonical_id=canonical,
            source_url=source_url,
            target_path=target_path,
            files_deleted=files_deleted,
        )
    finally:
        clear_source_lifecycle_lease(root, canonical, owner_id=owner_id)


def list_sources(root: Path, *, filter_path: str | None = None) -> list[SourceAdminView]:
    return load_admin_source_views(root, filter_path=filter_path)


def update_source(
    root: Path,
    *,
    source: str,
    fetch_children: bool | None = None,
    sync_attachments: bool | None = None,
    child_path: str | None = ...,  # type: ignore[assignment]
) -> UpdateResult:
    state = load_active_sync_state(root)
    canonical, source_url, _target_path = _resolve_source_or_manifest(state, root, source)
    manifest = read_source_manifest(root, canonical)
    if manifest is None:
        raise SourceNotFoundError(source)

    existing_request = load_child_discovery_request(root, canonical) or ChildDiscoveryRequest(canonical_id=canonical)
    if sync_attachments is not None:
        BrainRepository(root).update_source_sync_settings(canonical, sync_attachments=sync_attachments)
        manifest = read_source_manifest(root, canonical) or manifest

    next_fetch_children = existing_request.fetch_children
    next_child_path = existing_request.child_path
    if fetch_children is not None:
        next_fetch_children = fetch_children
    if child_path is not ...:
        if child_path is not None and not next_fetch_children:
            raise InvalidChildDiscoveryRequestError(child_path)
        next_child_path = child_path  # type: ignore[assignment]
    if not next_fetch_children:
        next_child_path = None

    save_child_discovery_request(
        root,
        canonical,
        fetch_children=next_fetch_children,
        child_path=next_child_path,
    )
    record_operational_event(
        event_type="source.updated",
        canonical_id=canonical,
        knowledge_path=manifest.target_path,
        outcome="updated",
        details={
            "fetch_children": next_fetch_children,
            "sync_attachments": manifest.sync_attachments,
            "child_path": next_child_path,
        },
    )
    return UpdateResult(
        canonical_id=canonical,
        source_url=source_url,
        fetch_children=next_fetch_children,
        sync_attachments=manifest.sync_attachments,
        child_path=next_child_path,
    )


def observe_missing_source(
    root: Path,
    *,
    canonical_id: str,
    outcome: str,
    lifecycle_session_id: str | None = None,
) -> MissingObservationResult | None:
    repository = BrainRepository(root)
    manifest = read_source_manifest(root, canonical_id)
    if manifest is None:
        return None
    if _conflicting_active_lease(root, canonical_id) is not None:
        return None

    manifest = read_source_manifest(root, canonical_id)
    if manifest is None or _conflicting_active_lease(root, canonical_id) is not None:
        return None

    newly_missing = manifest.knowledge_state != "missing"
    if newly_missing:
        repository.mark_source_missing(canonical_id)

    runtime_state = record_source_missing_confirmation(
        root,
        canonical_id,
        lifecycle_session_id=lifecycle_session_id,
    )
    delete_source(root, canonical_id)

    if newly_missing:
        record_operational_event(
            event_type="source.missing_marked",
            canonical_id=canonical_id,
            knowledge_path=manifest.target_path,
            outcome=outcome,
            details={"source_url": manifest.source_url},
        )
    record_operational_event(
        event_type="source.missing_confirmed",
        canonical_id=canonical_id,
        knowledge_path=manifest.target_path,
        outcome="missing",
        details={"missing_confirmation_count": runtime_state.missing_confirmation_count},
    )
    return MissingObservationResult(
        canonical_id=canonical_id,
        knowledge_path=manifest.target_path,
        knowledge_state="missing",
        missing_confirmation_count=runtime_state.missing_confirmation_count,
        newly_missing=newly_missing,
    )


def _cleanup_runtime_after_materialization(
    root: Path,
    canonical_id: str,
    *,
    lifecycle_owner_id: str | None,
) -> None:
    if lifecycle_owner_id is None:
        delete_source_lifecycle_runtime(root, canonical_id)
        return

    clear_source_lifecycle_lease(root, canonical_id, owner_id=lifecycle_owner_id)
    runtime_state = load_source_lifecycle_runtime(root, canonical_id)
    if runtime_state is None:
        return
    if _empty_lifecycle_row(runtime_state):
        delete_source_lifecycle_runtime(root, canonical_id)


def process_prepared_source(
    root: Path,
    source_state: SourceState,
    prepared: PreparedSourceSync,
    *,
    lifecycle_owner_id: str | None = None,
) -> SourceSyncResult:
    source_state.last_checked_utc = prepared.checked_utc
    if prepared.skip_materialization:
        return SourceSyncResult(changed=False, discovered_children=prepared.discovered_children)

    if lifecycle_owner_id is not None:
        renewed, existing = renew_source_lifecycle_lease(
            root,
            prepared.canonical_id,
            lifecycle_owner_id,
            lease_expires_utc=_lease_expiry(),
        )
        if not renewed:
            raise SourceLifecycleLeaseConflictError(
                canonical_id=prepared.canonical_id,
                lease_owner=existing.lease_owner if existing is not None else None,
            )

    repository = BrainRepository(root)
    materialization = repository.materialize_markdown(
        knowledge_path=source_state.target_path,
        filename=prepared.filename,
        canonical_id=prepared.canonical_id,
        markdown=prepared.markdown,
        source_type=prepared.source_type,
        source_url=prepared.source_url,
        content_hash=prepared.content_hash,
        remote_fingerprint=prepared.remote_fingerprint,
        materialized_utc=prepared.checked_utc,
    )
    source_state.knowledge_path = materialization.materialized_path
    source_state.knowledge_state = "materialized"
    source_state.materialized_utc = prepared.checked_utc
    source_state.content_hash = prepared.content_hash
    source_state.remote_fingerprint = prepared.remote_fingerprint
    ensure_source_polling(root, prepared.canonical_id)
    _cleanup_runtime_after_materialization(
        root,
        prepared.canonical_id,
        lifecycle_owner_id=lifecycle_owner_id,
    )
    for stale_name in materialization.duplicate_files_removed:
        log.warning("Removed duplicate managed file for %s: %s", prepared.canonical_id, stale_name)
    return SourceSyncResult(changed=materialization.changed, discovered_children=prepared.discovered_children)


async def sync_source(
    root: Path,
    source_state: SourceState,
    http_client: httpx.AsyncClient,
    *,
    fetch_children: bool = False,
) -> SourceSyncResult:
    prepared = await prepare_source_sync(
        source_state,
        http_client,
        root=root,
        fetch_children=fetch_children,
    )
    return process_prepared_source(root, source_state, prepared)


def compute_child_target_base(
    *,
    parent_target: str,
    parent_canonical_id: str,
    parent_source_url: str,
    request: ChildDiscoveryRequest,
) -> str:
    if request.child_path == ".":
        return parent_target
    if request.child_path:
        return f"{parent_target}/{request.child_path}" if parent_target else request.child_path

    parent_id = parent_canonical_id.split(":", 1)[1]
    slug = slugify(parent_source_url.rstrip("/").split("/")[-1] or parent_id)
    suffix = f"c{parent_id}-{slug}"
    return f"{parent_target}/{suffix}" if parent_target else suffix


def process_discovered_children(
    root: Path,
    *,
    parent_canonical_id: str,
    parent_source_url: str,
    parent_target: str,
    sync_attachments: bool,
    request: ChildDiscoveryRequest | None,
    discovered_children: list[ChildDiscoveryResult],
    schedule_immediate,
    state: SyncState,
) -> SyncState:
    if request is None or not request.fetch_children:
        return state

    try:
        child_target_base = compute_child_target_base(
            parent_target=parent_target,
            parent_canonical_id=parent_canonical_id,
            parent_source_url=parent_source_url,
            request=request,
        )
        for child in discovered_children:
            try:
                child_result = add_source(
                    root=root,
                    url=child.url,
                    target_path=child_target_base,
                    sync_attachments=sync_attachments,
                )
                refreshed = load_active_sync_state(root).sources.get(child_result.canonical_id)
                if refreshed is not None:
                    state.sources[child_result.canonical_id] = refreshed
                schedule_immediate(child_result.canonical_id)
                record_operational_event(
                    event_type="source.child_registered",
                    canonical_id=child_result.canonical_id,
                    knowledge_path=child_result.target_path,
                    outcome="registered",
                    details={"parent_canonical_id": parent_canonical_id},
                )
            except SourceAlreadyExistsError:
                log.debug("Child %s already registered, skipping", child.canonical_id)
            except Exception as exc:
                log.warning("Failed to add child %s: %s", child.canonical_id, exc)
    finally:
        clear_child_discovery_request(root, parent_canonical_id)

    return state


def move_source(
    root: Path,
    *,
    source: str,
    to_path: str,
) -> MoveResult:
    owner_id = _owner_id("move")
    state = load_active_sync_state(root)
    resolved = _try_resolve_source_or_manifest(state, root, source)
    if resolved is None:
        return MoveResult(
            result_state="not_found",
            source=source,
            new_path=to_path,
            message=f"Source not found: {source}",
        )
    canonical, _source_url, old_path = resolved
    acquired, existing = acquire_source_lifecycle_lease(
        root,
        canonical,
        owner_id,
        lease_expires_utc=_lease_expiry(),
    )
    if not acquired:
        return MoveResult(
            result_state="lease_conflict",
            source=source,
            canonical_id=canonical,
            old_path=old_path,
            new_path=to_path,
            lease_owner=existing.lease_owner if existing is not None else None,
            message=f"Source lifecycle lease is already held for {canonical}",
        )

    repository = BrainRepository(root)
    try:
        manifest = read_source_manifest(root, canonical)
        if manifest is None:
            return MoveResult(
                result_state="not_found",
                source=source,
                new_path=to_path,
                message=f"Source not found: {source}",
            )

        files_moved = False
        if old_path != to_path:
            files_moved = repository.move_knowledge_tree(old_path, to_path)
            if not files_moved:
                repository.move_source_attachment_dir(old_path, to_path, canonical)

        manifest = read_source_manifest(root, canonical)
        if manifest is None:
            return MoveResult(
                result_state="not_found",
                source=source,
                new_path=to_path,
                message=f"Source not found: {source}",
            )
        found = repository.resolve_source_file(manifest).path
        if found is not None:
            repository.sync_manifest_to_found_path(canonical, found)
        else:
            repository.set_source_area_path(canonical, to_path)

        _record_query_index_invalidated(knowledge_paths=[old_path, to_path], reason="source_moved")
        record_operational_event(
            event_type="source.moved",
            canonical_id=canonical,
            knowledge_path=to_path,
            outcome="moved",
            details={"old_path": old_path, "new_path": to_path, "files_moved": files_moved},
        )
        return MoveResult(
            result_state="moved",
            source=source,
            canonical_id=canonical,
            old_path=old_path,
            new_path=to_path,
            files_moved=files_moved,
        )
    finally:
        clear_source_lifecycle_lease(root, canonical, owner_id=owner_id)


def enqueue_regen_path(
    root: Path,
    *,
    knowledge_path: str,
    enqueue,
    reason: str,
    canonical_id: str | None = None,
) -> None:
    enqueue(knowledge_path)
    _record_query_index_invalidated(knowledge_paths=[knowledge_path], reason=reason)
    record_operational_event(
        event_type="regen.enqueued",
        canonical_id=canonical_id,
        knowledge_path=knowledge_path,
        outcome=reason,
    )


@dataclass(frozen=True)
class FolderChangeOutcome:
    knowledge_path: str
    action: str


def handle_watcher_folder_change(
    root: Path,
    *,
    knowledge_path: str,
    enqueue,
) -> FolderChangeOutcome:
    change, _, new_structure_hash = classify_folder_change(root, knowledge_path)
    if change.change_type == "none":
        return FolderChangeOutcome(knowledge_path=knowledge_path, action="ignored")
    if change.structural:
        record_operational_event(
            event_type="watcher.structure_observed",
            knowledge_path=knowledge_path,
            outcome="enqueued",
            details={"new_structure_hash": new_structure_hash},
        )
        enqueue_regen_path(root, knowledge_path=knowledge_path, enqueue=enqueue, reason="structure_only")
        return FolderChangeOutcome(knowledge_path=knowledge_path, action="structure_enqueued")
    enqueue_regen_path(root, knowledge_path=knowledge_path, enqueue=enqueue, reason="watcher_change")
    return FolderChangeOutcome(knowledge_path=knowledge_path, action="enqueued")


def _parent_path(knowledge_path: str) -> str:
    if not knowledge_path:
        return ""
    parts = knowledge_path.rsplit("/", 1)
    return parts[0] if len(parts) > 1 else ""


def apply_folder_move(
    root: Path,
    *,
    move: FolderMove,
    enqueue=None,
) -> None:
    knowledge_root = root / "knowledge"
    repository = BrainRepository(root)

    try:
        src_rel = normalize_path(move.src.relative_to(knowledge_root))
        dest_rel = normalize_path(move.dest.relative_to(knowledge_root))
    except ValueError:
        return

    record_operational_event(
        event_type="watcher.move_observed",
        knowledge_path=dest_rel,
        outcome="observed",
        details={"src": src_rel, "dest": dest_rel},
    )
    rename_knowledge_path_prefix(root, src_rel, dest_rel)
    for manifest in read_all_source_manifests(root).values():
        if manifest.knowledge_path != src_rel and not manifest.knowledge_path.startswith(src_rel + "/"):
            continue
        if _conflicting_active_lease(root, manifest.canonical_id) is not None:
            continue
        repository.apply_folder_move_to_manifest(manifest.canonical_id, src_rel, dest_rel)
    _record_query_index_invalidated(
        knowledge_paths=[src_rel, dest_rel, _parent_path(src_rel), _parent_path(dest_rel)],
        reason="folder_move",
    )
    record_operational_event(
        event_type="watcher.move_applied",
        knowledge_path=dest_rel,
        outcome="applied",
        details={"src": src_rel, "dest": dest_rel},
    )
    if enqueue is not None:
        enqueue_regen_path(root, knowledge_path=dest_rel, enqueue=enqueue, reason="folder_move")
        src_parent = _parent_path(src_rel)
        dest_parent = _parent_path(dest_rel)
        if src_parent != dest_parent:
            enqueue_regen_path(root, knowledge_path=src_parent, enqueue=enqueue, reason="folder_move")


def reconcile_sources(
    root: Path,
    *,
    finalize_missing: bool = False,
    lifecycle_session_id: str | None = None,
) -> ReconcileResult:
    del finalize_missing

    current_lifecycle_session_id = lifecycle_session_id or ensure_lifecycle_session(root, owner_kind="cli")
    knowledge_root = root / "knowledge"
    repository = BrainRepository(root)
    updated: list[ReconcileEntry] = []
    not_found: list[str] = []
    unchanged_count = 0
    marked_missing: list[str] = []
    deleted: list[str] = []
    reappeared: list[str] = []

    all_manifests = read_all_source_manifests(root)
    runtime_rows = load_all_source_lifecycle_runtime(root)
    for runtime_canonical_id, runtime_state in runtime_rows.items():
        manifest = all_manifests.get(runtime_canonical_id)
        if manifest is None:
            if _lease_is_active(runtime_state):
                continue
            delete_source_lifecycle_runtime(root, runtime_canonical_id)
            continue
        _revalidate_runtime_row(root, manifest)

    for manifest_canonical_id, manifest in all_manifests.items():
        resolution = repository.resolve_source_file(manifest)
        found = resolution.path

        if resolution.resolution == "unmaterialized":
            unchanged_count += 1
            continue

        if manifest.knowledge_state == "missing":
            if found is not None:
                if _conflicting_active_lease(root, manifest_canonical_id) is not None:
                    unchanged_count += 1
                    continue
                repository.sync_manifest_to_found_path(manifest_canonical_id, found)
                delete_source_lifecycle_runtime(root, manifest_canonical_id)
                ensure_source_polling(root, manifest_canonical_id)
                reappeared.append(manifest_canonical_id)
                rediscovered_path = normalize_path(found.parent.relative_to(knowledge_root))
                record_operational_event(
                    event_type="source.rediscovered",
                    canonical_id=manifest_canonical_id,
                    knowledge_path=rediscovered_path,
                    outcome="rediscovered",
                )
                record_operational_event(
                    event_type="reconcile.path_updated",
                    canonical_id=manifest_canonical_id,
                    knowledge_path=rediscovered_path,
                    outcome="reappeared",
                )
            else:
                observation = observe_missing_source(
                    root,
                    canonical_id=manifest_canonical_id,
                    outcome="missing",
                    lifecycle_session_id=current_lifecycle_session_id,
                )
                if observation is None:
                    unchanged_count += 1
                    continue
                not_found.append(manifest_canonical_id)
            continue

        if found is not None:
            new_target = normalize_path(found.parent.relative_to(knowledge_root))
            old_target = manifest.target_path
            if _conflicting_active_lease(root, manifest_canonical_id) is not None:
                unchanged_count += 1
                continue
            repository.sync_manifest_to_found_path(manifest_canonical_id, found)
            if new_target != old_target or resolution.resolution != "direct":
                updated.append(
                    ReconcileEntry(
                        canonical_id=manifest_canonical_id,
                        old_path=old_target,
                        new_path=new_target,
                    )
                )
                _record_query_index_invalidated(
                    knowledge_paths=[old_target, new_target],
                    reason="reconcile_path_updated",
                )
                record_operational_event(
                    event_type="reconcile.path_updated",
                    canonical_id=manifest_canonical_id,
                    knowledge_path=new_target,
                    outcome="updated",
                    details={"old_path": old_target, "new_path": new_target},
                )
            else:
                unchanged_count += 1
        else:
            observation = observe_missing_source(
                root,
                canonical_id=manifest_canonical_id,
                outcome="missing",
                lifecycle_session_id=current_lifecycle_session_id,
            )
            if observation is not None:
                marked_missing.append(manifest_canonical_id)
                not_found.append(manifest_canonical_id)
                record_operational_event(
                    event_type="reconcile.missing_marked",
                    canonical_id=manifest_canonical_id,
                    knowledge_path=manifest.target_path,
                    outcome="missing",
                    details={"missing_confirmation_count": observation.missing_confirmation_count},
                )
            else:
                unchanged_count += 1

    orphan_count = 0
    for runtime_canonical in load_sync_progress(root):
        if runtime_canonical not in all_manifests:
            delete_source(root, runtime_canonical)
            orphan_count += 1

    return ReconcileResult(
        updated=updated,
        not_found=not_found,
        unchanged=unchanged_count,
        marked_missing=marked_missing,
        deleted=deleted,
        reappeared=reappeared,
        orphan_rows_pruned=orphan_count,
    )

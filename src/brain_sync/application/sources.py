"""Source management commands — importable Python API."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from brain_sync.application.query_index import invalidate_area_index
from brain_sync.application.roots import _require_root
from brain_sync.application.source_state import SourceState, SyncState, load_state, save_state
from brain_sync.brain.fileops import (
    canonical_prefix,
    path_is_dir,
    rglob_paths,
)
from brain_sync.brain.manifest import (
    MANIFEST_VERSION,
    SourceManifest,
    read_all_source_manifests,
    read_source_manifest,
)
from brain_sync.brain.repository import BrainRepository
from brain_sync.brain.tree import normalize_path
from brain_sync.runtime.repository import (
    ChildDiscoveryRequest,
    clear_child_discovery_request,
    load_all_child_discovery_requests,
    load_child_discovery_request,
    load_sync_progress,
    record_operational_event,
    save_child_discovery_request,
)
from brain_sync.runtime.repository import (
    delete_source as db_delete_source,
)
from brain_sync.sources import UnsupportedSourceError, canonical_id, detect_source_type

log = logging.getLogger(__name__)


@dataclass
class AddResult:
    canonical_id: str
    source_url: str
    target_path: str
    fetch_children: bool
    sync_attachments: bool
    child_path: str | None = None


@dataclass
class RemoveResult:
    canonical_id: str
    source_url: str
    target_path: str
    files_deleted: bool


@dataclass
class SourceInfo:
    canonical_id: str
    source_url: str
    target_path: str
    last_checked_utc: str | None
    last_changed_utc: str | None
    current_interval_secs: int
    fetch_children: bool
    sync_attachments: bool


@dataclass
class MoveResult:
    canonical_id: str
    old_path: str
    new_path: str
    files_moved: bool


@dataclass
class UpdateResult:
    canonical_id: str
    source_url: str
    fetch_children: bool
    sync_attachments: bool
    child_path: str | None = None


class SourceAlreadyExistsError(Exception):
    """Raised when a source is already registered."""

    def __init__(self, canonical_id: str, source_url: str, target_path: str):
        self.canonical_id = canonical_id
        self.source_url = source_url
        self.target_path = target_path
        super().__init__(f"Source already registered: {canonical_id}")


class SourceNotFoundError(Exception):
    """Raised when a source lookup fails."""

    def __init__(self, source: str):
        self.source = source
        super().__init__(f"Source not found: {source}")


class InvalidChildDiscoveryRequestError(ValueError):
    """Raised when child-discovery request fields do not form a valid one-shot request."""

    def __init__(self, child_path: str | None):
        self.child_path = child_path
        super().__init__(
            "child_path requires an active child-discovery request; pass fetch_children=True "
            "or update an already-pending request"
        )


class UnsupportedSourceUrlError(ValueError):
    """Raised when a URL does not map to any supported source adapter."""

    def __init__(self, source: str):
        self.source = source
        super().__init__(f"Unsupported source URL: {source}")


def _resolve_source(state, source: str) -> str | None:
    """Find a source by canonical ID or URL."""
    if source in state.sources:
        return source
    for cid, ss in state.sources.items():
        if ss.source_url == source:
            return cid
    return None


def check_source_exists(root: Path, url: str) -> SourceAlreadyExistsError | None:
    """Check if a source URL is already registered.

    Returns a SourceAlreadyExistsError if the source exists, None otherwise.
    Does not raise — caller decides how to handle the result.
    """
    try:
        stype = detect_source_type(url)
    except UnsupportedSourceError as exc:
        raise UnsupportedSourceUrlError(url) from exc
    cid = canonical_id(stype, url)
    state = load_state(root)
    if cid in state.sources:
        existing = state.sources[cid]
        return SourceAlreadyExistsError(cid, existing.source_url, existing.target_path)
    return None


def add_source(
    root: Path | None = None,
    *,
    url: str,
    target_path: str,
    fetch_children: bool = False,
    sync_attachments: bool = False,
    child_path: str | None = None,
) -> AddResult:
    """Register a source URL for syncing.

    Raises:
        UnsupportedSourceError: If the URL type is not recognised.
        SourceAlreadyExistsError: If the source is already registered.
    """
    root = _require_root(root)
    repository = BrainRepository(root)

    existing = check_source_exists(root, url)
    if existing is not None:
        raise existing
    if child_path is not None and not fetch_children:
        raise InvalidChildDiscoveryRequestError(child_path)

    try:
        stype = detect_source_type(url)
    except UnsupportedSourceError as exc:
        raise UnsupportedSourceUrlError(url) from exc
    cid = canonical_id(stype, url)
    state = load_state(root)

    # Phase 1: write manifest first (crash recovery favours disk truth)
    repository.save_source_manifest(
        SourceManifest(
            version=MANIFEST_VERSION,
            canonical_id=cid,
            source_url=url,
            source_type=stype.value,
            materialized_path="",  # unknown until first sync writes the file
            sync_attachments=sync_attachments,
            target_path=target_path,
        ),
    )

    if fetch_children:
        save_child_discovery_request(
            root,
            cid,
            fetch_children=fetch_children,
            child_path=child_path,
        )

    state.sources[cid] = SourceState(
        canonical_id=cid,
        source_url=url,
        source_type=stype.value,
        target_path=target_path,
        sync_attachments=sync_attachments,
    )
    save_state(root, state)
    repository.ensure_knowledge_dir(target_path)
    invalidate_area_index(root, knowledge_paths=[target_path], reason="source_registered")
    record_operational_event(
        event_type="source.registered",
        canonical_id=cid,
        knowledge_path=target_path,
        outcome="registered",
        details={"source_url": url, "sync_attachments": sync_attachments, "fetch_children": fetch_children},
    )

    return AddResult(
        canonical_id=cid,
        source_url=url,
        target_path=target_path,
        fetch_children=fetch_children,
        sync_attachments=sync_attachments,
        child_path=child_path,
    )


def _resolve_source_or_manifest(state: SyncState, root: Path, source: str) -> tuple[str, str, str]:
    """Resolve source by state first, then manifest fallback (for missing-status sources).

    Returns (canonical_id, source_url, target_path).
    Raises SourceNotFoundError if not found anywhere.
    """
    cid = _resolve_source(state, source)
    if cid is not None:
        ss = state.sources[cid]
        return cid, ss.source_url, ss.target_path

    # Fallback: check manifests directly (covers missing-status sources excluded from state)
    manifest = read_source_manifest(root, source)
    if manifest is not None:
        return manifest.canonical_id, manifest.source_url, manifest.target_path

    # Try URL match across all manifests
    all_manifests = read_all_source_manifests(root)
    for m in all_manifests.values():
        if m.source_url == source:
            return m.canonical_id, m.source_url, m.target_path

    raise SourceNotFoundError(source)


def remove_source(
    root: Path | None = None,
    *,
    source: str,
    delete_files: bool = False,
) -> RemoveResult:
    """Unregister a sync source.

    Raises:
        SourceNotFoundError: If the source is not found.
    """
    root = _require_root(root)
    repository = BrainRepository(root)
    state = load_state(root)

    cid, source_url, target_path = _resolve_source_or_manifest(state, root, source)

    # --- Scoped file deletion (only files owned by this source) ---
    files_deleted = False
    if delete_files:
        files_deleted = repository.remove_source_owned_files(target_path, cid)

    state.sources.pop(cid, None)
    save_state(root, state)

    db_delete_source(root, cid)
    clear_child_discovery_request(root, cid)

    # Phase 1: delete manifest (bypasses two-stage — explicit remove is immediate)
    repository.delete_source_registration(cid)
    invalidate_area_index(root, knowledge_paths=[target_path], reason="source_removed")
    record_operational_event(
        event_type="source.removed",
        canonical_id=cid,
        knowledge_path=target_path,
        outcome="removed",
        details={"delete_files": delete_files, "files_deleted": files_deleted},
    )

    return RemoveResult(
        canonical_id=cid,
        source_url=source_url,
        target_path=target_path,
        files_deleted=files_deleted,
    )


def list_sources(
    root: Path | None = None,
    *,
    filter_path: str | None = None,
) -> list[SourceInfo]:
    """List registered sync sources."""
    root = _require_root(root)
    state = load_state(root)
    child_requests = load_all_child_discovery_requests(root)

    results: list[SourceInfo] = []
    for cid, ss in sorted(state.sources.items()):
        target = getattr(ss, "target_path", "")
        if filter_path and not target.startswith(filter_path):
            continue
        request = child_requests.get(cid)
        results.append(
            SourceInfo(
                canonical_id=cid,
                source_url=ss.source_url,
                target_path=target,
                last_checked_utc=ss.last_checked_utc,
                last_changed_utc=ss.last_changed_utc,
                current_interval_secs=ss.current_interval_secs,
                fetch_children=request.fetch_children if request is not None else False,
                sync_attachments=getattr(ss, "sync_attachments", False),
            )
        )

    return results


def move_source(
    root: Path | None = None,
    *,
    source: str,
    to_path: str,
) -> MoveResult:
    """Move a sync source to a new knowledge path.

    Raises:
        SourceNotFoundError: If the source is not found.
    """
    root = _require_root(root)
    repository = BrainRepository(root)
    state = load_state(root)

    cid, _url, old_path = _resolve_source_or_manifest(state, root, source)

    if cid in state.sources:
        state.sources[cid].target_path = to_path
        save_state(root, state)

    files_moved = False
    if old_path != to_path:
        files_moved = repository.move_knowledge_tree(old_path, to_path)

    # Move .brain-sync/attachments/{source_dir_id}/ if it exists (already moved
    # with parent dir above, but handle case where old_dir == new_dir or
    # partial moves)
    if not files_moved:
        repository.move_source_attachment_dir(old_path, to_path, cid)

    # Phase 1: update manifest materialized_path and target_path
    manifest = read_source_manifest(root, cid)
    if manifest is not None:
        found = repository.resolve_source_file(manifest).path
        if found is not None:
            repository.sync_manifest_to_found_path(cid, found)
        else:
            repository.set_source_target_path(cid, to_path, clear_materialized_path=True)
    invalidate_area_index(root, knowledge_paths=[old_path, to_path], reason="source_moved")
    record_operational_event(
        event_type="source.moved",
        canonical_id=cid,
        knowledge_path=to_path,
        outcome="moved",
        details={"old_path": old_path, "new_path": to_path, "files_moved": files_moved},
    )

    return MoveResult(
        canonical_id=cid,
        old_path=old_path,
        new_path=to_path,
        files_moved=files_moved,
    )


def update_source(
    root: Path | None = None,
    *,
    source: str,
    fetch_children: bool | None = None,
    sync_attachments: bool | None = None,
    child_path: str | None = ...,  # type: ignore[assignment]  # sentinel
) -> UpdateResult:
    """Update config flags for an existing sync source.

    Only the flags that are explicitly provided (not None / not sentinel) are changed.

    Raises:
        SourceNotFoundError: If the source is not found.
    """
    root = _require_root(root)
    state = load_state(root)

    cid = _resolve_source(state, source)
    if cid is not None:
        ss = state.sources[cid]
    else:
        # Fallback: manifest lookup for missing-status sources excluded from state
        manifest = read_source_manifest(root, source)
        if manifest is None:
            all_manifests = read_all_source_manifests(root)
            manifest = next((m for m in all_manifests.values() if m.source_url == source), None)
        if manifest is None:
            raise SourceNotFoundError(source)
        cid = manifest.canonical_id
        ss = SourceState(
            canonical_id=cid,
            source_url=manifest.source_url,
            source_type=manifest.source_type,
            target_path=manifest.target_path,
            sync_attachments=manifest.sync_attachments,
        )

    existing_request = load_child_discovery_request(root, cid) or ChildDiscoveryRequest(canonical_id=cid)

    # Apply provided flags to in-memory state
    if sync_attachments is not None:
        ss.sync_attachments = sync_attachments
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

    repository = BrainRepository(root)
    repository.update_source_sync_settings(
        cid,
        sync_attachments=sync_attachments,
    )
    save_child_discovery_request(
        root,
        cid,
        fetch_children=next_fetch_children,
        child_path=next_child_path,
    )
    record_operational_event(
        event_type="source.updated",
        canonical_id=cid,
        knowledge_path=ss.target_path,
        outcome="updated",
        details={
            "fetch_children": next_fetch_children,
            "sync_attachments": ss.sync_attachments,
            "child_path": next_child_path,
        },
    )

    return UpdateResult(
        canonical_id=cid,
        source_url=ss.source_url,
        fetch_children=next_fetch_children,
        sync_attachments=ss.sync_attachments,
        child_path=next_child_path,
    )


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


def _find_file_by_identity_header(knowledge_root: Path, canonical_id_str: str) -> Path | None:
    """Tier-2: scan .md files across all of knowledge/ for matching identity header."""
    from brain_sync.sync.pipeline import extract_source_id

    if not path_is_dir(knowledge_root):
        return None
    for p in rglob_paths(knowledge_root, "*.md"):
        found_cid = extract_source_id(p)
        if found_cid == canonical_id_str:
            return p
    return None


def reconcile_sources(root: Path | None = None) -> ReconcileResult:
    """Reconcile source registrations against filesystem state.

    Iterates manifests (not DB sources). Uses 3-tier file resolution:
    1. materialized_path — direct file check
    2. Identity header scan — extract_source_id() on nearby .md files
    3. Prefix glob — rediscover_local_path() (existing)

    Implements two-stage missing protocol and orphan DB row pruning.
    """
    root = _require_root(root)

    knowledge_root = root / "knowledge"

    updated: list[ReconcileEntry] = []
    not_found: list[str] = []
    unchanged_count = 0
    marked_missing: list[str] = []
    deleted: list[str] = []
    reappeared: list[str] = []

    # Read ALL manifests (including missing-status) for reconciliation
    all_manifests = read_all_source_manifests(root)
    repository = BrainRepository(root)
    utc_now = datetime.now(UTC).isoformat()

    for cid, m in all_manifests.items():
        resolution = repository.resolve_source_file(m)
        found = resolution.path

        # Unmaterialized active source with no file found → nothing to reconcile
        if resolution.resolution == "unmaterialized":
            unchanged_count += 1
            continue

        if m.status == "missing":
            if found is not None:
                # Reappearing: file found again during grace period
                repository.clear_source_missing(cid)
                repository.sync_manifest_to_found_path(cid, found)
                reappeared.append(cid)
                record_operational_event(
                    event_type="reconcile.path_updated",
                    canonical_id=cid,
                    knowledge_path=normalize_path(found.parent.relative_to(knowledge_root)),
                    outcome="reappeared",
                )
            else:
                # Second-stage: still missing → delete manifest + DB row
                repository.delete_source_registration(cid)
                db_delete_source(root, cid)
                deleted.append(cid)
                invalidate_area_index(root, knowledge_paths=[m.target_path], reason="source_deleted")
                record_operational_event(
                    event_type="reconcile.deleted",
                    canonical_id=cid,
                    knowledge_path=m.target_path,
                    outcome="deleted",
                )
            continue

        # Active manifest with materialized_path
        if found is not None:
            # Update materialized_path if file moved
            new_target = normalize_path(found.parent.relative_to(knowledge_root))
            old_target = m.target_path or (
                normalize_path(Path(m.materialized_path).parent) if m.materialized_path else ""
            )

            repository.sync_manifest_to_found_path(cid, found)

            if new_target != old_target:
                updated.append(ReconcileEntry(canonical_id=cid, old_path=old_target, new_path=new_target))
                invalidate_area_index(root, knowledge_paths=[old_target, new_target], reason="reconcile_path_updated")
                record_operational_event(
                    event_type="reconcile.path_updated",
                    canonical_id=cid,
                    knowledge_path=new_target,
                    outcome="updated",
                    details={"old_path": old_target, "new_path": new_target},
                )
            else:
                unchanged_count += 1
        else:
            # First-stage missing: file not found at any tier
            repository.mark_source_missing(cid, utc_now)
            marked_missing.append(cid)
            not_found.append(cid)
            record_operational_event(
                event_type="reconcile.missing_marked",
                canonical_id=cid,
                knowledge_path=m.target_path,
                outcome="missing",
            )

    # Orphan DB row pruning: delete DB rows with no corresponding manifest
    manifest_dir = root / ".brain-sync" / "sources"
    orphan_count = 0
    if path_is_dir(manifest_dir):
        db_sources = load_sync_progress(root)
        for db_cid in db_sources:
            if db_cid not in all_manifests:
                db_delete_source(root, db_cid)
                orphan_count += 1
                log.info("Pruned orphan DB row: %s", db_cid)

    return ReconcileResult(
        updated=updated,
        not_found=not_found,
        unchanged=unchanged_count,
        marked_missing=marked_missing,
        deleted=deleted,
        reappeared=reappeared,
        orphan_rows_pruned=orphan_count,
    )


@dataclass
class MigrateResult:
    sources_migrated: int
    files_migrated: int
    dirs_cleaned: int


def migrate_sources(root: Path | None = None) -> MigrateResult:
    """Migrate all sources to the current .brain-sync/attachments/{source_dir_id}/ layout.

    Handles both legacy _sync-context/ dirs and bare-ID _attachments/{bare_id}/ dirs.
    Also cleans up stale _sync-context/ directories under knowledge/.
    """
    from brain_sync.sync.attachments import LEGACY_CONTEXT_DIR, migrate_legacy_context

    root = _require_root(root)
    repository = BrainRepository(root)
    state = load_state(root)
    knowledge_root = root / "knowledge"

    sources_migrated = 0
    files_migrated = 0

    # Migrate each source's legacy _sync-context/ and bare-ID _attachments/ dirs
    for cid, ss in state.sources.items():
        target_dir = knowledge_root / ss.target_path if ss.target_path else knowledge_root
        source_dir_id = canonical_prefix(cid).rstrip("-")

        # Check if there's anything to migrate: legacy dir or bare-ID attachment dir
        legacy_dir = target_dir / LEGACY_CONTEXT_DIR
        bare_id = cid.split(":", 1)[1]
        bare_att_dir = target_dir / "_attachments" / bare_id
        needs_migration = path_is_dir(legacy_dir) or (path_is_dir(bare_att_dir) and bare_id != source_dir_id)
        if not needs_migration:
            continue

        count = migrate_legacy_context(target_dir, source_dir_id, cid, root)
        if count > 0:
            sources_migrated += 1
            files_migrated += count
        else:
            sources_migrated += 1  # still cleaned up the empty dir

    # Clean up any remaining _sync-context/ dirs under knowledge/
    dirs_cleaned = 0
    if path_is_dir(knowledge_root):
        for legacy in rglob_paths(knowledge_root, LEGACY_CONTEXT_DIR):
            if path_is_dir(legacy) and repository.remove_legacy_context_dir(legacy):
                dirs_cleaned += 1
                log.info("Removed stale %s: %s", LEGACY_CONTEXT_DIR, legacy)

    return MigrateResult(
        sources_migrated=sources_migrated,
        files_migrated=files_migrated,
        dirs_cleaned=dirs_cleaned,
    )

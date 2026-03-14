"""Source management commands — importable Python API."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from brain_sync.commands.context import _require_root
from brain_sync.fileops import canonical_prefix, rediscover_local_path
from brain_sync.fs_utils import normalize_path
from brain_sync.manifest import (
    MANIFEST_DIR,
    MANIFEST_VERSION,
    SourceManifest,
    SyncHint,
    clear_manifest_missing,
    delete_source_manifest,
    ensure_manifest_dir,
    mark_manifest_missing,
    read_all_source_manifests,
    read_source_manifest,
    update_manifest_materialized_path,
    write_source_manifest,
)
from brain_sync.sources import canonical_id, detect_source_type
from brain_sync.state import (
    SourceState,
    SyncState,
    count_relationships_for_doc,
    load_relationships_for_primary,
    load_state,
    remove_document_if_orphaned,
    remove_relationship,
    save_state,
    update_source_flags,
    update_source_target_path,
)
from brain_sync.state import (
    delete_source as db_delete_source,
)

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
    stype = detect_source_type(url)
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

    existing = check_source_exists(root, url)
    if existing is not None:
        raise existing

    stype = detect_source_type(url)
    cid = canonical_id(stype, url)
    state = load_state(root)

    # Phase 1: write manifest first (crash recovery favours disk truth)
    write_source_manifest(
        root,
        SourceManifest(
            manifest_version=MANIFEST_VERSION,
            canonical_id=cid,
            source_url=url,
            source_type=stype.value,
            materialized_path="",  # unknown until first sync writes the file
            fetch_children=fetch_children,
            sync_attachments=sync_attachments,
            target_path=target_path,
            child_path=child_path,
        ),
    )

    state.sources[cid] = SourceState(
        canonical_id=cid,
        source_url=url,
        source_type=stype.value,
        target_path=target_path,
        fetch_children=fetch_children,
        sync_attachments=sync_attachments,
        child_path=child_path,
    )
    save_state(root, state)

    knowledge_dir = root / "knowledge" / target_path
    knowledge_dir.mkdir(parents=True, exist_ok=True)

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
    state = load_state(root)

    cid, source_url, target_path = _resolve_source_or_manifest(state, root, source)

    # --- Scoped file deletion (only files owned by this source) ---
    files_deleted = False
    if delete_files:
        target_dir = root / "knowledge" / target_path
        if target_dir.exists():
            # Delete main document file(s) matching the canonical prefix
            prefix = canonical_prefix(cid)
            for f in target_dir.iterdir():
                if f.is_file() and f.name.startswith(prefix):
                    f.unlink()
                    files_deleted = True

            # Clean up _attachments/{source_dir_id}/ for this source
            source_dir_id = canonical_prefix(cid).rstrip("-")
            att_dir = target_dir / "_attachments" / source_dir_id
            if att_dir.is_dir():
                shutil.rmtree(att_dir)
                files_deleted = True
            # Legacy _sync-context cleanup
            legacy_ctx = target_dir / "_sync-context"
            if legacy_ctx.is_dir():
                shutil.rmtree(legacy_ctx)
                files_deleted = True

            # Clean up empty directories bottom-up (but only remove target_dir
            # and its subdirs if they're now empty — never delete other content)
            for dirpath in sorted(target_dir.rglob("*"), reverse=True):
                if dirpath.is_dir() and not any(dirpath.iterdir()):
                    dirpath.rmdir()
            if target_dir.exists() and not any(target_dir.iterdir()):
                target_dir.rmdir()

    # --- DB cleanup: relationships and orphaned documents ---
    rels = load_relationships_for_primary(root, cid)
    for rel in rels:
        remove_relationship(root, cid, rel.canonical_id)
        if count_relationships_for_doc(root, rel.canonical_id) == 0:
            remove_document_if_orphaned(root, rel.canonical_id)
    remove_document_if_orphaned(root, cid)

    state.sources.pop(cid, None)
    save_state(root, state)

    db_delete_source(root, cid)

    # Phase 1: delete manifest (bypasses two-stage — explicit remove is immediate)
    delete_source_manifest(root, cid)

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

    results: list[SourceInfo] = []
    for cid, ss in sorted(state.sources.items()):
        target = getattr(ss, "target_path", "")
        if filter_path and not target.startswith(filter_path):
            continue
        results.append(
            SourceInfo(
                canonical_id=cid,
                source_url=ss.source_url,
                target_path=target,
                last_checked_utc=ss.last_checked_utc,
                last_changed_utc=ss.last_changed_utc,
                current_interval_secs=ss.current_interval_secs,
                fetch_children=getattr(ss, "fetch_children", False),
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
    state = load_state(root)

    cid = _resolve_source(state, source)
    if cid is None:
        raise SourceNotFoundError(source)

    ss = state.sources[cid]
    old_path = getattr(ss, "target_path", "")
    ss.target_path = to_path
    save_state(root, state)

    # save_state UPDATE doesn't touch target_path (by design), so update directly
    update_source_target_path(root, cid, to_path)

    files_moved = False
    old_dir = root / "knowledge" / old_path
    new_dir = root / "knowledge" / to_path
    if old_dir.exists() and old_dir != new_dir:
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(old_dir), str(new_dir))
        files_moved = True

    # Move _attachments/{page_id}/ if it exists (already moved with parent dir above,
    # but handle case where old_dir == new_dir or partial moves)
    if not files_moved:
        source_dir_id = canonical_prefix(cid).rstrip("-")
        old_att = old_dir / "_attachments" / source_dir_id
        new_att = new_dir / "_attachments" / source_dir_id
        if old_att.is_dir() and not new_att.exists():
            new_att.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_att), str(new_att))

    # Phase 1: update manifest materialized_path and target_path
    knowledge_root = root / "knowledge"
    found = rediscover_local_path(knowledge_root, cid)
    manifest = read_source_manifest(root, cid)
    if manifest is not None:
        manifest.target_path = to_path
        if found is not None:
            manifest.materialized_path = normalize_path(found.relative_to(knowledge_root))
        else:
            manifest.materialized_path = ""
        write_source_manifest(root, manifest)

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
            fetch_children=manifest.fetch_children,
            sync_attachments=manifest.sync_attachments,
            child_path=manifest.child_path,
        )

    # Apply provided flags to in-memory state
    if fetch_children is not None:
        ss.fetch_children = fetch_children
    if sync_attachments is not None:
        ss.sync_attachments = sync_attachments
    if child_path is not ...:
        ss.child_path = child_path  # type: ignore[assignment]

    # Write directly to DB — save_state skips config fields on UPDATE
    update_source_flags(
        root,
        cid,
        fetch_children=fetch_children,
        sync_attachments=sync_attachments,
        child_path=child_path,
    )

    # Update manifest flags
    manifest_obj = read_source_manifest(root, cid)
    if manifest_obj is not None:
        if fetch_children is not None:
            manifest_obj.fetch_children = fetch_children
        if sync_attachments is not None:
            manifest_obj.sync_attachments = sync_attachments
        if child_path is not ...:
            manifest_obj.child_path = child_path  # type: ignore[assignment]
        write_source_manifest(root, manifest_obj)

    return UpdateResult(
        canonical_id=cid,
        source_url=ss.source_url,
        fetch_children=ss.fetch_children,
        sync_attachments=ss.sync_attachments,
        child_path=ss.child_path,
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


def _bootstrap_manifests_from_db(root: Path, state: SyncState) -> int:
    """One-time migration: export existing DB sources to manifests.

    Only runs when .brain-sync/sources/ is empty but DB has sources.
    Uses the provided ``state`` directly — callers (including ``_migrate()``)
    must pre-populate it from whatever connection they already hold.
    Returns the number of manifests written.
    """
    manifest_dir = root / MANIFEST_DIR
    if not manifest_dir.is_dir():
        ensure_manifest_dir(root)

    existing = read_all_source_manifests(root)
    if existing:
        return 0  # manifests already exist — not a migration scenario

    if not state.sources:
        return 0

    count = 0
    for cid, ss in state.sources.items():
        # v21+: sync_cache has no intent fields — skip rows without source_url
        if not ss.source_url:
            continue
        # Discover the actual file path for materialized_path
        knowledge_root = root / "knowledge"
        materialized = ""
        if ss.target_path:
            target_dir = knowledge_root / ss.target_path
            if target_dir.is_dir():
                prefix = canonical_prefix(cid)
                for p in target_dir.iterdir():
                    if p.is_file() and p.name.startswith(prefix):
                        materialized = normalize_path(p.relative_to(knowledge_root))
                        break

        hint = None
        if ss.content_hash:
            hint = SyncHint(
                content_hash=ss.content_hash,
                last_synced_utc=ss.last_checked_utc,
            )

        write_source_manifest(
            root,
            SourceManifest(
                manifest_version=MANIFEST_VERSION,
                canonical_id=cid,
                source_url=ss.source_url,
                source_type=ss.source_type,
                materialized_path=materialized,
                fetch_children=ss.fetch_children,
                sync_attachments=ss.sync_attachments,
                target_path=ss.target_path,
                child_path=ss.child_path,
                sync_hint=hint,
            ),
        )
        count += 1

    log.info("Bootstrap migration: exported %d DB sources to manifests", count)
    return count


def _find_file_by_identity_header(knowledge_root: Path, canonical_id_str: str) -> Path | None:
    """Tier-2: scan .md files across all of knowledge/ for matching identity header."""
    from brain_sync.pipeline import extract_source_id

    if not knowledge_root.is_dir():
        return None
    for p in knowledge_root.rglob("*.md"):
        if p.is_file():
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
    state = load_state(root)

    # Bootstrap manifests from DB if none exist yet (one-time migration)
    _bootstrap_manifests_from_db(root, state)

    knowledge_root = root / "knowledge"

    updated: list[ReconcileEntry] = []
    not_found: list[str] = []
    unchanged_count = 0
    marked_missing: list[str] = []
    deleted: list[str] = []
    reappeared: list[str] = []

    # Read ALL manifests (including missing-status) for reconciliation
    all_manifests = read_all_source_manifests(root)
    utc_now = datetime.now(UTC).isoformat()

    for cid, m in all_manifests.items():
        # Three-tier file resolution
        found: Path | None = None

        if m.materialized_path:
            # Tier 1: direct file check at materialized_path
            direct = knowledge_root / m.materialized_path
            if direct.is_file():
                found = direct

            # Tier 2: identity header scan across all of knowledge/
            if found is None:
                found = _find_file_by_identity_header(knowledge_root, cid)

        # Tier 3: prefix glob (searches all of knowledge/) — also used for unmaterialized sources
        if found is None:
            found = rediscover_local_path(knowledge_root, cid)

        # Unmaterialized active source with no file found → nothing to reconcile
        if m.status == "active" and not m.materialized_path and found is None:
            unchanged_count += 1
            continue

        if m.status == "missing":
            if found is not None:
                # Reappearing: file found again during grace period
                clear_manifest_missing(root, cid)
                materialized = normalize_path(found.relative_to(knowledge_root))
                update_manifest_materialized_path(root, cid, materialized)
                reappeared.append(cid)
            else:
                # Second-stage: still missing → delete manifest + DB row
                delete_source_manifest(root, cid)
                db_delete_source(root, cid)
                deleted.append(cid)
            continue

        # Active manifest with materialized_path
        if found is not None:
            # Update materialized_path if file moved
            materialized = normalize_path(found.relative_to(knowledge_root))
            new_target = normalize_path(found.parent.relative_to(knowledge_root))
            old_target = m.target_path or (
                normalize_path(Path(m.materialized_path).parent) if m.materialized_path else ""
            )

            if materialized != m.materialized_path:
                update_manifest_materialized_path(root, cid, materialized)
                # Update target_path in manifest
                manifest_obj = read_source_manifest(root, cid)
                if manifest_obj is not None:
                    manifest_obj.target_path = new_target
                    write_source_manifest(root, manifest_obj)

            if new_target != old_target:
                update_source_target_path(root, cid, new_target)
                updated.append(ReconcileEntry(canonical_id=cid, old_path=old_target, new_path=new_target))
            else:
                unchanged_count += 1
        else:
            # First-stage missing: file not found at any tier
            mark_manifest_missing(root, cid, utc_now)
            marked_missing.append(cid)
            not_found.append(cid)

    # Orphan DB row pruning: delete DB rows with no corresponding manifest
    manifest_dir = root / ".brain-sync" / "sources"
    orphan_count = 0
    if manifest_dir.is_dir():
        from brain_sync.state import _load_db_sync_progress

        db_sources = _load_db_sync_progress(root)
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
    """Migrate all sources to the current _attachments/{source_dir_id}/ layout.

    Handles both legacy _sync-context/ dirs and bare-ID _attachments/{bare_id}/ dirs.
    Also cleans up stale _sync-context/ directories in knowledge/ and insights/.
    """
    import shutil

    from brain_sync.attachments import LEGACY_CONTEXT_DIR, migrate_legacy_context

    root = _require_root(root)
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
        needs_migration = legacy_dir.is_dir() or (bare_att_dir.is_dir() and bare_id != source_dir_id)
        if not needs_migration:
            continue

        count = migrate_legacy_context(target_dir, source_dir_id, cid, root)
        if count > 0:
            sources_migrated += 1
            files_migrated += count
        else:
            sources_migrated += 1  # still cleaned up the empty dir

    # Clean up any remaining _sync-context/ dirs (orphaned or in insights/)
    dirs_cleaned = 0
    for search_root in [knowledge_root, root / "insights"]:
        if not search_root.is_dir():
            continue
        for legacy in list(search_root.rglob(LEGACY_CONTEXT_DIR)):
            if legacy.is_dir():
                shutil.rmtree(legacy)
                dirs_cleaned += 1
                log.info("Removed stale %s: %s", LEGACY_CONTEXT_DIR, legacy)

    return MigrateResult(
        sources_migrated=sources_migrated,
        files_migrated=files_migrated,
        dirs_cleaned=dirs_cleaned,
    )

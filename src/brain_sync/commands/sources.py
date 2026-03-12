"""Source management commands — importable Python API."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from brain_sync.commands.context import _require_root
from brain_sync.fileops import canonical_prefix, rediscover_local_path
from brain_sync.fs_utils import normalize_path
from brain_sync.sources import canonical_id, detect_source_type
from brain_sync.state import (
    SourceState,
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

    cid = _resolve_source(state, source)
    if cid is None:
        raise SourceNotFoundError(source)

    ss = state.sources[cid]
    target_path = ss.target_path
    source_url = ss.source_url

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

            # Delete relationship files (_sync-context or _attachments)
            rels = load_relationships_for_primary(root, cid)
            for rel in rels:
                rel_file = target_dir / rel.local_path
                if rel_file.is_file():
                    rel_file.unlink(missing_ok=True)
                    files_deleted = True

            # Also clean up _attachments/{source_dir_id}/ for this source
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

    del state.sources[cid]
    save_state(root, state)

    db_delete_source(root, cid)

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
    if cid is None:
        raise SourceNotFoundError(source)

    ss = state.sources[cid]

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


def reconcile_sources(root: Path | None = None) -> ReconcileResult:
    """Update target_path for sources whose files have been moved on disk.

    Scans knowledge/ for each source's canonical-prefix file.  If the file
    is no longer at the expected target_path but is found elsewhere, the DB
    is updated to match.
    """
    root = _require_root(root)
    state = load_state(root)
    knowledge_root = root / "knowledge"

    updated: list[ReconcileEntry] = []
    not_found: list[str] = []
    unchanged_count = 0

    for cid, ss in state.sources.items():
        prefix = canonical_prefix(cid)
        expected_dir = knowledge_root / ss.target_path if ss.target_path else knowledge_root

        # Check if a file with this prefix exists at the expected location
        found_at_expected = False
        if expected_dir.is_dir():
            for p in expected_dir.iterdir():
                if p.is_file() and p.name.startswith(prefix):
                    found_at_expected = True
                    break
            # Also check bare prefix (titleless docs)
            if not found_at_expected:
                bare = prefix.rstrip("-")
                if bare != prefix:
                    for p in expected_dir.iterdir():
                        if p.is_file() and p.name.startswith(bare):
                            found_at_expected = True
                            break

        if found_at_expected:
            unchanged_count += 1
            continue

        # File not at expected location — search all of knowledge/
        found = rediscover_local_path(knowledge_root, cid)
        if found is None:
            not_found.append(cid)
            continue

        # Compute new target_path relative to knowledge/
        new_target = normalize_path(found.parent.relative_to(knowledge_root))
        old_target = ss.target_path

        if new_target != old_target:
            update_source_target_path(root, cid, new_target)
            ss.target_path = new_target
            updated.append(
                ReconcileEntry(
                    canonical_id=cid,
                    old_path=old_target,
                    new_path=new_target,
                )
            )

    return ReconcileResult(updated=updated, not_found=not_found, unchanged=unchanged_count)


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

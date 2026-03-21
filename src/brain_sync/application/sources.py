"""Application-facing source lifecycle facades."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from brain_sync.application.roots import _require_root
from brain_sync.brain.fileops import canonical_prefix, path_is_dir, rglob_paths
from brain_sync.runtime.repository import record_operational_event
from brain_sync.sync.finalization import FinalizationResult
from brain_sync.sync.finalization import finalize_missing as sync_finalize_missing
from brain_sync.sync.lifecycle import (
    AddResult,
    InvalidChildDiscoveryRequestError,
    MoveResult,
    ReconcileEntry,
    ReconcileResult,
    RemoveResult,
    SourceAlreadyExistsError,
    SourceNotFoundError,
    UnsupportedSourceUrlError,
    UpdateResult,
    observe_missing_source,
)
from brain_sync.sync.lifecycle import (
    add_source as sync_add_source,
)
from brain_sync.sync.lifecycle import (
    check_source_exists as sync_check_source_exists,
)
from brain_sync.sync.lifecycle import (
    list_sources as sync_list_sources,
)
from brain_sync.sync.lifecycle import (
    move_source as sync_move_source,
)
from brain_sync.sync.lifecycle import (
    reconcile_sources as sync_reconcile_sources,
)
from brain_sync.sync.lifecycle import (
    remove_source as sync_remove_source,
)
from brain_sync.sync.lifecycle import (
    update_source as sync_update_source,
)
from brain_sync.sync.source_state import SourceAdminView as SourceInfo

__all__ = [
    "AddResult",
    "FinalizationResult",
    "InvalidCanonicalIdError",
    "InvalidChildDiscoveryRequestError",
    "MigrateResult",
    "MoveResult",
    "ReconcileEntry",
    "ReconcileResult",
    "RemoveResult",
    "SourceAlreadyExistsError",
    "SourceInfo",
    "SourceNotFoundError",
    "UnsupportedSourceUrlError",
    "UpdateResult",
    "add_source",
    "check_source_exists",
    "finalize_missing",
    "list_sources",
    "mark_source_missing",
    "migrate_sources",
    "move_source",
    "reconcile_sources",
    "remove_source",
    "update_source",
]

_EXACT_SOURCE_CANONICAL_ID_PATTERN = re.compile(r"^(?:confluence:\d+|gdoc:[A-Za-z0-9_-]+|test:[A-Za-z0-9_-]+)$")


class InvalidCanonicalIdError(ValueError):
    def __init__(self, canonical_id: str):
        self.canonical_id = canonical_id
        super().__init__(f"Invalid canonical ID: {canonical_id!r}")


def require_exact_source_canonical_id(canonical_id: str) -> str:
    if not canonical_id or canonical_id.strip() != canonical_id:
        raise InvalidCanonicalIdError(canonical_id)
    has_invalid_separator = (
        "://" in canonical_id
        or "/" in canonical_id
        or "\\" in canonical_id
        or "," in canonical_id
        or " " in canonical_id
    )
    if has_invalid_separator:
        raise InvalidCanonicalIdError(canonical_id)
    if re.match(r"^[A-Za-z]:", canonical_id):
        raise InvalidCanonicalIdError(canonical_id)
    if _EXACT_SOURCE_CANONICAL_ID_PATTERN.fullmatch(canonical_id) is None:
        raise InvalidCanonicalIdError(canonical_id)
    return canonical_id


def check_source_exists(root: Path, url: str) -> SourceAlreadyExistsError | None:
    return sync_check_source_exists(root, url)


def add_source(
    root: Path | None = None,
    *,
    url: str,
    target_path: str,
    fetch_children: bool = False,
    sync_attachments: bool = False,
    child_path: str | None = None,
) -> AddResult:
    return sync_add_source(
        _require_root(root),
        url=url,
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
    return sync_remove_source(_require_root(root), source=source, delete_files=delete_files)


def list_sources(
    root: Path | None = None,
    *,
    filter_path: str | None = None,
) -> list[SourceInfo]:
    return sync_list_sources(_require_root(root), filter_path=filter_path)


def move_source(
    root: Path | None = None,
    *,
    source: str,
    to_path: str,
) -> MoveResult:
    return sync_move_source(_require_root(root), source=source, to_path=to_path)


def update_source(
    root: Path | None = None,
    *,
    source: str,
    fetch_children: bool | None = None,
    sync_attachments: bool | None = None,
    child_path: str | None = ...,  # type: ignore[assignment]
) -> UpdateResult:
    return sync_update_source(
        _require_root(root),
        source=source,
        fetch_children=fetch_children,
        sync_attachments=sync_attachments,
        child_path=child_path,
    )


def mark_source_missing(
    root: Path,
    *,
    canonical_id: str,
    missing_since_utc: str | None = None,
    outcome: str,
    lifecycle_session_id: str | None = None,
) -> bool:
    del missing_since_utc
    return (
        observe_missing_source(
            root,
            canonical_id=canonical_id,
            outcome=outcome,
            lifecycle_session_id=lifecycle_session_id,
        )
        is not None
    )


def reconcile_sources(
    root: Path | None = None,
    *,
    finalize_missing: bool = False,
    lifecycle_session_id: str | None = None,
) -> ReconcileResult:
    return sync_reconcile_sources(
        _require_root(root),
        finalize_missing=finalize_missing,
        lifecycle_session_id=lifecycle_session_id,
    )


def finalize_missing(
    root: Path | None = None,
    *,
    canonical_id: str,
    lifecycle_session_id: str | None = None,
) -> FinalizationResult:
    canonical_id = require_exact_source_canonical_id(canonical_id)
    return sync_finalize_missing(
        _require_root(root),
        canonical_id=canonical_id,
        lifecycle_session_id=lifecycle_session_id,
    )


@dataclass(frozen=True)
class MigrateResult:
    sources_migrated: int
    files_migrated: int
    dirs_cleaned: int


def migrate_sources(root: Path | None = None) -> MigrateResult:
    from brain_sync.sync.attachments import LEGACY_CONTEXT_DIR, migrate_legacy_context

    root = _require_root(root)
    from brain_sync.brain.repository import BrainRepository
    from brain_sync.sync.source_state import load_active_sync_state

    repository = BrainRepository(root)
    state = load_active_sync_state(root)
    knowledge_root = root / "knowledge"

    sources_migrated = 0
    files_migrated = 0
    for canonical_id, source_state in state.sources.items():
        target_dir = knowledge_root / source_state.target_path if source_state.target_path else knowledge_root
        source_dir_id = canonical_prefix(canonical_id).rstrip("-")
        legacy_dir = target_dir / LEGACY_CONTEXT_DIR
        bare_id = canonical_id.split(":", 1)[1]
        bare_att_dir = target_dir / "_attachments" / bare_id
        needs_migration = path_is_dir(legacy_dir) or (path_is_dir(bare_att_dir) and bare_id != source_dir_id)
        if not needs_migration:
            continue

        count = migrate_legacy_context(target_dir, source_dir_id, canonical_id, root)
        sources_migrated += 1
        files_migrated += count

    dirs_cleaned = 0
    if path_is_dir(knowledge_root):
        for legacy in rglob_paths(knowledge_root, LEGACY_CONTEXT_DIR):
            if path_is_dir(legacy) and repository.remove_legacy_context_dir(legacy):
                dirs_cleaned += 1

    if dirs_cleaned:
        record_operational_event(
            event_type="source.updated",
            outcome="migrated_legacy_context",
            details={"dirs_cleaned": dirs_cleaned, "sources_migrated": sources_migrated},
        )

    return MigrateResult(
        sources_migrated=sources_migrated,
        files_migrated=files_migrated,
        dirs_cleaned=dirs_cleaned,
    )

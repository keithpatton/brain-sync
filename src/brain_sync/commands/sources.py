"""Source management commands — importable Python API."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from brain_sync.commands.context import _require_root
from brain_sync.sources import canonical_id, detect_source_type
from brain_sync.state import (
    SourceState,
    load_state,
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
    include_links: bool
    include_children: bool
    include_attachments: bool


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
    include_links: bool
    include_children: bool
    include_attachments: bool


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
    include_links: bool
    include_children: bool
    include_attachments: bool


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
    include_links: bool = False,
    include_children: bool = False,
    include_attachments: bool = False,
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
        include_links=include_links,
        include_children=include_children,
        include_attachments=include_attachments,
    )
    save_state(root, state)

    knowledge_dir = root / "knowledge" / target_path
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    return AddResult(
        canonical_id=cid,
        source_url=url,
        target_path=target_path,
        include_links=include_links,
        include_children=include_children,
        include_attachments=include_attachments,
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

    files_deleted = False
    if delete_files:
        target_dir = root / "knowledge" / target_path
        if target_dir.exists():
            shutil.rmtree(str(target_dir))
            files_deleted = True

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
                include_links=getattr(ss, "include_links", False),
                include_children=getattr(ss, "include_children", False),
                include_attachments=getattr(ss, "include_attachments", False),
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
    include_links: bool | None = None,
    include_children: bool | None = None,
    include_attachments: bool | None = None,
) -> UpdateResult:
    """Update config flags for an existing sync source.

    Only the flags that are explicitly provided (not None) are changed.

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
    if include_links is not None:
        ss.include_links = include_links
    if include_children is not None:
        ss.include_children = include_children
    if include_attachments is not None:
        ss.include_attachments = include_attachments

    # Write directly to DB — save_state skips config fields on UPDATE
    update_source_flags(
        root,
        cid,
        include_links=include_links,
        include_children=include_children,
        include_attachments=include_attachments,
    )

    return UpdateResult(
        canonical_id=cid,
        source_url=ss.source_url,
        include_links=ss.include_links,
        include_children=ss.include_children,
        include_attachments=ss.include_attachments,
    )

"""Application-facing reconciliation workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.application.query_index import invalidate_area_index
from brain_sync.application.sources import ReconcileEntry, reconcile_sources
from brain_sync.runtime.repository import ensure_lifecycle_session
from brain_sync.sync.reconcile import TreeReconcileResult
from brain_sync.sync.reconcile import reconcile_knowledge_tree as reconcile_knowledge_tree_sync

__all__ = ["ReconcileReport", "TreeReconcileResult", "reconcile_brain", "reconcile_knowledge_tree"]


@dataclass(frozen=True)
class ReconcileReport:
    """Transport-neutral summary of reconcile work for one user-visible request."""

    updated: list[ReconcileEntry] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    unchanged: int = 0
    marked_missing: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    reappeared: list[str] = field(default_factory=list)
    orphan_rows_pruned: int = 0
    orphans_cleaned: list[str] = field(default_factory=list)
    content_changed: list[str] = field(default_factory=list)
    enqueued_paths: list[str] = field(default_factory=list)
    has_source_changes: bool = False
    has_tree_changes: bool = False
    has_changes: bool = False


def reconcile_knowledge_tree(root: Path) -> TreeReconcileResult:
    result = reconcile_knowledge_tree_sync(root)
    for path in result.content_changed:
        invalidate_area_index(root, knowledge_paths=[path], reason="reconcile_content_changed")
    for path in result.enqueued_paths:
        invalidate_area_index(root, knowledge_paths=[path], reason="reconcile_path_enqueued")
    return result


def reconcile_brain(
    root: Path,
    *,
    include_knowledge_tree: bool = False,
    lifecycle_session_id: str | None = None,
    lifecycle_session_owner_kind: str = "cli",
) -> ReconcileReport:
    """Run the shared reconcile workflow and return a flattened report.

    CLI and MCP both need the same source-reconcile result shaping. Some
    callers, such as the CLI command, also want the knowledge-tree pass in the
    same workflow, while narrower callers can skip it.
    """

    current_lifecycle_session_id = lifecycle_session_id or ensure_lifecycle_session(
        root,
        owner_kind=lifecycle_session_owner_kind,
    )
    source_result = reconcile_sources(
        root=root,
        lifecycle_session_id=current_lifecycle_session_id,
    )
    tree_result = reconcile_knowledge_tree(root) if include_knowledge_tree else TreeReconcileResult()

    has_source_changes = bool(
        source_result.updated
        or source_result.not_found
        or source_result.marked_missing
        or source_result.deleted
        or source_result.reappeared
        or source_result.orphan_rows_pruned
    )
    has_tree_changes = bool(tree_result.orphans_cleaned or tree_result.content_changed or tree_result.enqueued_paths)

    return ReconcileReport(
        updated=source_result.updated,
        not_found=source_result.not_found,
        unchanged=source_result.unchanged,
        marked_missing=source_result.marked_missing,
        deleted=source_result.deleted,
        reappeared=source_result.reappeared,
        orphan_rows_pruned=source_result.orphan_rows_pruned,
        orphans_cleaned=tree_result.orphans_cleaned,
        content_changed=tree_result.content_changed,
        enqueued_paths=tree_result.enqueued_paths,
        has_source_changes=has_source_changes,
        has_tree_changes=has_tree_changes,
        has_changes=has_source_changes or has_tree_changes,
    )

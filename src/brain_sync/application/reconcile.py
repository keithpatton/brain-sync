"""Application-owned reconciliation workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.application.insights import load_all_insight_states
from brain_sync.application.query_index import invalidate_area_index
from brain_sync.application.regen import classify_folder_change
from brain_sync.application.sources import ReconcileEntry, reconcile_sources
from brain_sync.runtime.repository import (
    clear_dirty_knowledge_paths,
    load_dirty_knowledge_paths,
    record_operational_event,
    save_path_observations,
)
from brain_sync.sync.reconcile import KnowledgeTreeScanResult, scan_knowledge_tree

__all__ = ["ReconcileReport", "TreeReconcileResult", "reconcile_brain", "reconcile_knowledge_tree"]


@dataclass(frozen=True)
class TreeReconcileResult:
    orphans_cleaned: list[str] = field(default_factory=list)
    content_changed: list[str] = field(default_factory=list)
    enqueued_paths: list[str] = field(default_factory=list)


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
    """Reconcile the knowledge tree using application-owned cross-plane state views."""
    tracked_paths = {state.knowledge_path for state in load_all_insight_states(root)}
    scan_result: KnowledgeTreeScanResult = scan_knowledge_tree(root, tracked_paths=tracked_paths)
    dirty_paths = load_dirty_knowledge_paths(root)
    candidate_paths = set(scan_result.candidate_paths) | dirty_paths

    content_changed: list[str] = []
    for path in sorted(candidate_paths):
        change, _, _ = classify_folder_change(root, path)
        if change.change_type != "none":
            content_changed.append(path)

    clear_dirty_knowledge_paths(root, candidate_paths)
    save_path_observations(root, scan_result.observed_mtimes, active_paths=scan_result.active_paths)

    for orphan in scan_result.orphans_cleaned:
        record_operational_event(
            event_type="reconcile.orphan_cleaned",
            knowledge_path=orphan,
            outcome="cleaned",
        )
    for path in content_changed:
        invalidate_area_index(root, knowledge_paths=[path], reason="reconcile_content_changed")
    for path in scan_result.enqueued_paths:
        invalidate_area_index(root, knowledge_paths=[path], reason="reconcile_path_enqueued")
        record_operational_event(
            event_type="reconcile.path_enqueued",
            knowledge_path=path,
            outcome="enqueued",
        )

    return TreeReconcileResult(
        orphans_cleaned=scan_result.orphans_cleaned,
        content_changed=content_changed,
        enqueued_paths=scan_result.enqueued_paths,
    )


def reconcile_brain(root: Path, *, include_knowledge_tree: bool = False) -> ReconcileReport:
    """Run the shared reconcile workflow and return a flattened report.

    CLI and MCP both need the same source-reconcile result shaping. Some
    callers, such as the CLI command, also want the knowledge-tree pass in the
    same workflow, while narrower callers can skip it.
    """

    source_result = reconcile_sources(root=root)
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

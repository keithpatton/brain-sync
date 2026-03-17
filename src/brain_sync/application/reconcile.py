"""Application-owned reconciliation workflows."""

from __future__ import annotations

from pathlib import Path

from brain_sync.application.insights import load_all_insight_states
from brain_sync.sync.reconcile import TreeReconcileResult
from brain_sync.sync.reconcile import reconcile_knowledge_tree as reconcile_tree_runtime

__all__ = ["TreeReconcileResult", "reconcile_knowledge_tree"]


def reconcile_knowledge_tree(root: Path) -> TreeReconcileResult:
    """Reconcile the knowledge tree using application-owned cross-plane state views."""
    tracked_paths = {state.knowledge_path for state in load_all_insight_states(root)}
    return reconcile_tree_runtime(root, tracked_paths=tracked_paths)

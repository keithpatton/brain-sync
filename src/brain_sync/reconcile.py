"""Startup knowledge-tree reconciliation.

Compares the knowledge/ folder tree against the regen_locks table and
co-located sidecars to detect offline structural changes (folder
rename/delete/move, file add/delete). Cleans stale DB rows and orphan
managed insight directories, and identifies paths needing regen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.fileops import clean_insights_tree, path_is_dir
from brain_sync.fs_utils import find_all_content_paths
from brain_sync.layout import area_insights_dir
from brain_sync.regen import classify_folder_change
from brain_sync.state import (
    delete_insight_state,
    load_all_insight_states,
)

log = logging.getLogger(__name__)


@dataclass
class TreeReconcileResult:
    orphans_cleaned: list[str] = field(default_factory=list)
    content_changed: list[str] = field(default_factory=list)
    enqueued_paths: list[str] = field(default_factory=list)


def _deepest_untracked_paths(paths: set[str]) -> list[str]:
    """Return only deepest untracked content paths, sorted deepest-first.

    Startup reconcile should seed regen from the deepest newly contentful areas.
    The normal walk-up behavior then rebuilds parents from the actual level of
    change rather than starting too high in the tree.
    """
    deepest: list[str] = []
    for path in sorted(paths, key=lambda p: (-p.count("/"), p)):
        if any(existing == path or existing.startswith(path + "/") for existing in deepest):
            continue
        deepest.append(path)
    return deepest


def reconcile_knowledge_tree(root: Path) -> TreeReconcileResult:
    """Reconcile knowledge/ folder tree against regen_locks DB + sidecars.

    Three-part algorithm:
    A) Clean orphan state — DB rows pointing to non-existent knowledge dirs
    B) Hash-check tracked folders — detect offline file add/delete
    C) Scoped enqueue for untracked folders
    """
    result = TreeReconcileResult()
    knowledge_root = root / "knowledge"

    if not path_is_dir(knowledge_root):
        return result

    # Part A: Clean orphan state
    fs_paths = set(find_all_content_paths(knowledge_root))
    db_states = load_all_insight_states(root)
    db_paths = {s.knowledge_path for s in db_states if s.knowledge_path}

    orphan_db_paths = db_paths - fs_paths
    for orphan in orphan_db_paths:
        delete_insight_state(root, orphan)
        orphan_insights = area_insights_dir(root, orphan)
        if path_is_dir(orphan_insights):
            fully_removed = clean_insights_tree(orphan_insights)
            if not fully_removed:
                log.info("Preserved non-regenerable artifacts in knowledge/%s/.brain-sync/insights", orphan)
            else:
                log.info("Cleaned orphan insights dir: knowledge/%s/.brain-sync/insights", orphan)
        log.info("Cleaned orphan regen state: %s", orphan)
        result.orphans_cleaned.append(orphan)

    # Part B: Hash-check tracked folders (offline file add/delete detection)
    tracked_paths = db_paths & fs_paths
    for path in tracked_paths:
        change, _, _ = classify_folder_change(root, path)
        if change.change_type != "none":
            result.content_changed.append(path)

    # Part B2: Root-path check — the root knowledge path ("")
    # find_all_content_paths() only returns subdirectories, and db_paths filters
    # out "". Handle root explicitly when a root DB row exists — this catches
    # offline changes to root-level files AND child directory changes that affect
    # the root summary. classify_folder_change(root, "") handles both cases.
    has_root_db_row = any(s.knowledge_path == "" for s in db_states)
    if has_root_db_row:
        change, _, _ = classify_folder_change(root, "")
        if change.change_type != "none":
            result.content_changed.append("")

    # Part C: Scoped enqueue for untracked folders
    untracked_paths = fs_paths - db_paths
    for path in _deepest_untracked_paths(untracked_paths):
        result.enqueued_paths.append(path)

    if result.orphans_cleaned or result.content_changed or result.enqueued_paths:
        log.info(
            "Tree reconcile: %d orphans cleaned, %d knowledge areas changed, %d knowledge areas enqueued",
            len(result.orphans_cleaned),
            len(result.content_changed),
            len(result.enqueued_paths),
        )

    return result

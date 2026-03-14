"""Startup knowledge-tree reconciliation.

Compares the knowledge/ folder tree against the regen_locks DB table and
sidecars to detect offline structural changes (folder rename/delete/move,
file add/delete).  Cleans stale DB rows and orphan insight directories,
and identifies paths needing regen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.fileops import clean_insights_tree
from brain_sync.fs_utils import find_all_content_paths
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


def reconcile_knowledge_tree(root: Path) -> TreeReconcileResult:
    """Reconcile knowledge/ folder tree against regen_locks DB + sidecars.

    Three-part algorithm:
    A) Clean orphan state — DB rows pointing to non-existent knowledge dirs
    B) Hash-check tracked folders — detect offline file add/delete
    C) Scoped enqueue for untracked folders
    """
    result = TreeReconcileResult()
    knowledge_root = root / "knowledge"
    insights_root = root / "insights"

    if not knowledge_root.is_dir():
        return result

    # Part A: Clean orphan state
    fs_paths = set(find_all_content_paths(knowledge_root))
    db_states = load_all_insight_states(root)
    db_paths = {s.knowledge_path for s in db_states if s.knowledge_path}

    orphan_db_paths = db_paths - fs_paths
    for orphan in orphan_db_paths:
        delete_insight_state(root, orphan)
        orphan_insights = insights_root / orphan
        if orphan_insights.is_dir():
            fully_removed = clean_insights_tree(orphan_insights)
            if not fully_removed:
                log.info("Preserved non-regenerable artifacts in insights/%s", orphan)
            else:
                log.info("Cleaned orphan insights dir: insights/%s", orphan)
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
    for path in untracked_paths:
        # Rule 1: insights/ dir exists → evidence of prior regen (moved folder)
        if (insights_root / path).is_dir():
            result.enqueued_paths.append(path)
            continue

        # Rule 2: orphans were cleaned → brain state disrupted by offline mutations
        if orphan_db_paths:
            result.enqueued_paths.append(path)

    if result.orphans_cleaned or result.content_changed or result.enqueued_paths:
        log.info(
            "Tree reconcile: %d orphans cleaned, %d content changed, %d enqueued",
            len(result.orphans_cleaned),
            len(result.content_changed),
            len(result.enqueued_paths),
        )

    return result

"""Startup knowledge-tree scanning.

Scans filesystem reality to find candidate knowledge paths for higher-level
classification. It does not call REGEN.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.brain.fileops import iterdir_paths, path_is_dir
from brain_sync.brain.layout import area_insights_dir
from brain_sync.brain.repository import BrainRepository
from brain_sync.brain.tree import find_all_content_paths, is_readable_file
from brain_sync.runtime.repository import delete_regen_lock

log = logging.getLogger(__name__)


@dataclass
class KnowledgeTreeScanResult:
    orphans_cleaned: list[str] = field(default_factory=list)
    candidate_paths: list[str] = field(default_factory=list)
    enqueued_paths: list[str] = field(default_factory=list)


def _deepest_untracked_paths(paths: set[str]) -> list[str]:
    deepest: list[str] = []
    for path in sorted(paths, key=lambda value: (-value.count("/"), value)):
        if any(existing == path or existing.startswith(path + "/") for existing in deepest):
            continue
        deepest.append(path)
    return deepest


def _parent_path(path: str) -> str:
    if not path:
        return ""
    parts = path.rsplit("/", 1)
    return parts[0] if len(parts) > 1 else ""


def scan_knowledge_tree(root: Path, *, tracked_paths: set[str]) -> KnowledgeTreeScanResult:
    """Scan filesystem reality and return tracked paths that need classification."""
    result = KnowledgeTreeScanResult()
    knowledge_root = root / "knowledge"
    repository = BrainRepository(root)

    if not path_is_dir(knowledge_root):
        return result

    fs_non_root_paths = set(find_all_content_paths(knowledge_root))
    root_has_readable_files = any(is_readable_file(entry) for entry in iterdir_paths(knowledge_root))
    tracked_non_root_paths = {path for path in tracked_paths if path}

    orphan_db_paths = tracked_non_root_paths - fs_non_root_paths
    for orphan in orphan_db_paths:
        repository.delete_portable_insight_state(orphan)
        delete_regen_lock(root, orphan)
        orphan_insights = area_insights_dir(root, orphan)
        if path_is_dir(orphan_insights):
            fully_removed = repository.clean_regenerable_insights(orphan)
            if not fully_removed:
                log.info("Preserved non-regenerable artifacts in knowledge/%s/.brain-sync/insights", orphan)
            else:
                log.info("Cleaned orphan insights dir: knowledge/%s/.brain-sync/insights", orphan)
        result.orphans_cleaned.append(orphan)
        parent = _parent_path(orphan)
        if parent in tracked_paths:
            result.candidate_paths.append(parent)

    tracked_existing_paths = tracked_non_root_paths & fs_non_root_paths
    result.candidate_paths.extend(sorted(tracked_existing_paths))
    if "" in tracked_paths:
        result.candidate_paths.append("")

    untracked_paths = fs_non_root_paths - tracked_non_root_paths
    result.enqueued_paths.extend(_deepest_untracked_paths(untracked_paths))
    if "" not in tracked_paths:
        # Root-level readable files have no child walk-up path, so a fresh
        # root area must be enqueued explicitly when that direct content exists.
        if root_has_readable_files:
            result.enqueued_paths.append("")

    if result.orphans_cleaned or result.candidate_paths or result.enqueued_paths:
        log.info(
            "Tree scan: %d orphans cleaned, %d candidate paths, %d knowledge areas enqueued",
            len(result.orphans_cleaned),
            len(result.candidate_paths),
            len(result.enqueued_paths),
        )

    return result

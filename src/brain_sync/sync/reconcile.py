"""Startup knowledge-tree scanning.

Scans filesystem reality and runtime path observations to find candidate
knowledge paths for higher-level classification. It does not call REGEN.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.brain.fileops import iterdir_paths, path_is_dir
from brain_sync.brain.layout import area_insights_dir
from brain_sync.brain.repository import BrainRepository
from brain_sync.brain.tree import is_content_dir, is_readable_file
from brain_sync.runtime.repository import delete_regen_lock, load_path_observations

log = logging.getLogger(__name__)


@dataclass
class KnowledgeTreeScanResult:
    orphans_cleaned: list[str] = field(default_factory=list)
    candidate_paths: list[str] = field(default_factory=list)
    enqueued_paths: list[str] = field(default_factory=list)
    observed_mtimes: dict[str, int] = field(default_factory=dict)
    active_paths: set[str] = field(default_factory=set)


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


def _observation_int(parts: list[bytes]) -> int:
    hasher = hashlib.sha256()
    for part in parts:
        hasher.update(part)
        hasher.update(b"\0")
    return int.from_bytes(hasher.digest()[:8], "big", signed=True)


def _scan_observed_paths(knowledge_root: Path) -> tuple[set[str], dict[str, int], bool]:
    active_paths: set[str] = set()
    observations: dict[str, int] = {}
    root_has_readable_files = False

    def _walk(directory: Path, prefix: str) -> tuple[bool, int]:
        nonlocal root_has_readable_files
        entries = iterdir_paths(directory)
        child_dirs = [entry for entry in entries if is_content_dir(entry)]
        readable_files = [entry for entry in entries if is_readable_file(entry)]
        if not prefix and readable_files:
            root_has_readable_files = True

        child_parts: list[bytes] = []
        for child in sorted(child_dirs, key=lambda value: value.name):
            child_rel = prefix + "/" + child.name if prefix else child.name
            _child_active, child_observation = _walk(child, child_rel)
            child_parts.append(f"dir:{child.name}:{child_observation}".encode())

        file_parts: list[bytes] = []
        for file_path in sorted(readable_files, key=lambda value: value.name):
            try:
                stat = file_path.stat()
            except OSError:
                continue
            file_parts.append(f"file:{file_path.name}:{stat.st_mtime_ns}:{stat.st_size}".encode())

        active = bool(child_dirs or readable_files)
        observation = _observation_int(child_parts + file_parts)
        if active:
            active_paths.add(prefix)
            observations[prefix] = observation
        return active, observation

    _walk(knowledge_root, "")
    return active_paths, observations, root_has_readable_files


def scan_knowledge_tree(root: Path, *, tracked_paths: set[str]) -> KnowledgeTreeScanResult:
    """Scan filesystem reality and narrow classification candidates."""
    result = KnowledgeTreeScanResult()
    knowledge_root = root / "knowledge"
    repository = BrainRepository(root)

    if not path_is_dir(knowledge_root):
        return result

    fs_paths, observed_mtimes, root_has_readable_files = _scan_observed_paths(knowledge_root)
    prior_observations = load_path_observations(root)
    tracked_non_root_paths = {path for path in tracked_paths if path}
    fs_non_root_paths = {path for path in fs_paths if path}

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
    for path in sorted(tracked_existing_paths):
        observed = observed_mtimes[path]
        result.observed_mtimes[path] = observed
        if prior_observations.get(path) != observed:
            result.candidate_paths.append(path)

    if "" in fs_paths:
        result.observed_mtimes[""] = observed_mtimes[""]
        if "" in tracked_paths and prior_observations.get("") != observed_mtimes[""]:
            result.candidate_paths.append("")

    untracked_paths = fs_non_root_paths - tracked_non_root_paths
    result.enqueued_paths.extend(_deepest_untracked_paths(untracked_paths))
    result.active_paths = set(fs_paths)
    if "" in fs_paths and "" not in tracked_paths:
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

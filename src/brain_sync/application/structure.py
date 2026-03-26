"""Application-owned structural tree export for semantic knowledge areas."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.brain.fileops import iterdir_paths, path_is_dir, path_is_file, rglob_paths
from brain_sync.brain.layout import (
    INSIGHT_STATE_FILENAME,
    SUMMARY_FILENAME,
    area_dir,
    area_insights_dir,
    area_journal_dir,
    knowledge_root,
)
from brain_sync.brain.managed_markdown import extract_source_id
from brain_sync.brain.manifest import read_all_source_manifests
from brain_sync.brain.sidecar import RegenMeta, read_all_regen_meta
from brain_sync.brain.tree import get_child_dirs, is_readable_file, normalize_path

_JOURNAL_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")
_SYNCED_STATE_ORDER = ("awaiting", "materialized", "stale", "missing")


@dataclass(frozen=True)
class SyncedFileCounts:
    awaiting: int = 0
    materialized: int = 0
    stale: int = 0
    missing: int = 0


@dataclass(frozen=True)
class InsightStats:
    artifact_count: int = 0
    summary_present: bool = False
    last_regen_utc: str | None = None


@dataclass(frozen=True)
class JournalStats:
    entry_count: int = 0
    first_entry_date: str | None = None
    last_entry_date: str | None = None


@dataclass(frozen=True)
class TreeNode:
    path: str
    depth: int
    child_folder_count: int = 0
    manual_file_count: int = 0
    synced_files: SyncedFileCounts = field(default_factory=SyncedFileCounts)
    insights: InsightStats = field(default_factory=InsightStats)
    journals: JournalStats = field(default_factory=JournalStats)


@dataclass(frozen=True)
class TreeResult:
    nodes: list[TreeNode]
    total_nodes: int
    max_depth: int


def _discover_semantic_paths(root: Path) -> set[str]:
    if not path_is_dir(root):
        return {""}

    semantic_paths: set[str] = set()

    def _walk(directory: Path, knowledge_path: str) -> bool:
        has_semantic_child = False
        for child in get_child_dirs(directory):
            child_path = child.name if not knowledge_path else f"{knowledge_path}/{child.name}"
            if _walk(child, child_path):
                has_semantic_child = True

        has_readable_files = any(is_readable_file(entry) for entry in iterdir_paths(directory))
        qualifies = knowledge_path == "" or has_readable_files or has_semantic_child
        if qualifies:
            semantic_paths.add(knowledge_path)
        return qualifies

    _walk(root, "")
    semantic_paths.add("")
    return semantic_paths


def _build_child_index(paths: set[str]) -> dict[str, list[str]]:
    child_index: dict[str, list[str]] = {path: [] for path in paths}
    for path in sorted((p for p in paths if p), key=str.casefold):
        parent = normalize_path(Path(path).parent)
        if parent in child_index:
            child_index[parent].append(path)
    for children in child_index.values():
        children.sort(key=str.casefold)
    return child_index


def _ordered_paths(child_index: dict[str, list[str]]) -> list[str]:
    ordered: list[str] = []

    def _walk(path: str) -> None:
        ordered.append(path)
        for child in child_index.get(path, []):
            _walk(child)

    _walk("")
    return ordered


def _build_synced_counts(root: Path) -> dict[str, SyncedFileCounts]:
    grouped: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(_SYNCED_STATE_ORDER, 0))
    for manifest in read_all_source_manifests(root).values():
        area_path = normalize_path(Path(manifest.knowledge_path).parent)
        grouped[area_path][manifest.knowledge_state] += 1
    return {
        path: SyncedFileCounts(
            awaiting=counts["awaiting"],
            materialized=counts["materialized"],
            stale=counts["stale"],
            missing=counts["missing"],
        )
        for path, counts in grouped.items()
    }


def _count_manual_files(root: Path, knowledge_path: str) -> int:
    directory = area_dir(root, knowledge_path)
    if not path_is_dir(directory):
        return 0
    count = 0
    for entry in iterdir_paths(directory):
        if not is_readable_file(entry):
            continue
        if extract_source_id(entry) is not None:
            continue
        count += 1
    return count


def _collect_insight_stats(root: Path, knowledge_path: str, regen_meta: dict[str, RegenMeta]) -> InsightStats:
    insights_dir = area_insights_dir(root, knowledge_path)
    artifact_count = 0
    summary_present = False

    if path_is_dir(insights_dir):
        for entry in iterdir_paths(insights_dir):
            if not path_is_file(entry) or entry.name.startswith(".") or entry.name == INSIGHT_STATE_FILENAME:
                continue
            artifact_count += 1
            if entry.name == SUMMARY_FILENAME:
                summary_present = True

    meta = regen_meta.get(knowledge_path)
    return InsightStats(
        artifact_count=artifact_count,
        summary_present=summary_present,
        last_regen_utc=meta.last_regen_utc if meta is not None else None,
    )


def _collect_journal_stats(root: Path, knowledge_path: str) -> JournalStats:
    journal_dir = area_journal_dir(root, knowledge_path)
    if not path_is_dir(journal_dir):
        return JournalStats()

    entry_count = 0
    dated_entries: list[str] = []
    for entry in rglob_paths(journal_dir, "*.md"):
        if not path_is_file(entry) or entry.name.startswith("."):
            continue
        entry_count += 1
        if _JOURNAL_DATE_RE.match(entry.name):
            dated_entries.append(entry.stem)

    if not dated_entries:
        return JournalStats(entry_count=entry_count)

    dated_entries.sort()
    return JournalStats(
        entry_count=entry_count,
        first_entry_date=dated_entries[0],
        last_entry_date=dated_entries[-1],
    )


def tree_brain(root: Path) -> TreeResult:
    """Return the full semantic knowledge-area tree under knowledge/."""
    knowledge = knowledge_root(root)
    semantic_paths = _discover_semantic_paths(knowledge)
    child_index = _build_child_index(semantic_paths)
    synced_counts = _build_synced_counts(root)
    regen_meta = read_all_regen_meta(knowledge)

    nodes = [
        TreeNode(
            path=knowledge_path,
            depth=0 if not knowledge_path else len(Path(knowledge_path).parts),
            child_folder_count=len(child_index.get(knowledge_path, [])),
            manual_file_count=_count_manual_files(root, knowledge_path),
            synced_files=synced_counts.get(knowledge_path, SyncedFileCounts()),
            insights=_collect_insight_stats(root, knowledge_path, regen_meta),
            journals=_collect_journal_stats(root, knowledge_path),
        )
        for knowledge_path in _ordered_paths(child_index)
    ]
    max_depth = max((node.depth for node in nodes), default=0)
    return TreeResult(nodes=nodes, total_nodes=len(nodes), max_depth=max_depth)


def tree_result_to_payload(result: TreeResult) -> dict:
    """Convert TreeResult into the sparse public JSON contract."""

    def _node_payload(node: TreeNode) -> dict:
        payload: dict[str, object] = {
            "path": node.path,
            "depth": node.depth,
        }
        if node.child_folder_count:
            payload["child_folder_count"] = node.child_folder_count
        if node.manual_file_count:
            payload["manual_file_count"] = node.manual_file_count

        synced_files: dict[str, int] = {}
        for field_name in _SYNCED_STATE_ORDER:
            value = getattr(node.synced_files, field_name)
            if value:
                synced_files[field_name] = value
        if synced_files:
            payload["synced_files"] = synced_files

        insights: dict[str, object] = {}
        if node.insights.summary_present:
            insights["summary_present"] = True
        if node.insights.artifact_count:
            insights["artifact_count"] = node.insights.artifact_count
        if node.insights.last_regen_utc is not None:
            insights["last_regen_utc"] = node.insights.last_regen_utc
        if insights:
            payload["insights"] = insights

        journals: dict[str, object] = {}
        if node.journals.entry_count:
            journals["entry_count"] = node.journals.entry_count
        if node.journals.first_entry_date is not None:
            journals["first_entry_date"] = node.journals.first_entry_date
        if node.journals.last_entry_date is not None:
            journals["last_entry_date"] = node.journals.last_entry_date
        if journals:
            payload["journals"] = journals

        return payload

    return {
        "nodes": [_node_payload(node) for node in result.nodes],
        "total_nodes": result.total_nodes,
        "max_depth": result.max_depth,
    }


def render_tree_lines(result: TreeResult) -> list[str]:
    """Render TreeResult in a compact human-readable CLI form."""

    def _label(path: str) -> str:
        if not path:
            return "knowledge/"
        return f"{Path(path).name}/"

    def _yes_no(value: bool) -> str:
        return "yes" if value else "no"

    lines: list[str] = []
    for node in result.nodes:
        indent = "  " * node.depth
        synced = node.synced_files
        segments = [
            f"folders={node.child_folder_count}",
            f"manual={node.manual_file_count}",
            (f"synced[a={synced.awaiting},m={synced.materialized},s={synced.stale},ms={synced.missing}]"),
            (
                "insights["
                f"summary={_yes_no(node.insights.summary_present)},"
                f"artifacts={node.insights.artifact_count},"
                f"last_regen={node.insights.last_regen_utc or '-'}"
                "]"
            ),
            (
                "journals["
                f"count={node.journals.entry_count},"
                f"first={node.journals.first_entry_date or '-'},"
                f"last={node.journals.last_entry_date or '-'}"
                "]"
            ),
        ]
        lines.append(f"{indent}{_label(node.path)}  {' '.join(segments)}")
    return lines


__all__ = [
    "InsightStats",
    "JournalStats",
    "SyncedFileCounts",
    "TreeNode",
    "TreeResult",
    "render_tree_lines",
    "tree_brain",
    "tree_result_to_payload",
]

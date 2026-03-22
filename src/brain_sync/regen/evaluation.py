"""Deterministic REGEN input evaluation for one knowledge area.

Owns change classification, child-summary loading, and content/structure hash
computation. It does not call the LLM or persist runtime lifecycle state.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from brain_sync.brain.fileops import TEXT_EXTENSIONS, iterdir_paths, path_exists, path_is_dir, read_bytes, read_text
from brain_sync.brain.layout import area_insights_dir, area_summary_path
from brain_sync.brain.sidecar import RegenMeta, load_regen_hashes
from brain_sync.brain.tree import get_child_dirs, is_readable_file, normalize_path


@dataclass
class ChangeEvent:
    """Classification of what changed in a folder between hash computations."""

    change_type: Literal["none", "rename", "content"]
    structural: bool


def classify_change(
    old_content_hash: str | None,
    new_content_hash: str,
    old_structure_hash: str | None,
    new_structure_hash: str,
) -> ChangeEvent:
    """Classify the type of change between old and new hash pairs."""

    content_changed = old_content_hash != new_content_hash
    structure_changed = old_structure_hash != new_structure_hash
    if not content_changed and not structure_changed:
        return ChangeEvent(change_type="none", structural=False)
    if not content_changed and structure_changed:
        return ChangeEvent(change_type="rename", structural=True)
    return ChangeEvent(change_type="content", structural=False)


FolderEvaluationOutcome = Literal[
    "missing_path",
    "no_content",
    "unchanged",
    "structure_only",
    "content_changed",
    "metadata_backfill",
]


@dataclass(frozen=True)
class FolderEvaluation:
    """Explicit evaluation result for one knowledge path before any backend call."""

    knowledge_path: str
    knowledge_dir: Path
    insights_dir: Path
    outcome: FolderEvaluationOutcome
    change: ChangeEvent
    meta: RegenMeta | None
    child_dirs: tuple[Path, ...]
    child_summaries: dict[str, str]
    has_direct_files: bool
    content_hash: str | None
    structure_hash: str | None
    summary_exists: bool


def compute_content_hash(
    child_summaries: dict[str, str],
    knowledge_dir: Path,
    has_direct_files: bool,
) -> str:
    """Compute content-only hash for a folder."""

    h = hashlib.sha256()
    for content in sorted(child_summaries.values()):
        h.update(content.encode("utf-8"))
    if has_direct_files:
        file_hashes: list[tuple[str, bytes]] = []
        for path in iterdir_paths(knowledge_dir):
            if is_readable_file(path):
                content = read_bytes(path)
                if path.suffix.lower() in TEXT_EXTENSIONS:
                    content = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                file_hashes.append((hashlib.sha256(content).hexdigest(), content))
        for _, content in sorted(file_hashes):
            h.update(content)
    return h.hexdigest()


def compute_structure_hash(
    child_dirs: list[Path],
    knowledge_dir: Path,
    has_direct_files: bool,
) -> str:
    """Compute structural hash capturing names only."""

    h = hashlib.sha256()
    for child in sorted(child_dirs, key=lambda directory: directory.name):
        h.update(b"dir:")
        h.update(child.name.encode("utf-8"))
    if has_direct_files:
        for path in sorted(
            (path for path in iterdir_paths(knowledge_dir) if is_readable_file(path)),
            key=lambda candidate: candidate.name,
        ):
            h.update(b"file:")
            h.update(path.name.encode("utf-8"))
    return h.hexdigest()


def collect_child_summaries(
    root: Path,
    current_path: str,
    child_dirs: list[Path],
) -> dict[str, str]:
    """Read existing child summaries from co-located area insights."""

    child_summaries: dict[str, str] = {}
    for child in child_dirs:
        child_rel = current_path + "/" + child.name if current_path else child.name
        child_summary_path = area_summary_path(root, child_rel)
        if path_exists(child_summary_path):
            child_summaries[child.name] = read_text(child_summary_path, encoding="utf-8")
    return child_summaries


def evaluate_folder_state(root: Path, knowledge_path: str) -> FolderEvaluation:
    """Evaluate one knowledge path without invoking the backend."""

    normalized_path = normalize_path(knowledge_path)
    knowledge_dir = root / "knowledge" / normalized_path if normalized_path else root / "knowledge"
    insights_dir = area_insights_dir(root, normalized_path)
    if not path_is_dir(knowledge_dir):
        return FolderEvaluation(
            knowledge_path=normalized_path,
            knowledge_dir=knowledge_dir,
            insights_dir=insights_dir,
            outcome="missing_path",
            change=ChangeEvent(change_type="content", structural=False),
            meta=None,
            child_dirs=(),
            child_summaries={},
            has_direct_files=False,
            content_hash=None,
            structure_hash=None,
            summary_exists=False,
        )

    meta = load_regen_hashes(root, normalized_path)
    child_dirs = tuple(get_child_dirs(knowledge_dir))
    has_direct_files = any(is_readable_file(path) for path in iterdir_paths(knowledge_dir))
    if not child_dirs and not has_direct_files:
        return FolderEvaluation(
            knowledge_path=normalized_path,
            knowledge_dir=knowledge_dir,
            insights_dir=insights_dir,
            outcome="no_content",
            change=ChangeEvent(change_type="content", structural=False),
            meta=meta,
            child_dirs=child_dirs,
            child_summaries={},
            has_direct_files=False,
            content_hash=None,
            structure_hash=None,
            summary_exists=path_exists(insights_dir / "summary.md"),
        )

    child_summaries = collect_child_summaries(root, normalized_path, list(child_dirs))
    if not child_summaries and not has_direct_files:
        return FolderEvaluation(
            knowledge_path=normalized_path,
            knowledge_dir=knowledge_dir,
            insights_dir=insights_dir,
            outcome="no_content",
            change=ChangeEvent(change_type="content", structural=False),
            meta=meta,
            child_dirs=child_dirs,
            child_summaries={},
            has_direct_files=False,
            content_hash=None,
            structure_hash=None,
            summary_exists=path_exists(insights_dir / "summary.md"),
        )

    content_hash = compute_content_hash(child_summaries, knowledge_dir, has_direct_files)
    structure_hash = compute_structure_hash(list(child_dirs), knowledge_dir, has_direct_files)
    summary_exists = path_exists(insights_dir / "summary.md")

    if not meta or not meta.content_hash:
        return FolderEvaluation(
            knowledge_path=normalized_path,
            knowledge_dir=knowledge_dir,
            insights_dir=insights_dir,
            outcome="content_changed",
            change=ChangeEvent(change_type="content", structural=False),
            meta=meta,
            child_dirs=child_dirs,
            child_summaries=child_summaries,
            has_direct_files=has_direct_files,
            content_hash=content_hash,
            structure_hash=structure_hash,
            summary_exists=summary_exists,
        )

    if meta.structure_hash is None and summary_exists:
        return FolderEvaluation(
            knowledge_path=normalized_path,
            knowledge_dir=knowledge_dir,
            insights_dir=insights_dir,
            outcome="metadata_backfill",
            change=ChangeEvent(change_type="none", structural=False),
            meta=meta,
            child_dirs=child_dirs,
            child_summaries=child_summaries,
            has_direct_files=has_direct_files,
            content_hash=content_hash,
            structure_hash=structure_hash,
            summary_exists=True,
        )

    event = classify_change(
        meta.content_hash,
        content_hash,
        meta.structure_hash,
        structure_hash,
    )
    outcome: FolderEvaluationOutcome
    if event.change_type == "none":
        outcome = "unchanged"
    elif event.structural:
        outcome = "structure_only"
    else:
        outcome = "content_changed"

    return FolderEvaluation(
        knowledge_path=normalized_path,
        knowledge_dir=knowledge_dir,
        insights_dir=insights_dir,
        outcome=outcome,
        change=event,
        meta=meta,
        child_dirs=child_dirs,
        child_summaries=child_summaries,
        has_direct_files=has_direct_files,
        content_hash=content_hash,
        structure_hash=structure_hash,
        summary_exists=summary_exists,
    )


__all__ = [
    "ChangeEvent",
    "FolderEvaluation",
    "FolderEvaluationOutcome",
    "classify_change",
    "collect_child_summaries",
    "compute_content_hash",
    "compute_structure_hash",
    "evaluate_folder_state",
]

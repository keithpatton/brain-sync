"""Shared filesystem helpers for brain content discovery.

Used by both the regen engine and the MCP server. Extracted from regen.py
to avoid coupling between these independent consumers.
"""

from __future__ import annotations

from pathlib import Path

from brain_sync.fileops import EXCLUDED_DIRS, KNOWLEDGE_EXTENSIONS


def normalize_path(p: str | Path) -> str:
    """Normalize a relative path to forward slashes for consistent storage.

    Use this for any path that will be stored in the DB or compared across
    modules. Converts backslashes (Windows Path artefacts) to forward slashes.
    """
    result = str(p).replace("\\", "/")
    return "" if result == "." else result


def is_readable_file(p: Path) -> bool:
    """Check if a file has a readable extension and is not hidden."""
    return p.is_file() and p.suffix.lower() in KNOWLEDGE_EXTENSIONS and not p.name.startswith(("_", "."))


def is_content_dir(p: Path) -> bool:
    """Check if a directory should be included in content discovery."""
    return p.is_dir() and not p.name.startswith(".") and p.name not in EXCLUDED_DIRS


def get_child_dirs(directory: Path) -> list[Path]:
    """Get child content directories, excluding EXCLUDED_DIRS and dotfiles."""
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if is_content_dir(p))


def find_all_content_paths(knowledge_root: Path) -> list[str]:
    """Find all knowledge paths bottom-up (deepest first).

    Walks the tree, collects all folders that have readable files or
    child content dirs, sorted deepest-first so that regen_all processes
    leaves before parents.
    """
    paths: list[str] = []

    def _walk(directory: Path, prefix: str) -> None:
        if not directory.is_dir():
            return
        for child in sorted(directory.iterdir()):
            if not is_content_dir(child):
                continue
            child_rel = prefix + "/" + child.name if prefix else child.name
            # Recurse first (depth-first → deepest paths added first)
            _walk(child, child_rel)
            # Include this folder if it has readable files or content child dirs
            has_files = any(is_readable_file(p) for p in child.iterdir())
            has_children = any(is_content_dir(p) for p in child.iterdir())
            if has_files or has_children:
                paths.append(child_rel)

    _walk(knowledge_root, "")
    return paths

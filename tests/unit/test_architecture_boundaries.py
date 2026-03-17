from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_FORBIDDEN_IMPORTS = {
    "brain_sync.brain.fileops": {
        "atomic_write_bytes",
        "write_if_changed",
        "write_bytes_if_changed",
        "clean_insights_tree",
    },
    "brain_sync.brain.manifest": {
        "write_source_manifest",
        "delete_source_manifest",
        "mark_manifest_missing",
        "clear_manifest_missing",
    },
    "brain_sync.brain.sidecar": {
        "write_regen_meta",
        "delete_regen_meta",
    },
}

_ALLOWED_EXCEPTION_FILES = {
    "src/brain_sync/application/init.py",
    "src/brain_sync/brain/repository.py",
    "src/brain_sync/runtime/repository.py",
    "src/brain_sync/sync/pipeline.py",
}

_LEGACY_IMPORT_STRINGS = {
    "brain_sync.area_index",
    "brain_sync.attachments",
    "brain_sync.brain_repository",
    "brain_sync.cli",
    "brain_sync.commands",
    "brain_sync.config",
    "brain_sync.confluence_rest",
    "brain_sync.converter",
    "brain_sync.docx_converter",
    "brain_sync.fileops",
    "brain_sync.fs_utils",
    "brain_sync.layout",
    "brain_sync.logging_config",
    "brain_sync.managed_markdown",
    "brain_sync.manifest",
    "brain_sync.mcp",
    "brain_sync.pipeline",
    "brain_sync.reconcile",
    "brain_sync.regen_lifecycle",
    "brain_sync.regen_queue",
    "brain_sync.retry",
    "brain_sync.scheduler",
    "brain_sync.sidecar",
    "brain_sync.state",
    "brain_sync.token_tracking",
    "brain_sync.watcher",
}


def test_portable_mutation_primitives_do_not_spread_beyond_approved_exception_set() -> None:
    root = Path(__file__).resolve().parents[2]
    src_root = root / "src" / "brain_sync"
    violations: list[str] = []

    for path in src_root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel in _ALLOWED_EXCEPTION_FILES:
            continue
        if path.name in {"fileops.py", "manifest.py", "sidecar.py"}:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module not in _FORBIDDEN_IMPORTS:
                continue
            forbidden = _FORBIDDEN_IMPORTS[node.module]
            imported = sorted(alias.name for alias in node.names if alias.name in forbidden)
            if imported:
                violations.append(f"{rel}: {node.module} -> {', '.join(imported)}")

    message = "Portable mutation primitive imports must stay within the approved exception set:\n" + "\n".join(
        violations
    )
    assert violations == [], message


def test_in_repo_python_files_use_canonical_module_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    violations: list[str] = []

    for search_root in (root / "src" / "brain_sync", root / "tests"):
        for path in search_root.rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if rel == "tests/unit/test_architecture_boundaries.py":
                continue

            text = path.read_text(encoding="utf-8")
            hits = sorted(pattern for pattern in _LEGACY_IMPORT_STRINGS if pattern in text)
            if hits:
                violations.append(f"{rel}: {', '.join(hits)}")

    message = "In-repo Python files must use canonical package paths only:\n" + "\n".join(violations)
    assert violations == [], message

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_FORBIDDEN_IMPORTS = {
    "brain_sync.fileops": {
        "atomic_write_bytes",
        "write_if_changed",
        "write_bytes_if_changed",
        "clean_insights_tree",
    },
    "brain_sync.manifest": {
        "write_source_manifest",
        "delete_source_manifest",
        "mark_manifest_missing",
        "clear_manifest_missing",
    },
    "brain_sync.sidecar": {
        "write_regen_meta",
        "delete_regen_meta",
    },
}

_ALLOWED_EXCEPTION_FILES = {
    "src/brain_sync/brain_repository.py",
    "src/brain_sync/state.py",
    "src/brain_sync/commands/init.py",
    "src/brain_sync/pipeline.py",
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

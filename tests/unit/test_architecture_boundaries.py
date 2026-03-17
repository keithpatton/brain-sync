from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _ROOT / "src" / "brain_sync"
_CANONICAL_PACKAGES = frozenset(
    {
        "application",
        "interfaces",
        "brain",
        "runtime",
        "sync",
        "regen",
        "query",
        "sources",
        "llm",
        "util",
    }
)

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

_ALLOWED_PORTABLE_MUTATION_EXCEPTION_FILES = {
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

_ALLOWED_PACKAGE_DEPENDENCIES = {
    "application": frozenset({"brain", "runtime", "sync", "regen", "query", "sources", "llm", "util"}),
    "interfaces": frozenset({"application"}),
    "brain": frozenset({"util"}),
    "runtime": frozenset({"util"}),
    "sync": frozenset({"brain", "runtime", "sources", "util"}),
    "regen": frozenset({"brain", "runtime", "llm", "util"}),
    "query": frozenset({"brain", "util"}),
    "sources": frozenset({"util"}),
    "llm": frozenset({"util"}),
    "util": frozenset(),
}

# Normative carveouts from docs/RULES.md.
_ORCHESTRATION_SURFACE_IMPORTS = {
    "src/brain_sync/__main__.py": frozenset(
        {
            "brain_sync.interfaces.cli",
            "brain_sync.interfaces.cli.handlers",
            "brain_sync.runtime.config",
            "brain_sync.util.logging",
        }
    ),
    "src/brain_sync/interfaces/cli/handlers.py": frozenset(
        {
            "brain_sync.brain.fileops",
            "brain_sync.brain.tree",
            "brain_sync.query.area_index",
            "brain_sync.query.placement",
            "brain_sync.regen",
            "brain_sync.regen.lifecycle",
            "brain_sync.runtime.repository",
            "brain_sync.runtime.token_tracking",
            "brain_sync.sources",
            "brain_sync.sources.docx",
            "brain_sync.sources.title_resolution",
            "brain_sync.sync.daemon",
            "brain_sync.sync.reconcile",
        }
    ),
    "src/brain_sync/interfaces/mcp/server.py": frozenset(
        {
            "brain_sync.brain.fileops",
            "brain_sync.brain.layout",
            "brain_sync.brain.repository",
            "brain_sync.brain.tree",
            "brain_sync.query.area_index",
            "brain_sync.query.placement",
            "brain_sync.regen",
            "brain_sync.regen.lifecycle",
            "brain_sync.runtime.config",
            "brain_sync.runtime.token_tracking",
            "brain_sync.sources",
            "brain_sync.sources.title_resolution",
            "brain_sync.util.logging",
        }
    ),
    "src/brain_sync/sync/daemon.py": frozenset(
        {
            "brain_sync.application.sources",
            "brain_sync.regen",
            "brain_sync.regen.lifecycle",
            "brain_sync.regen.queue",
        }
    ),
}

_RULE_EXCEPTION_IMPORTS = {
    "src/brain_sync/query/placement.py": frozenset({"brain_sync.sources.docx"}),
    "src/brain_sync/sources/confluence/attachments.py": frozenset(
        {
            "brain_sync.brain.fileops",
            "brain_sync.brain.repository",
            "brain_sync.sync.attachments",
        }
    ),
    "src/brain_sync/sources/confluence/auth.py": frozenset({"brain_sync.runtime.config"}),
    "src/brain_sync/sources/confluence/rest.py": frozenset({"brain_sync.runtime.config"}),
    "src/brain_sync/sources/googledocs/auth.py": frozenset({"brain_sync.runtime.config"}),
    "src/brain_sync/sources/test/__init__.py": frozenset({"brain_sync.runtime.config"}),
}

# Transitional debt documented in docs/architecture/ARCHITECTURE.md.
_TRANSITIONAL_DEBT_IMPORTS = {
    "src/brain_sync/runtime/repository.py": frozenset(
        {
            "brain_sync.brain.fileops",
            "brain_sync.brain.layout",
            "brain_sync.brain.managed_markdown",
            "brain_sync.brain.manifest",
            "brain_sync.brain.repository",
            "brain_sync.brain.sidecar",
            "brain_sync.brain.tree",
        }
    ),
    "src/brain_sync/sync/reconcile.py": frozenset({"brain_sync.regen"}),
    "src/brain_sync/sync/watcher.py": frozenset({"brain_sync.regen"}),
}


def _iter_python_files() -> list[Path]:
    return sorted(_SRC_ROOT.rglob("*.py"))


def _root_relative(path: Path) -> str:
    return path.relative_to(_ROOT).as_posix()


def _owning_package(rel_path: str) -> str | None:
    if not rel_path.startswith("src/brain_sync/"):
        return None
    remainder = rel_path.removeprefix("src/brain_sync/")
    if "/" not in remainder:
        return None
    package = remainder.split("/", 1)[0]
    return package if package in _CANONICAL_PACKAGES else None


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names if alias.name.startswith("brain_sync."))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("brain_sync."):
            modules.add(node.module)
    return modules


def _module_package(module: str) -> str | None:
    parts = module.split(".")
    if len(parts) < 2 or parts[0] != "brain_sync":
        return None
    package = parts[1]
    return package if package in _CANONICAL_PACKAGES else None


def _off_graph_imports(rel_path: str, modules: set[str]) -> set[str]:
    package = _owning_package(rel_path)
    if package is None:
        return set(modules)

    allowed_packages = _ALLOWED_PACKAGE_DEPENDENCIES[package]
    off_graph: set[str] = set()
    for module in modules:
        dep_package = _module_package(module)
        if dep_package is None or dep_package == package or dep_package in allowed_packages:
            continue
        off_graph.add(module)
    return off_graph


def _assert_exact_allowlist(
    *,
    allowlist: dict[str, frozenset[str]],
    actual_off_graph: dict[str, set[str]],
    label: str,
) -> None:
    violations: list[str] = []
    stale: list[str] = []

    for rel_path, allowed_modules in sorted(allowlist.items()):
        actual = actual_off_graph.get(rel_path, set())
        if not actual:
            stale.append(rel_path)
            continue
        unexpected = sorted(module for module in actual if module not in allowed_modules)
        if unexpected:
            violations.append(f"{rel_path}: {', '.join(unexpected)}")

    if violations or stale:
        message_parts = [f"{label} must stay closed and exact."]
        if violations:
            message_parts.append("Unexpected imports:\n" + "\n".join(violations))
        if stale:
            message_parts.append("Stale exception entries:\n" + "\n".join(sorted(stale)))
        raise AssertionError("\n\n".join(message_parts))


def test_portable_mutation_primitives_do_not_spread_beyond_approved_exception_set() -> None:
    violations: list[str] = []

    for path in _iter_python_files():
        rel = _root_relative(path)
        if rel in _ALLOWED_PORTABLE_MUTATION_EXCEPTION_FILES:
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
    violations: list[str] = []

    for search_root in (_ROOT / "src" / "brain_sync", _ROOT / "tests"):
        for path in search_root.rglob("*.py"):
            rel = path.relative_to(_ROOT).as_posix()
            if rel == "tests/unit/test_architecture_boundaries.py":
                continue

            text = path.read_text(encoding="utf-8")
            hits = sorted(pattern for pattern in _LEGACY_IMPORT_STRINGS if pattern in text)
            if hits:
                violations.append(f"{rel}: {', '.join(hits)}")

    message = "In-repo Python files must use canonical package paths only:\n" + "\n".join(violations)
    assert violations == [], message


def test_no_undocumented_off_graph_imports_exist() -> None:
    actual_off_graph = {
        _root_relative(path): _off_graph_imports(_root_relative(path), _imported_modules(path))
        for path in _iter_python_files()
    }
    actual_off_graph = {rel: modules for rel, modules in actual_off_graph.items() if modules}

    documented = set(_ORCHESTRATION_SURFACE_IMPORTS) | set(_RULE_EXCEPTION_IMPORTS) | set(_TRANSITIONAL_DEBT_IMPORTS)

    unexpected = sorted(set(actual_off_graph) - documented)
    stale = sorted(documented - set(actual_off_graph))

    message_parts: list[str] = []
    if unexpected:
        message_parts.append("Unexpected off-graph import files:\n" + "\n".join(unexpected))
    if stale:
        message_parts.append("Stale documented boundary exceptions:\n" + "\n".join(stale))

    assert message_parts == [], "\n\n".join(message_parts)


def test_rule_orchestration_surfaces_are_closed_and_exact() -> None:
    actual_off_graph = {
        _root_relative(path): _off_graph_imports(_root_relative(path), _imported_modules(path))
        for path in _iter_python_files()
    }
    _assert_exact_allowlist(
        allowlist=_ORCHESTRATION_SURFACE_IMPORTS,
        actual_off_graph=actual_off_graph,
        label="Closed orchestration surfaces",
    )


def test_rule_file_level_exceptions_are_closed_and_exact() -> None:
    actual_off_graph = {
        _root_relative(path): _off_graph_imports(_root_relative(path), _imported_modules(path))
        for path in _iter_python_files()
    }
    _assert_exact_allowlist(
        allowlist=_RULE_EXCEPTION_IMPORTS,
        actual_off_graph=actual_off_graph,
        label="Rule-level file exceptions",
    )


def test_transitional_boundary_debts_are_closed_and_exact() -> None:
    actual_off_graph = {
        _root_relative(path): _off_graph_imports(_root_relative(path), _imported_modules(path))
        for path in _iter_python_files()
    }
    _assert_exact_allowlist(
        allowlist=_TRANSITIONAL_DEBT_IMPORTS,
        actual_off_graph=actual_off_graph,
        label="Transitional boundary debts",
    )

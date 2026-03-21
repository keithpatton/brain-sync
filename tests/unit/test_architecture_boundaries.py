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
    "sync": frozenset({"brain", "runtime", "regen", "sources", "util"}),
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
            "brain_sync.runtime.paths",
            "brain_sync.util.logging",
        }
    ),
    "src/brain_sync/interfaces/cli/handlers.py": frozenset(
        {
            "brain_sync.brain.fileops",
            "brain_sync.sources.docx",
            "brain_sync.sync.daemon",
        }
    ),
    "src/brain_sync/interfaces/mcp/server.py": frozenset(
        {
            "brain_sync.runtime.config",
            "brain_sync.runtime.repository",
            "brain_sync.util.logging",
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

_TRANSITIONAL_DEBT_IMPORTS: dict[str, frozenset[str]] = {}
_SYNC_LIFECYCLE_ORCHESTRATORS = frozenset(
    {
        "src/brain_sync/sync/lifecycle.py",
        "src/brain_sync/sync/finalization.py",
    }
)
_SYNC_LIFECYCLE_ONLY_FILES = frozenset({"src/brain_sync/sync/lifecycle.py"})
_LIFECYCLE_RESERVED_METHODS = frozenset(
    {
        "save_source_manifest",
        "update_source_sync_settings",
        "mark_source_missing",
        "sync_manifest_to_found_path",
        "delete_source_registration",
        "remove_source_owned_files",
        "materialize_markdown",
        "set_source_area_path",
    }
)
_LIFECYCLE_ONLY_RESERVED_METHODS = frozenset(
    {
        "move_knowledge_tree",
        "move_source_attachment_dir",
        "apply_folder_move_to_manifests",
    }
)


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


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _import_alias_map(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name != "brain_sync" and not alias.name.startswith("brain_sync."):
                    continue
                if alias.asname:
                    aliases[alias.asname] = alias.name
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (node.module == "brain_sync" or node.module.startswith("brain_sync."))
        ):
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _resolve_import_alias(dotted: str, aliases: dict[str, str]) -> str:
    parts = dotted.split(".")
    for size in range(len(parts), 0, -1):
        prefix = ".".join(parts[:size])
        target = aliases.get(prefix)
        if target is None:
            continue
        suffix = ".".join(parts[size:])
        return target if not suffix else f"{target}.{suffix}"
    return dotted


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
        missing = sorted(module for module in allowed_modules if module not in actual)
        if unexpected:
            violations.append(f"{rel_path}: {', '.join(unexpected)}")
        if missing:
            stale.append(f"{rel_path}: {', '.join(missing)}")

    if violations or stale:
        message_parts = [f"{label} must stay closed and exact."]
        if violations:
            message_parts.append("Unexpected imports:\n" + "\n".join(violations))
        if stale:
            message_parts.append("Stale exception entries:\n" + "\n".join(sorted(stale)))
        raise AssertionError("\n\n".join(message_parts))


def _brain_repository_method_calls(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            calls.add(node.func.attr)
    return calls


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


def test_application_barrel_reexports_only_application_submodules() -> None:
    barrel = _ROOT / "src" / "brain_sync" / "application" / "__init__.py"
    imported = _imported_modules(barrel)
    violations = sorted(module for module in imported if not module.startswith("brain_sync.application."))
    message = "brain_sync.application.__init__ must re-export only application-owned submodules:\n" + "\n".join(
        violations
    )
    assert violations == [], message


def test_runtime_persistence_owner_is_the_only_production_sqlite_surface() -> None:
    violations: list[str] = []

    for path in _iter_python_files():
        rel = _root_relative(path)
        if rel == "src/brain_sync/runtime/repository.py":
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        import_aliases = _import_alias_map(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "sqlite3" for alias in node.names):
                    violations.append(f"{rel}: imports sqlite3 directly")
            elif isinstance(node, ast.ImportFrom):
                if node.module == "sqlite3":
                    violations.append(f"{rel}: imports from sqlite3 directly")
                if node.module == "brain_sync.runtime.repository":
                    private_runtime_helpers = sorted(alias.name for alias in node.names if alias.name.startswith("_"))
                    if private_runtime_helpers:
                        violations.append(
                            f"{rel}: imports private runtime.repository helper(s): {', '.join(private_runtime_helpers)}"
                        )
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "sqlite3"
                and node.func.attr == "connect"
            ):
                violations.append(f"{rel}: calls sqlite3.connect() directly")
            elif isinstance(node, ast.Attribute):
                dotted = _dotted_name(node)
                if dotted is None:
                    continue
                resolved = _resolve_import_alias(dotted, import_aliases)
                if resolved.startswith("brain_sync.runtime.repository._"):
                    violations.append(f"{rel}: accesses private runtime.repository helper via alias: {dotted}")

    message = "Runtime persistence must stay behind brain_sync.runtime.repository:\n" + "\n".join(violations)
    assert violations == [], message


def test_area_index_build_stays_behind_application_query_index() -> None:
    violations: list[str] = []
    allowed_callers = {
        "src/brain_sync/application/query_index.py",
        "src/brain_sync/query/area_index.py",
    }

    for path in _iter_python_files():
        rel = _root_relative(path)
        if rel in allowed_callers:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        import_aliases = _import_alias_map(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            dotted = _dotted_name(node.func)
            if dotted is None:
                continue
            resolved = _resolve_import_alias(dotted, import_aliases)
            if resolved in {
                "brain_sync.application.query_index.AreaIndex.build",
                "brain_sync.query.area_index.AreaIndex.build",
            }:
                violations.append(f"{rel}: calls {dotted} directly")

    message = "AreaIndex lifecycle must stay behind brain_sync.application.query_index:\n" + "\n".join(violations)
    assert violations == [], message


def test_import_alias_resolution_catches_parent_package_runtime_chain() -> None:
    tree = ast.parse(
        "import brain_sync.runtime as rt\nimport brain_sync.runtime.repository\nrt.repository._connect_runtime()\n"
    )

    aliases = _import_alias_map(tree)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    dotted = _dotted_name(call.func)

    assert dotted == "rt.repository._connect_runtime"
    assert _resolve_import_alias(dotted, aliases) == "brain_sync.runtime.repository._connect_runtime"


def test_import_alias_resolution_catches_parent_package_query_chain() -> None:
    tree = ast.parse(
        "import brain_sync.query as q\nimport brain_sync.query.area_index\nq.area_index.AreaIndex.build(root)\n"
    )

    aliases = _import_alias_map(tree)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    dotted = _dotted_name(call.func)

    assert dotted == "q.area_index.AreaIndex.build"
    assert _resolve_import_alias(dotted, aliases) == "brain_sync.query.area_index.AreaIndex.build"


def test_import_alias_resolution_catches_root_package_runtime_chain() -> None:
    tree = ast.parse("import brain_sync as bs\nbs.runtime.repository._connect_runtime()\n")

    aliases = _import_alias_map(tree)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    dotted = _dotted_name(call.func)

    assert dotted == "bs.runtime.repository._connect_runtime"
    assert _resolve_import_alias(dotted, aliases) == "brain_sync.runtime.repository._connect_runtime"


def test_import_alias_resolution_catches_root_from_import_runtime_chain() -> None:
    tree = ast.parse("from brain_sync import runtime as rt\nrt.repository._connect_runtime()\n")

    aliases = _import_alias_map(tree)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    dotted = _dotted_name(call.func)

    assert dotted == "rt.repository._connect_runtime"
    assert _resolve_import_alias(dotted, aliases) == "brain_sync.runtime.repository._connect_runtime"


def test_import_alias_resolution_catches_root_package_query_chain() -> None:
    tree = ast.parse("import brain_sync as bs\nbs.query.area_index.AreaIndex.build(root)\n")

    aliases = _import_alias_map(tree)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    dotted = _dotted_name(call.func)

    assert dotted == "bs.query.area_index.AreaIndex.build"
    assert _resolve_import_alias(dotted, aliases) == "brain_sync.query.area_index.AreaIndex.build"


def test_import_alias_resolution_catches_root_from_import_query_chain() -> None:
    tree = ast.parse("from brain_sync import query as q\nq.area_index.AreaIndex.build(root)\n")

    aliases = _import_alias_map(tree)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    dotted = _dotted_name(call.func)

    assert dotted == "q.area_index.AreaIndex.build"
    assert _resolve_import_alias(dotted, aliases) == "brain_sync.query.area_index.AreaIndex.build"


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


def test_sync_package_no_longer_imports_application_modules() -> None:
    violations: list[str] = []

    for path in sorted((_SRC_ROOT / "sync").rglob("*.py")):
        rel = _root_relative(path)
        imported = _imported_modules(path)
        forbidden = sorted(module for module in imported if module.startswith("brain_sync.application"))
        if forbidden:
            violations.append(f"{rel}: {', '.join(forbidden)}")

    message = "Production sync modules must not import application modules:\n" + "\n".join(violations)
    assert violations == [], message


def test_sync_lifecycle_orchestrators_are_named_explicitly() -> None:
    for rel_path in sorted(_SYNC_LIFECYCLE_ORCHESTRATORS):
        assert (_ROOT / rel_path).exists(), f"Expected lifecycle orchestrator file missing: {rel_path}"

    policy_path = _ROOT / "src" / "brain_sync" / "sync" / "lifecycle_policy.py"
    tree = ast.parse(policy_path.read_text(encoding="utf-8"), filename=str(policy_path))
    violations = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
    violations.extend(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
    forbidden = sorted(
        module
        for module in violations
        if module.startswith("brain_sync.brain")
        or module.startswith("brain_sync.runtime")
        or module.startswith("brain_sync.application")
    )
    assert forbidden == [], "sync.lifecycle_policy.py must remain IO-free:\n" + "\n".join(forbidden)


def test_reserved_brain_repository_lifecycle_methods_are_called_only_from_approved_orchestrators() -> None:
    violations: list[str] = []

    for path in _iter_python_files():
        rel = _root_relative(path)
        calls = _brain_repository_method_calls(path)
        shared_hits = sorted(calls & _LIFECYCLE_RESERVED_METHODS)
        lifecycle_only_hits = sorted(calls & _LIFECYCLE_ONLY_RESERVED_METHODS)
        if shared_hits and rel not in _SYNC_LIFECYCLE_ORCHESTRATORS:
            violations.append(f"{rel}: {', '.join(shared_hits)}")
        if lifecycle_only_hits and rel not in _SYNC_LIFECYCLE_ONLY_FILES:
            violations.append(f"{rel}: {', '.join(lifecycle_only_hits)}")

    message = (
        "Reserved BrainRepository lifecycle mutation methods must stay in sync/lifecycle.py "
        "or sync/finalization.py as approved:\n" + "\n".join(violations)
    )
    assert violations == [], message

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


_EXPECTED_SUBPROCESS_ENV_PATHS = {
    "e2e/harness/cli.py",
    "e2e/harness/daemon.py",
    "e2e/test_db_contention.py",
    "mcp/test_mcp_stdio.py",
    "system/test_cli_commands.py",
}


def _tests_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _call_has_env_keyword(node: ast.Call) -> bool:
    return any(keyword.arg == "env" for keyword in node.keywords)


def test_subprocess_env_construction_paths_match_inventory() -> None:
    callers: set[str] = set()
    for path in _tests_root().rglob("*.py"):
        if path.name.startswith("__"):
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == "build_subprocess_env":
                callers.add(path.relative_to(_tests_root()).as_posix())
                break
            if not _call_has_env_keyword(node):
                continue
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                if node.func.value.id == "subprocess" and node.func.attr in {"run", "Popen"}:
                    callers.add(path.relative_to(_tests_root()).as_posix())
                    break
            if isinstance(node.func, ast.Name) and node.func.id == "StdioServerParameters":
                callers.add(path.relative_to(_tests_root()).as_posix())
                break

    assert callers == _EXPECTED_SUBPROCESS_ENV_PATHS

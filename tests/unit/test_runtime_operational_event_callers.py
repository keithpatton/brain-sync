from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


_EXPECTED_BRAIN_EVENT_CALLERS = {
    "application/local_files.py",
    "application/query_index.py",
    "application/sources.py",
    "regen/engine.py",
    "regen/queue.py",
    "runtime/repository.py",
    "sync/finalization.py",
    "sync/lifecycle.py",
    "sync/reconcile.py",
}


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "brain_sync"


def _callers_of(function_name: str) -> set[str]:
    callers: set[str] = set()
    for path in _source_root().rglob("*.py"):
        module = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == function_name)
                or (isinstance(node.func, ast.Attribute) and node.func.attr == function_name)
            )
            for node in ast.walk(module)
        ):
            callers.add(path.relative_to(_source_root()).as_posix())
    return callers


def test_brain_scoped_operational_event_callers_match_inventory() -> None:
    assert _callers_of("record_brain_operational_event") == _EXPECTED_BRAIN_EVENT_CALLERS


def test_rootless_operational_event_api_is_removed() -> None:
    repository_path = _source_root() / "runtime" / "repository.py"
    module = ast.parse(repository_path.read_text(encoding="utf-8"))

    assert "record_operational_event" not in {
        node.name for node in ast.walk(module) if isinstance(node, ast.FunctionDef)
    }

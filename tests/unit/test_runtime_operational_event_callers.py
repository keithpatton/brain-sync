from __future__ import annotations

import ast
from pathlib import Path

import pytest

from brain_sync.runtime.operational_events import (
    CATALOG_EVENT_TYPE_NAMES,
    FIELD_LOCKED_EVENT_FIELDS,
    OperationalEventType,
)

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


def _keyword_map(node: ast.Call) -> dict[str, ast.expr]:
    return {keyword.arg: keyword.value for keyword in node.keywords if keyword.arg is not None}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _static_event_type_name(value: ast.expr) -> str | None:
    if not isinstance(value, ast.Attribute):
        return None
    if not isinstance(value.value, ast.Name) or value.value.id != "OperationalEventType":
        return None
    try:
        return getattr(OperationalEventType, value.attr).value
    except AttributeError:
        return None


def _dict_literal_keys(value: ast.expr) -> set[str] | None:
    if not isinstance(value, ast.Dict):
        return None
    keys: set[str] = set()
    for key in value.keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        keys.add(key.value)
    return keys


def _locked_event_calls() -> list[tuple[str, int, str, ast.Call]]:
    calls: list[tuple[str, int, str, ast.Call]] = []
    locked_event_names = {event_type.value for event_type in FIELD_LOCKED_EVENT_FIELDS}
    for path in _source_root().rglob("*.py"):
        relative_path = path.relative_to(_source_root()).as_posix()
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) not in {"record_brain_operational_event", "_record_regen_event"}:
                continue
            event_type = _static_event_type_name(_keyword_map(node).get("event_type", ast.Constant(None)))
            if event_type is None or event_type not in locked_event_names:
                continue
            calls.append((relative_path, node.lineno, event_type, node))
    return calls


def _string_literals_with_token(path: Path, token: str) -> list[int]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    matches: list[int] = []
    for node in ast.walk(module):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and token in node.value.lower():
            matches.append(getattr(node, "lineno", 1))
    return matches


def test_brain_scoped_operational_event_callers_match_inventory() -> None:
    assert _callers_of("record_brain_operational_event") == _EXPECTED_BRAIN_EVENT_CALLERS


def test_rootless_operational_event_api_is_removed() -> None:
    repository_path = _source_root() / "runtime" / "repository.py"
    module = ast.parse(repository_path.read_text(encoding="utf-8"))

    assert "record_operational_event" not in {
        node.name for node in ast.walk(module) if isinstance(node, ast.FunctionDef)
    }


def test_included_emitters_do_not_use_raw_event_type_literals() -> None:
    for relative_path in sorted(_EXPECTED_BRAIN_EVENT_CALLERS):
        module_path = _source_root() / relative_path
        module = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if not isinstance(node, ast.Call):
                continue
            if not (
                (isinstance(node.func, ast.Name) and node.func.id == "record_brain_operational_event")
                or (isinstance(node.func, ast.Attribute) and node.func.attr == "record_brain_operational_event")
            ):
                continue
            event_type_keyword = next((keyword for keyword in node.keywords if keyword.arg == "event_type"), None)
            assert event_type_keyword is not None, f"{relative_path} is missing an event_type keyword"
            assert not isinstance(event_type_keyword.value, ast.Constant) or not isinstance(
                event_type_keyword.value.value, str
            ), f"{relative_path} uses a raw event_type literal"


def test_operational_event_sql_is_owned_by_runtime_repository() -> None:
    offenders: list[str] = []
    for path in _source_root().rglob("*.py"):
        relative_path = path.relative_to(_source_root()).as_posix()
        if relative_path in {"runtime/repository.py", "runtime/operational_events.py"}:
            continue
        for lineno in _string_literals_with_token(path, "operational_events"):
            offenders.append(f"{relative_path}:{lineno}")

    assert offenders == []


def test_locked_operational_event_emitters_provide_required_fields() -> None:
    covered_event_types: set[str] = set()
    failures: list[str] = []

    for relative_path, lineno, event_type_name, call in _locked_event_calls():
        covered_event_types.add(event_type_name)
        keywords = _keyword_map(call)
        required_fields = FIELD_LOCKED_EVENT_FIELDS[OperationalEventType(event_type_name)]

        for field in sorted(required_fields):
            if field.startswith("details."):
                detail_key = field.split(".", 1)[1]
                details = keywords.get("details")
                if details is None:
                    failures.append(f"{relative_path}:{lineno} {event_type_name} is missing details")
                    continue
                detail_keys = _dict_literal_keys(details)
                if detail_keys is None or detail_key not in detail_keys:
                    failures.append(f"{relative_path}:{lineno} {event_type_name} is missing details.{detail_key}")
                continue

            if field not in keywords:
                failures.append(f"{relative_path}:{lineno} {event_type_name} is missing {field}")

    assert covered_event_types == {event_type.value for event_type in FIELD_LOCKED_EVENT_FIELDS}
    assert failures == []


def test_operational_event_catalog_is_non_empty_and_approved() -> None:
    assert CATALOG_EVENT_TYPE_NAMES

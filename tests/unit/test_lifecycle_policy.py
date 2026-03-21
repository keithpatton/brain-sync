from __future__ import annotations

import ast
import inspect

import pytest

from brain_sync.sync import lifecycle_policy
from brain_sync.sync.lifecycle_policy import (
    can_use_unchanged_fast_path,
    finalization_eligibility,
    stale_blocks_unchanged_fast_path,
)

pytestmark = pytest.mark.unit


def test_stale_blocks_unchanged_fast_path() -> None:
    assert stale_blocks_unchanged_fast_path(knowledge_state="stale") is True
    assert stale_blocks_unchanged_fast_path(knowledge_state="materialized") is False


@pytest.mark.parametrize(
    ("knowledge_state", "has_existing_file", "context_missing", "expected"),
    [
        ("materialized", True, False, True),
        ("materialized", False, False, False),
        ("materialized", True, True, False),
        ("stale", True, False, False),
        ("missing", True, False, False),
        ("awaiting", False, False, False),
    ],
)
def test_can_use_unchanged_fast_path_requires_trusted_materialized_state(
    knowledge_state: str,
    has_existing_file: bool,
    context_missing: bool,
    expected: bool,
) -> None:
    assert (
        can_use_unchanged_fast_path(
            knowledge_state=knowledge_state,
            has_existing_file=has_existing_file,
            context_missing=context_missing,
        )
        is expected
    )


@pytest.mark.parametrize(
    ("kwargs", "expected_reason", "expected_eligible"),
    [
        (
            {
                "manifest_exists": False,
                "knowledge_state": None,
                "has_runtime_row": False,
                "missing_confirmation_count": 0,
                "last_missing_confirmation_session_id": None,
                "current_lifecycle_session_id": "cli:session-1",
                "conflicting_lease": False,
            },
            "not_found",
            False,
        ),
        (
            {
                "manifest_exists": True,
                "knowledge_state": "materialized",
                "has_runtime_row": True,
                "missing_confirmation_count": 2,
                "last_missing_confirmation_session_id": "cli:session-1",
                "current_lifecycle_session_id": "cli:session-1",
                "conflicting_lease": False,
            },
            "not_missing",
            False,
        ),
        (
            {
                "manifest_exists": True,
                "knowledge_state": "missing",
                "has_runtime_row": True,
                "missing_confirmation_count": 2,
                "last_missing_confirmation_session_id": "cli:session-1",
                "current_lifecycle_session_id": "cli:session-1",
                "conflicting_lease": True,
            },
            "lease_conflict",
            False,
        ),
        (
            {
                "manifest_exists": True,
                "knowledge_state": "missing",
                "has_runtime_row": False,
                "missing_confirmation_count": 0,
                "last_missing_confirmation_session_id": None,
                "current_lifecycle_session_id": "cli:session-1",
                "conflicting_lease": False,
            },
            "pending_confirmation",
            False,
        ),
        (
            {
                "manifest_exists": True,
                "knowledge_state": "missing",
                "has_runtime_row": True,
                "missing_confirmation_count": 1,
                "last_missing_confirmation_session_id": "cli:session-1",
                "current_lifecycle_session_id": "cli:session-1",
                "conflicting_lease": False,
            },
            "pending_confirmation",
            False,
        ),
        (
            {
                "manifest_exists": True,
                "knowledge_state": "missing",
                "has_runtime_row": True,
                "missing_confirmation_count": 2,
                "last_missing_confirmation_session_id": "cli:session-older",
                "current_lifecycle_session_id": "cli:session-1",
                "conflicting_lease": False,
            },
            "pending_confirmation",
            False,
        ),
        (
            {
                "manifest_exists": True,
                "knowledge_state": "missing",
                "has_runtime_row": True,
                "missing_confirmation_count": 2,
                "last_missing_confirmation_session_id": "cli:session-1",
                "current_lifecycle_session_id": "cli:session-1",
                "conflicting_lease": False,
            },
            "finalized",
            True,
        ),
    ],
)
def test_finalization_eligibility_reducer(
    kwargs: dict[str, object],
    expected_reason: str,
    expected_eligible: bool,
) -> None:
    result = finalization_eligibility(**kwargs)

    assert result.reason == expected_reason
    assert result.eligible is expected_eligible


def test_lifecycle_policy_module_stays_io_free() -> None:
    tree = ast.parse(inspect.getsource(lifecycle_policy))
    imported_modules: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    assert imported_modules <= {"__future__", "dataclasses"}

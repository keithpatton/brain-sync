from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from brain_sync.application.reconcile import TreeReconcileResult, reconcile_brain
from brain_sync.application.sources import ReconcileEntry, ReconcileResult

pytestmark = pytest.mark.unit


def test_reconcile_brain_skips_knowledge_tree_when_not_requested(tmp_path):
    source_result = ReconcileResult(updated=[], not_found=[], unchanged=2)

    with (
        patch(
            "brain_sync.application.reconcile.ensure_lifecycle_session",
            return_value="cli:session-1",
        ) as mock_session,
        patch("brain_sync.application.reconcile.reconcile_sources", return_value=source_result) as mock_sources,
        patch("brain_sync.application.reconcile.reconcile_knowledge_tree") as mock_tree,
    ):
        report = reconcile_brain(tmp_path)

    mock_session.assert_called_once_with(tmp_path, owner_kind="cli")
    mock_sources.assert_called_once_with(root=tmp_path, lifecycle_session_id="cli:session-1")
    mock_tree.assert_not_called()
    assert report.unchanged == 2
    assert report.orphans_cleaned == []
    assert report.has_changes is False


def test_reconcile_brain_combines_source_and_tree_reporting(tmp_path):
    source_result = ReconcileResult(
        updated=[ReconcileEntry(canonical_id="confluence:123", old_path="old", new_path="new")],
        not_found=["confluence:999"],
        unchanged=1,
        orphan_rows_pruned=2,
    )
    tree_result = TreeReconcileResult(
        orphans_cleaned=["teams/alpha"],
        content_changed=["teams/beta"],
        enqueued_paths=["teams/gamma"],
    )

    with (
        patch(
            "brain_sync.application.reconcile.ensure_lifecycle_session",
            return_value="cli:session-1",
        ),
        patch("brain_sync.application.reconcile.reconcile_sources", return_value=source_result),
        patch("brain_sync.application.reconcile.reconcile_knowledge_tree", return_value=tree_result),
    ):
        report = reconcile_brain(tmp_path, include_knowledge_tree=True)

    assert [entry.canonical_id for entry in report.updated] == ["confluence:123"]
    assert report.not_found == ["confluence:999"]
    assert report.orphan_rows_pruned == 2
    assert report.orphans_cleaned == ["teams/alpha"]
    assert report.content_changed == ["teams/beta"]
    assert report.enqueued_paths == ["teams/gamma"]
    assert report.has_source_changes is True
    assert report.has_tree_changes is True
    assert report.has_changes is True


def test_reconcile_brain_uses_explicit_lifecycle_session_without_recreating_one(tmp_path):
    source_result = ReconcileResult(updated=[], not_found=[], unchanged=1)

    with (
        patch("brain_sync.application.reconcile.ensure_lifecycle_session") as mock_session,
        patch("brain_sync.application.reconcile.reconcile_sources", return_value=source_result) as mock_sources,
    ):
        report = reconcile_brain(tmp_path, lifecycle_session_id="mcp:session-1", lifecycle_session_owner_kind="mcp")

    mock_session.assert_not_called()
    mock_sources.assert_called_once_with(root=tmp_path, lifecycle_session_id="mcp:session-1")
    assert report.unchanged == 1


def test_build_status_summary_returns_typed_usage_summary(tmp_path):
    raw_usage = {
        "total_input": 100,
        "total_output": 40,
        "total_tokens": 140,
        "total_invocations": 3,
        "by_operation": [{"operation": "regen", "input_tokens": 100, "output_tokens": 40, "total_tokens": 140}],
        "by_day": [{"day": "2026-03-18", "input_tokens": 100, "output_tokens": 40, "total_tokens": 140}],
    }
    insight_states = [
        SimpleNamespace(regen_status="current"),
        SimpleNamespace(regen_status="current"),
        SimpleNamespace(regen_status="needs_regen"),
    ]

    with (
        patch("brain_sync.application.status.list_sources", return_value=["a", "b"]),
        patch("brain_sync.application.status.load_all_insight_states", return_value=insight_states),
        patch("brain_sync.application.status.load_usage_summary", return_value=raw_usage),
        patch("brain_sync.application.status.active_brain_root", return_value=tmp_path),
    ):
        from brain_sync.application.status import build_status_summary

        summary = build_status_summary(tmp_path, usage_days=14)

    assert summary.source_count == 2
    assert summary.insight_states_by_status == {"current": 2, "needs_regen": 1}
    assert summary.usage.days == 14
    assert summary.usage.total_invocations == 3
    assert summary.usage.total_tokens == 140
    assert summary.usage.by_operation[0]["operation"] == "regen"
    assert summary.usage_available is True


def test_build_status_summary_marks_usage_unavailable_for_non_active_root(tmp_path):
    raw_usage = {
        "total_input": 500,
        "total_output": 100,
        "total_tokens": 600,
        "total_invocations": 4,
        "by_operation": [{"operation": "regen", "input_tokens": 500, "output_tokens": 100, "total_tokens": 600}],
        "by_day": [{"day": "2026-03-18", "input_tokens": 500, "output_tokens": 100, "total_tokens": 600}],
    }

    with (
        patch("brain_sync.application.status.list_sources", return_value=[]),
        patch("brain_sync.application.status.load_all_insight_states", return_value=[]),
        patch("brain_sync.application.status.load_usage_summary", return_value=raw_usage),
        patch("brain_sync.application.status.active_brain_root", return_value=tmp_path / "active"),
    ):
        from brain_sync.application.status import build_status_summary

        summary = build_status_summary(tmp_path / "other", usage_days=7)

    assert summary.usage_available is False
    assert summary.usage.total_invocations == 0
    assert summary.usage.by_operation == []


def test_get_usage_summary_accepts_legacy_root_argument(tmp_path):
    raw_usage = {
        "total_input": 10,
        "total_output": 5,
        "total_tokens": 15,
        "total_invocations": 1,
        "by_operation": [{"operation": "regen", "input_tokens": 10, "output_tokens": 5, "total_tokens": 15}],
        "by_day": [{"day": "2026-03-18", "input_tokens": 10, "output_tokens": 5, "total_tokens": 15}],
    }

    with (
        patch("brain_sync.application.status.load_usage_summary", return_value=raw_usage),
        patch("brain_sync.application.status.active_brain_root", return_value=tmp_path),
    ):
        from brain_sync.application.status import get_usage_summary

        summary = get_usage_summary(tmp_path, days=7)

    assert summary.total_invocations == 1
    assert summary.total_tokens == 15

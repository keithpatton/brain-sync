from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from brain_sync.application.local_files import LocalFileAddResult
from brain_sync.application.placement import PlacementCandidateView, PlacementSuggestionResult
from brain_sync.application.reconcile import ReconcileReport
from brain_sync.application.sources import AddResult, ReconcileEntry, UnsupportedSourceUrlError

pytestmark = pytest.mark.unit


def test_handle_add_uses_untitled_fallback_when_title_resolution_fails(tmp_path) -> None:
    from brain_sync.interfaces.cli.handlers import handle_add

    args = SimpleNamespace(
        source="https://docs.google.com/document/d/abc123/edit",
        target_path=None,
        subtree=None,
        dry_run=False,
        fetch_children=False,
        sync_attachments=False,
        child_path=None,
        root=tmp_path,
    )

    placement_result = PlacementSuggestionResult(
        document_title="Untitled",
        suggested_filename="gabc123-untitled.md",
        candidates=[PlacementCandidateView(path="area", score=10, reasoning="Matched: untitled.")],
        query_terms=["untitled"],
        total_areas=1,
    )
    add_result = AddResult(
        canonical_id="gdoc:abc123",
        source_url=args.source,
        target_path="area",
        fetch_children=False,
        sync_attachments=False,
    )

    def _placement_stub(*_args, **kwargs):
        assert kwargs["fallback_title"] == "Untitled"
        return placement_result, object()

    with (
        patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=tmp_path),
        patch(
            "brain_sync.application.sources.check_source_exists",
            return_value=None,
        ),
        patch(
            "brain_sync.application.placement.suggest_document_placement",
            side_effect=_placement_stub,
        ),
        patch(
            "brain_sync.application.sources.add_source",
            return_value=add_result,
        ) as mock_add,
        patch("builtins.input", return_value="1"),
    ):
        handle_add(args)

    mock_add.assert_called_once()
    assert mock_add.call_args.kwargs["target_path"] == "area"


def test_handle_add_unsupported_http_url_is_handled_cleanly(tmp_path) -> None:
    from brain_sync.interfaces.cli.handlers import handle_add

    args = SimpleNamespace(
        source="https://unsupported.example.com/doc/123",
        target_path="area",
        subtree=None,
        dry_run=False,
        fetch_children=False,
        sync_attachments=False,
        child_path=None,
        root=tmp_path,
    )

    with (
        patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=tmp_path),
        patch(
            "brain_sync.application.sources.check_source_exists",
            side_effect=UnsupportedSourceUrlError(args.source),
        ),
        patch("brain_sync.application.sources.add_source") as mock_add,
    ):
        handle_add(args)

    mock_add.assert_not_called()


def test_handle_add_auto_detects_subtree_from_cwd(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from brain_sync.interfaces.cli.handlers import handle_add

    knowledge_subtree = tmp_path / "knowledge" / "teams" / "platform"
    knowledge_subtree.mkdir(parents=True)
    monkeypatch.chdir(knowledge_subtree)

    args = SimpleNamespace(
        source="https://docs.google.com/document/d/abc123/edit",
        target_path=None,
        subtree=None,
        dry_run=False,
        fetch_children=False,
        sync_attachments=False,
        child_path=None,
        root=tmp_path,
    )

    placement_result = PlacementSuggestionResult(
        document_title="Doc",
        suggested_filename="gabc123-doc.md",
        candidates=[PlacementCandidateView(path="teams/platform", score=10, reasoning="Matched subtree.")],
        query_terms=["doc"],
        total_areas=1,
    )
    add_result = AddResult(
        canonical_id="gdoc:abc123",
        source_url=args.source,
        target_path="teams/platform",
        fetch_children=False,
        sync_attachments=False,
    )

    def _placement_stub(*_args, **kwargs):
        assert kwargs["subtree"] == "teams/platform"
        return placement_result, object()

    with (
        patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=tmp_path),
        patch("brain_sync.application.sources.check_source_exists", return_value=None),
        patch("brain_sync.application.placement.suggest_document_placement", side_effect=_placement_stub),
        patch("brain_sync.application.sources.add_source", return_value=add_result),
        patch("builtins.input", return_value="1"),
    ):
        handle_add(args)


def test_handle_add_file_auto_detects_subtree_from_cwd(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from brain_sync.interfaces.cli.handlers import handle_add_file

    knowledge_subtree = tmp_path / "knowledge" / "teams" / "platform"
    knowledge_subtree.mkdir(parents=True)
    monkeypatch.chdir(knowledge_subtree)

    source_file = tmp_path / "notes.md"
    source_file.write_text("# Notes\n", encoding="utf-8")

    args = SimpleNamespace(
        file=str(source_file),
        target_path=None,
        subtree=None,
        dry_run=False,
        move=False,
        root=tmp_path,
    )

    placement_result = PlacementSuggestionResult(
        document_title="notes",
        suggested_filename=None,
        candidates=[PlacementCandidateView(path="teams/platform", score=10, reasoning="Matched subtree.")],
        query_terms=["notes"],
        total_areas=1,
    )

    def _placement_stub(*_args, **kwargs):
        assert kwargs["subtree"] == "teams/platform"
        return placement_result, object()

    with (
        patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=tmp_path),
        patch("brain_sync.application.placement.extract_file_excerpt", return_value="# Notes"),
        patch("brain_sync.application.placement.suggest_document_placement", side_effect=_placement_stub),
        patch(
            "brain_sync.application.local_files.add_local_file",
            return_value=LocalFileAddResult(action="copied", path="knowledge/teams/platform/notes.md"),
        ) as mock_add,
        patch("builtins.input", return_value="1"),
    ):
        handle_add_file(args)

    mock_add.assert_called_once()
    assert mock_add.call_args.kwargs["target_path"].replace("\\", "/") == "teams/platform"


def test_handle_reconcile_logs_noop_when_nothing_changed(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    from brain_sync.interfaces.cli.handlers import handle_reconcile

    args = SimpleNamespace(root=tmp_path)

    with (
        patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=tmp_path),
        patch("brain_sync.application.reconcile.reconcile_brain", return_value=ReconcileReport(unchanged=5)),
        caplog.at_level(logging.INFO),
    ):
        handle_reconcile(args)

    assert "All sources are at their expected paths. Nothing to reconcile." in caplog.text


def test_handle_reconcile_logs_changed_summary(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    from brain_sync.interfaces.cli.handlers import handle_reconcile

    args = SimpleNamespace(root=tmp_path)
    report = ReconcileReport(
        updated=[ReconcileEntry(canonical_id="confluence:12345", old_path="old-team", new_path="new-team")],
        not_found=["confluence:99999"],
        orphans_cleaned=["teams/platform"],
        content_changed=["teams/ops"],
        enqueued_paths=["teams/new"],
        has_source_changes=True,
        has_tree_changes=True,
        has_changes=True,
    )

    with (
        patch("brain_sync.interfaces.cli.handlers._resolve_root_or_exit", return_value=tmp_path),
        patch("brain_sync.application.reconcile.reconcile_brain", return_value=report),
        caplog.at_level(logging.INFO),
    ):
        handle_reconcile(args)

    assert "Updated confluence:12345: knowledge/old-team -> knowledge/new-team" in caplog.text
    assert "1 source(s) could not be found on disk:" in caplog.text
    assert "Cleaned 1 orphan insight state(s)." in caplog.text
    assert "Detected offline changes in 1 tracked knowledge area(s)." in caplog.text
    assert "Discovered 1 new knowledge area(s) needing regen." in caplog.text

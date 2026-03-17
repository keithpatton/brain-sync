from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from brain_sync.application.placement import PlacementCandidateView, PlacementSuggestionResult
from brain_sync.application.sources import AddResult, UnsupportedSourceUrlError

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

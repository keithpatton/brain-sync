"""Tests for the MCP server tool handlers.

Tests call tool handler functions directly — no stdio transport needed.
All underlying commands/regen functions are mocked.
"""
from __future__ import annotations

from dataclasses import asdict
from unittest.mock import AsyncMock, patch

import pytest

from brain_sync.commands import (
    AddResult,
    MoveResult,
    RemoveResult,
    SourceAlreadyExistsError,
    SourceInfo,
    SourceNotFoundError,
)
from brain_sync.sources import UnsupportedSourceError


# ---------------------------------------------------------------------------
# Fixtures: sample data
# ---------------------------------------------------------------------------

SAMPLE_SOURCE = SourceInfo(
    canonical_id="confluence:12345",
    source_url="https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test",
    target_path="initiatives/test",
    last_checked_utc="2026-03-08T00:00:00+00:00",
    last_changed_utc="2026-03-07T12:00:00+00:00",
    current_interval_secs=1800,
    include_links=True,
    include_children=False,
    include_attachments=False,
)

SAMPLE_ADD_RESULT = AddResult(
    canonical_id="confluence:12345",
    source_url="https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test",
    target_path="initiatives/test",
    include_links=False,
    include_children=False,
    include_attachments=False,
)

SAMPLE_REMOVE_RESULT = RemoveResult(
    canonical_id="confluence:12345",
    source_url="https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test",
    target_path="initiatives/test",
    files_deleted=False,
)

SAMPLE_MOVE_RESULT = MoveResult(
    canonical_id="confluence:12345",
    old_path="initiatives/test",
    new_path="initiatives/moved",
    files_moved=True,
)


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestBrainSyncList:
    @patch("brain_sync.mcp.list_sources", return_value=[])
    def test_list_empty(self, mock_list):
        from brain_sync.mcp import brain_sync_list

        result = brain_sync_list()
        assert result == {"status": "ok", "sources": [], "count": 0}
        mock_list.assert_called_once()

    @patch("brain_sync.mcp.list_sources", return_value=[SAMPLE_SOURCE])
    def test_list_with_sources(self, mock_list):
        from brain_sync.mcp import brain_sync_list

        result = brain_sync_list()
        assert result["status"] == "ok"
        assert result["count"] == 1
        assert result["sources"] == [asdict(SAMPLE_SOURCE)]

    @patch("brain_sync.mcp.list_sources", return_value=[SAMPLE_SOURCE])
    def test_list_filter(self, mock_list):
        from brain_sync.mcp import brain_sync_list

        result = brain_sync_list(filter_path="initiatives")
        assert result["status"] == "ok"
        mock_list.assert_called_once()
        call_kwargs = mock_list.call_args
        assert call_kwargs.kwargs.get("filter_path") == "initiatives"


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------

class TestBrainSyncAdd:
    @patch("brain_sync.mcp.add_source", return_value=SAMPLE_ADD_RESULT)
    def test_add_success(self, mock_add):
        from brain_sync.mcp import brain_sync_add

        result = brain_sync_add(
            url="https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test",
            target_path="initiatives/test",
        )
        assert result["status"] == "ok"
        assert result["canonical_id"] == "confluence:12345"
        mock_add.assert_called_once()

    @patch(
        "brain_sync.mcp.add_source",
        side_effect=SourceAlreadyExistsError("confluence:12345", "https://example.com", "initiatives/test"),
    )
    def test_add_duplicate(self, mock_add):
        from brain_sync.mcp import brain_sync_add

        result = brain_sync_add(
            url="https://example.com",
            target_path="initiatives/test",
        )
        assert result["status"] == "error"
        assert result["error"] == "source_already_exists"
        assert result["canonical_id"] == "confluence:12345"

    @patch(
        "brain_sync.mcp.add_source",
        side_effect=UnsupportedSourceError("https://bad-url.example.com"),
    )
    def test_add_invalid_url(self, mock_add):
        from brain_sync.mcp import brain_sync_add

        result = brain_sync_add(
            url="https://bad-url.example.com",
            target_path="test",
        )
        assert result["status"] == "error"
        assert result["error"] == "unsupported_url"
        assert result["url"] == "https://bad-url.example.com"


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------

class TestBrainSyncRemove:
    @patch("brain_sync.mcp.remove_source", return_value=SAMPLE_REMOVE_RESULT)
    def test_remove_success(self, mock_remove):
        from brain_sync.mcp import brain_sync_remove

        result = brain_sync_remove(source="confluence:12345")
        assert result["status"] == "ok"
        assert result["canonical_id"] == "confluence:12345"

    @patch(
        "brain_sync.mcp.remove_source",
        side_effect=SourceNotFoundError("confluence:99999"),
    )
    def test_remove_not_found(self, mock_remove):
        from brain_sync.mcp import brain_sync_remove

        result = brain_sync_remove(source="confluence:99999")
        assert result["status"] == "error"
        assert result["error"] == "source_not_found"
        assert result["source"] == "confluence:99999"


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------

class TestBrainSyncMove:
    @patch("brain_sync.mcp.move_source", return_value=SAMPLE_MOVE_RESULT)
    def test_move_success(self, mock_move):
        from brain_sync.mcp import brain_sync_move

        result = brain_sync_move(source="confluence:12345", to_path="initiatives/moved")
        assert result["status"] == "ok"
        assert result["new_path"] == "initiatives/moved"
        assert result["files_moved"] is True

    @patch(
        "brain_sync.mcp.move_source",
        side_effect=SourceNotFoundError("confluence:99999"),
    )
    def test_move_not_found(self, mock_move):
        from brain_sync.mcp import brain_sync_move

        result = brain_sync_move(source="confluence:99999", to_path="x")
        assert result["status"] == "error"
        assert result["error"] == "source_not_found"


# ---------------------------------------------------------------------------
# Regen
# ---------------------------------------------------------------------------

class TestBrainSyncRegen:
    @pytest.mark.asyncio
    async def test_regen_path(self):
        with patch("brain_sync.mcp.regen_path", new_callable=AsyncMock, return_value=3):
            from brain_sync.mcp import brain_sync_regen

            result = await brain_sync_regen(path="initiatives/test")
            assert result["status"] == "ok"
            assert result["summaries_regenerated"] == 3
            assert result["path"] == "initiatives/test"

    @pytest.mark.asyncio
    async def test_regen_all(self):
        with patch("brain_sync.mcp.regen_all", new_callable=AsyncMock, return_value=7):
            from brain_sync.mcp import brain_sync_regen

            result = await brain_sync_regen()
            assert result["status"] == "ok"
            assert result["summaries_regenerated"] == 7
            assert result["path"] == "all"

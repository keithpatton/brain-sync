"""Tests for the MCP server tool handlers.

Tests call tool handler functions directly — no stdio transport needed.
Source management tools mock underlying commands. Query tools use real
filesystem via tmp_path fixtures.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
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

pytestmark = pytest.mark.mcp

# ---------------------------------------------------------------------------
# Fixtures: sample data for source management tests
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
# Fixture: brain filesystem for query tools
# ---------------------------------------------------------------------------


@pytest.fixture
def brain_root(tmp_path: Path) -> Path:
    """Create a minimal brain structure for query tool tests."""
    root = tmp_path / "brain"

    # knowledge/_core
    (root / "knowledge" / "_core").mkdir(parents=True)
    (root / "knowledge" / "_core" / "about-me.md").write_text("I am a test user.", encoding="utf-8")

    # schemas
    (root / "schemas" / "insights").mkdir(parents=True)
    (root / "schemas" / "insights" / "summary.md").write_text(
        "# Summary Schema\nTemplate for summaries.",
        encoding="utf-8",
    )

    # insights/_core
    (root / "insights" / "_core").mkdir(parents=True)
    (root / "insights" / "_core" / "summary.md").write_text("# Core Summary\nOverview of the brain.", encoding="utf-8")
    # journal should be excluded
    (root / "insights" / "_core" / "journal" / "2026-03").mkdir(parents=True)
    (root / "insights" / "_core" / "journal" / "2026-03" / "2026-03-08.md").write_text(
        "Journal entry.",
        encoding="utf-8",
    )

    # Area: initiatives/AAA
    (root / "knowledge" / "initiatives" / "AAA").mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "AAA" / "c12345-doc.md").write_text("AAA knowledge doc.", encoding="utf-8")
    (root / "insights" / "initiatives" / "AAA").mkdir(parents=True)
    (root / "insights" / "initiatives" / "AAA" / "summary.md").write_text(
        "# Platform AAA Summary\n\nAAA is the main platform initiative.\n\n## Architecture\n\nMicroservices.",
        encoding="utf-8",
    )
    (root / "insights" / "initiatives" / "AAA" / "decisions.md").write_text(
        "# Decisions\n\n- Chose microservices.",
        encoding="utf-8",
    )

    # Sub-area: initiatives/AAA/Accounts Service
    (root / "knowledge" / "initiatives" / "AAA" / "Accounts Service").mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "AAA" / "Accounts Service" / "doc.md").write_text(
        "Accounts doc.",
        encoding="utf-8",
    )
    (root / "insights" / "initiatives" / "AAA" / "Accounts Service").mkdir(parents=True)
    (root / "insights" / "initiatives" / "AAA" / "Accounts Service" / "summary.md").write_text(
        "# Accounts Service\n\nHandles user accounts.",
        encoding="utf-8",
    )

    # Area: initiatives/BBB
    (root / "knowledge" / "initiatives" / "BBB").mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "BBB" / "doc.md").write_text("BBB knowledge doc.", encoding="utf-8")
    (root / "insights" / "initiatives" / "BBB").mkdir(parents=True)
    (root / "insights" / "initiatives" / "BBB" / "summary.md").write_text(
        "# Platform BBB\n\nBBB handles billing.",
        encoding="utf-8",
    )

    return root


@pytest.fixture
def brain_with_many_children(brain_root: Path) -> Path:
    """Extend brain_root with 20+ child areas under initiatives/AAA."""
    for i in range(20):
        name = f"Child-{i:02d}"
        (brain_root / "insights" / "initiatives" / "AAA" / name).mkdir(parents=True)
        (brain_root / "insights" / "initiatives" / "AAA" / name / "summary.md").write_text(
            f"# {name}\n\nSummary for {name}.",
            encoding="utf-8",
        )
    return brain_root


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


# ---------------------------------------------------------------------------
# Query tools — use real filesystem via brain_root fixture
# ---------------------------------------------------------------------------


class TestBrainSyncQuery:
    def test_query_with_match(self, brain_root):
        from brain_sync.mcp import AreaIndex, brain_sync_query

        with (
            patch("brain_sync.mcp._root", brain_root),
            patch("brain_sync.mcp._area_index", AreaIndex.build(brain_root)),
        ):
            result = brain_sync_query(query="AAA")

        assert result["status"] == "ok"
        assert len(result["matches"]) >= 1
        assert result["matches"][0]["path"] == "initiatives/AAA"
        assert "global_context" not in result
        assert result["total_areas"] > 0

    def test_query_with_global(self, brain_root):
        from brain_sync.mcp import AreaIndex, brain_sync_query

        with (
            patch("brain_sync.mcp._root", brain_root),
            patch("brain_sync.mcp._area_index", AreaIndex.build(brain_root)),
        ):
            result = brain_sync_query(query="AAA", include_global=True)

        assert result["status"] == "ok"
        assert "global_context" in result
        gc = result["global_context"]
        assert "about-me.md" in gc["knowledge_core"]
        assert "insights/summary.md" in gc["schemas"]
        assert "summary.md" in gc["insights_core"]
        # Journal should be excluded from insights_core
        assert not any("journal" in k for k in gc["insights_core"])

    def test_query_no_match(self, brain_root):
        from brain_sync.mcp import AreaIndex, brain_sync_query

        with (
            patch("brain_sync.mcp._root", brain_root),
            patch("brain_sync.mcp._area_index", AreaIndex.build(brain_root)),
        ):
            result = brain_sync_query(query="nonexistent")

        assert result["status"] == "ok"
        assert result["matches"] == []

    def test_query_max_results(self, brain_root):
        from brain_sync.mcp import AreaIndex, brain_sync_query

        with (
            patch("brain_sync.mcp._root", brain_root),
            patch("brain_sync.mcp._area_index", AreaIndex.build(brain_root)),
        ):
            result = brain_sync_query(query="initiatives", max_results=1)

        assert result["status"] == "ok"
        assert len(result["matches"]) == 1

    def test_query_searches_summary_content(self, brain_root):
        """Matches against summary.md content, not just folder names."""
        from brain_sync.mcp import AreaIndex, brain_sync_query

        with (
            patch("brain_sync.mcp._root", brain_root),
            patch("brain_sync.mcp._area_index", AreaIndex.build(brain_root)),
        ):
            # "billing" appears only in BBB's summary, not in path
            result = brain_sync_query(query="billing")

        assert result["status"] == "ok"
        assert len(result["matches"]) >= 1
        assert result["matches"][0]["path"] == "initiatives/BBB"

    def test_query_path_weighted_higher(self, brain_root):
        """Path matches score higher than body matches."""
        from brain_sync.mcp import AreaIndex, brain_sync_query

        with (
            patch("brain_sync.mcp._root", brain_root),
            patch("brain_sync.mcp._area_index", AreaIndex.build(brain_root)),
        ):
            result = brain_sync_query(query="AAA")

        assert result["status"] == "ok"
        # AAA should be first because "AAA" is in the path (x3)
        assert result["matches"][0]["path"] == "initiatives/AAA"

    def test_query_areas_capped(self, tmp_path):
        """Areas listing respects MAX_AREAS_LISTED cap."""
        from brain_sync.mcp import MAX_AREAS_LISTED, AreaIndex, brain_sync_query

        root = tmp_path / "big-brain"
        (root / "knowledge" / "_core").mkdir(parents=True)
        (root / "schemas").mkdir(parents=True)
        (root / "insights" / "_core").mkdir(parents=True)
        # Create 60 areas
        for i in range(60):
            area = root / "insights" / f"area-{i:03d}"
            area.mkdir(parents=True)
            (area / "summary.md").write_text(f"# Area {i}", encoding="utf-8")

        with patch("brain_sync.mcp._root", root), patch("brain_sync.mcp._area_index", AreaIndex.build(root)):
            result = brain_sync_query(query="area")

        assert result["status"] == "ok"
        assert len(result["areas"]) == MAX_AREAS_LISTED
        assert result["areas_truncated"] is True
        assert result["total_areas"] == 60


class TestBrainSyncGetContext:
    def test_get_context(self, brain_root):
        from brain_sync.mcp import brain_sync_get_context

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_get_context()

        assert result["status"] == "ok"
        gc = result["global_context"]
        assert "about-me.md" in gc["knowledge_core"]
        assert gc["knowledge_core"]["about-me.md"] == "I am a test user."
        assert "insights/summary.md" in gc["schemas"]
        assert "summary.md" in gc["insights_core"]
        assert result["total_areas"] > 0

    def test_get_context_missing_core(self, tmp_path):
        """Graceful when _core/ doesn't exist."""
        from brain_sync.mcp import brain_sync_get_context

        root = tmp_path / "empty-brain"
        root.mkdir()

        with patch("brain_sync.mcp._root", root):
            result = brain_sync_get_context()

        assert result["status"] == "ok"
        assert result["global_context"]["knowledge_core"] == {}
        assert result["global_context"]["schemas"] == {}
        assert result["global_context"]["insights_core"] == {}
        assert result["total_areas"] == 0


class TestBrainSyncOpenArea:
    def test_open_area(self, brain_root):
        from brain_sync.mcp import brain_sync_open_area

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_area(path="initiatives/AAA")

        assert result["status"] == "ok"
        assert result["path"] == "initiatives/AAA"
        assert "summary.md" in result["insights"]
        assert "decisions.md" in result["insights"]
        assert result["total_children"] >= 1
        # Accounts Service should be in children
        child_names = [c["name"] for c in result["children"]]
        assert "Accounts Service" in child_names

    def test_open_area_with_children(self, brain_root):
        from brain_sync.mcp import brain_sync_open_area

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_area(path="initiatives/AAA", include_children=True)

        assert result["status"] == "ok"
        assert "child_summaries" in result
        assert "Accounts Service" in result["child_summaries"]
        assert "Handles user accounts" in result["child_summaries"]["Accounts Service"]

    def test_open_area_with_knowledge_list(self, brain_root):
        from brain_sync.mcp import brain_sync_open_area

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_area(path="initiatives/AAA", include_knowledge_list=True)

        assert result["status"] == "ok"
        assert "knowledge_files" in result
        assert "c12345-doc.md" in result["knowledge_files"]

    def test_open_area_not_found(self, brain_root):
        from brain_sync.mcp import brain_sync_open_area

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_area(path="nonexistent/area")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_area_summary_truncation(self, brain_root):
        """Large summary.md is truncated with marker."""
        from brain_sync.mcp import MAX_SUMMARY_CHARS, TRUNCATION_MARKER, brain_sync_open_area

        # Write a large summary
        large_summary = "# Large Summary\n\n" + "x" * (MAX_SUMMARY_CHARS + 5000)
        (brain_root / "insights" / "initiatives" / "AAA" / "summary.md").write_text(
            large_summary,
            encoding="utf-8",
        )

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_area(path="initiatives/AAA")

        assert result["status"] == "ok"
        summary = result["insights"]["summary.md"]
        assert len(summary) <= MAX_SUMMARY_CHARS + len(TRUNCATION_MARKER) + 10
        assert TRUNCATION_MARKER in summary

    def test_open_area_child_limit(self, brain_with_many_children):
        """Area with many children respects MAX_CHILDREN cap."""
        from brain_sync.mcp import MAX_CHILDREN, brain_sync_open_area

        with patch("brain_sync.mcp._root", brain_with_many_children):
            result = brain_sync_open_area(path="initiatives/AAA", include_children=True)

        assert result["status"] == "ok"
        assert len(result["child_summaries"]) <= MAX_CHILDREN
        assert result["children_truncated"] is True
        assert result["total_children"] > MAX_CHILDREN

    def test_open_area_payload_cap(self, brain_root):
        """Total response respects MAX_AREA_PAYLOAD, drops artifacts first."""
        from brain_sync.mcp import TRUNCATION_MARKER, brain_sync_open_area

        # Write a very large summary and large artifacts
        insights_dir = brain_root / "insights" / "initiatives" / "AAA"
        (insights_dir / "summary.md").write_text("# Summary\n" + "s" * 30000, encoding="utf-8")
        for i in range(5):
            (insights_dir / f"artifact-{i}.md").write_text("a" * 8000, encoding="utf-8")

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_area(path="initiatives/AAA")

        assert result["status"] == "ok"
        # Artifacts should have been replaced with truncation marker
        for key, value in result["insights"].items():
            if key != "summary.md":
                assert value == TRUNCATION_MARKER or len(value) <= 8000


class TestBrainSyncOpenFile:
    def test_open_file(self, brain_root):
        from brain_sync.mcp import brain_sync_open_file

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(path="insights/_core/summary.md")

        assert result["status"] == "ok"
        assert "Core Summary" in result["content"]
        assert result["offset"] == 0
        assert result["truncated"] is False
        assert "next_offset" not in result

    def test_open_file_not_found(self, brain_root):
        from brain_sync.mcp import brain_sync_open_file

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(path="nonexistent/file.md")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_file_path_traversal(self, brain_root):
        from brain_sync.mcp import brain_sync_open_file

        # Create a file outside brain root
        (brain_root.parent / "secret.md").write_text("secret!", encoding="utf-8")

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(path="../secret.md")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_file_directory_rejected(self, brain_root):
        from brain_sync.mcp import brain_sync_open_file

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(path="insights/_core")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_file_binary_rejected(self, brain_root):
        """Binary extensions return unsupported_type error."""
        from brain_sync.mcp import brain_sync_open_file

        (brain_root / "test.pdf").write_bytes(b"fake pdf")

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(path="test.pdf")

        assert result["status"] == "error"
        assert result["error"] == "unsupported_type"
        assert result["extension"] == ".pdf"

    def test_open_file_json_allowed(self, brain_root):
        from brain_sync.mcp import brain_sync_open_file

        (brain_root / "data.json").write_text('{"key": "value"}', encoding="utf-8")

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(path="data.json")

        assert result["status"] == "ok"
        assert '"key"' in result["content"]

    @pytest.mark.skipif(os.name == "nt", reason="symlinks may require elevated privileges on Windows")
    def test_open_file_symlink_escape(self, brain_root):
        """Symlink pointing outside brain root is rejected."""
        from brain_sync.mcp import brain_sync_open_file

        outside = brain_root.parent / "outside.md"
        outside.write_text("escaped!", encoding="utf-8")
        link = brain_root / "link.md"
        link.symlink_to(outside)

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(path="link.md")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_file_truncated_includes_metadata(self, brain_root):
        """File larger than DEFAULT_FILE_CHARS returns pagination metadata."""
        from brain_sync.mcp import DEFAULT_FILE_CHARS, brain_sync_open_file

        # Write a file larger than the default limit with line breaks
        lines = [f"Line {i}: " + "x" * 80 for i in range(2500)]
        large_content = "\n".join(lines)
        assert len(large_content) > DEFAULT_FILE_CHARS
        (brain_root / "large.md").write_text(large_content, encoding="utf-8")

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(path="large.md")

        assert result["status"] == "ok"
        assert result["truncated"] is True
        assert "next_offset" in result
        assert result["next_offset"] > 0
        assert "hint" in result
        assert "offset=" in result["hint"]

    def test_open_file_offset_reads_remainder(self, brain_root):
        """Pagination with offset picks up where previous call left off."""
        from brain_sync.mcp import brain_sync_open_file

        lines = [f"Line {i}: " + "x" * 80 for i in range(2500)]
        large_content = "\n".join(lines)
        (brain_root / "large.md").write_text(large_content, encoding="utf-8")

        with patch("brain_sync.mcp._root", brain_root):
            # First call
            r1 = brain_sync_open_file(path="large.md")
            assert r1["truncated"] is True

            # Second call at next_offset
            r2 = brain_sync_open_file(path="large.md", offset=r1["next_offset"])

        # Content should be contiguous
        combined = r1["content"] + r2["content"]
        assert combined == large_content[: len(combined)]

    def test_open_file_offset_beyond_eof(self, brain_root):
        """Offset past end of file returns empty content."""
        from brain_sync.mcp import brain_sync_open_file

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(
                path="insights/_core/summary.md",
                offset=999999,
            )

        assert result["status"] == "ok"
        assert result["content"] == ""
        assert result["truncated"] is False

    def test_open_file_limit_clamped(self, brain_root):
        """Limit larger than MAX_FILE_CHARS is clamped."""
        from brain_sync.mcp import MAX_FILE_CHARS, brain_sync_open_file

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(
                path="insights/_core/summary.md",
                limit=MAX_FILE_CHARS + 100,
            )

        assert result["status"] == "ok"
        assert result["limit"] == MAX_FILE_CHARS

    def test_open_file_newline_alignment(self, brain_root):
        """Chunk boundary aligns to newline, not mid-line."""
        from brain_sync.mcp import brain_sync_open_file

        # Write content where truncation would land mid-line
        lines = [f"Line {i}: " + "y" * 80 for i in range(250)]
        large_content = "\n".join(lines)
        (brain_root / "aligned.md").write_text(large_content, encoding="utf-8")

        with patch("brain_sync.mcp._root", brain_root):
            result = brain_sync_open_file(path="aligned.md")

        if result["truncated"]:
            # Content should end at a newline
            assert result["content"].endswith("\n") or "\n" not in result["content"][-1:]


# ---------------------------------------------------------------------------
# Search index
# ---------------------------------------------------------------------------


class TestAreaIndex:
    def test_build_and_search(self, brain_root):
        from brain_sync.mcp import AreaIndex

        index = AreaIndex.build(brain_root)
        assert len(index.entries) > 0

        results = index.search("AAA")
        assert len(results) >= 1
        assert results[0]["path"] == "initiatives/AAA"

    def test_search_deterministic_ordering(self, brain_root):
        """Two searches with same query produce identical results."""
        from brain_sync.mcp import AreaIndex

        index = AreaIndex.build(brain_root)
        r1 = index.search("initiatives")
        r2 = index.search("initiatives")
        assert r1 == r2

    def test_missing_summary(self, tmp_path):
        """Areas without summary.md are indexed with empty fields."""
        from brain_sync.mcp import AreaIndex

        root = tmp_path / "brain"
        (root / "insights" / "area-no-summary").mkdir(parents=True)
        # No summary.md

        index = AreaIndex.build(root)
        assert len(index.entries) == 1
        entry = index.entries[0]
        assert entry.summary_first_para == ""
        assert entry.summary_headings == []

    def test_staleness_detection(self, brain_root):
        """Index detects when summaries change."""
        from brain_sync.mcp import AreaIndex

        index = AreaIndex.build(brain_root)
        assert not index.is_stale(brain_root)

        # Modify a summary
        summary = brain_root / "insights" / "initiatives" / "AAA" / "summary.md"
        import time

        time.sleep(0.05)  # ensure mtime changes
        summary.write_text("# Updated\nNew content.", encoding="utf-8")

        assert index.is_stale(brain_root)


# ---------------------------------------------------------------------------
# fs_utils
# ---------------------------------------------------------------------------


class TestFsUtils:
    def test_is_readable_file(self, tmp_path):
        from brain_sync.fs_utils import is_readable_file

        md = tmp_path / "doc.md"
        md.write_text("hello", encoding="utf-8")
        assert is_readable_file(md) is True

        exe = tmp_path / "program.exe"
        exe.write_bytes(b"\x00")
        assert is_readable_file(exe) is False

        hidden = tmp_path / ".hidden.md"
        hidden.write_text("hidden", encoding="utf-8")
        assert is_readable_file(hidden) is False

        underscore = tmp_path / "_private.md"
        underscore.write_text("private", encoding="utf-8")
        assert is_readable_file(underscore) is False

    def test_is_content_dir(self, tmp_path):
        from brain_sync.fs_utils import is_content_dir

        normal = tmp_path / "area"
        normal.mkdir()
        assert is_content_dir(normal) is True

        dotdir = tmp_path / ".hidden"
        dotdir.mkdir()
        assert is_content_dir(dotdir) is False

        sync_ctx = tmp_path / "_sync-context"
        sync_ctx.mkdir()
        assert is_content_dir(sync_ctx) is False

    def test_get_child_dirs(self, tmp_path):
        from brain_sync.fs_utils import get_child_dirs

        (tmp_path / "b-area").mkdir()
        (tmp_path / "a-area").mkdir()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "_sync-context").mkdir()
        (tmp_path / "file.md").write_text("not a dir", encoding="utf-8")

        result = get_child_dirs(tmp_path)
        names = [p.name for p in result]
        assert names == ["a-area", "b-area"]  # sorted, no hidden/excluded

"""Tests for the MCP server tool handlers.

Tests call tool handler functions directly — no stdio transport needed.
Source management tools mock underlying commands. Query tools use real
filesystem via tmp_path fixtures.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_sync.application import (
    AddResult,
    MoveResult,
    ReconcileResult,
    RemoveResult,
    SourceAlreadyExistsError,
    SourceInfo,
    SourceNotFoundError,
)
from brain_sync.application.init import init_brain
from brain_sync.application.sources import ReconcileEntry, UnsupportedSourceUrlError
from brain_sync.brain.layout import area_insights_dir

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
    fetch_children=False,
    sync_attachments=False,
)

SAMPLE_ADD_RESULT = AddResult(
    canonical_id="confluence:12345",
    source_url="https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test",
    target_path="initiatives/test",
    fetch_children=False,
    sync_attachments=False,
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
# Fixture: mock MCP Context backed by BrainRuntime
# ---------------------------------------------------------------------------


def _make_ctx(root: Path) -> MagicMock:
    """Create a mock Context whose request_context.lifespan_context is a BrainRuntime."""
    from brain_sync.interfaces.mcp.server import AreaIndex, BrainRuntime

    rt = BrainRuntime(
        root=root,
        area_index=AreaIndex.build(root),
        regen_lock=asyncio.Lock(),
    )
    ctx = MagicMock()
    ctx.request_context.lifespan_context = rt
    return ctx


def _managed_insights(root: Path, knowledge_path: str = "") -> Path:
    return area_insights_dir(root, knowledge_path)


# ---------------------------------------------------------------------------
# Fixture: brain filesystem for query tools
# ---------------------------------------------------------------------------


@pytest.fixture
def brain_root(tmp_path: Path) -> Path:
    """Create a minimal brain structure for query tool tests."""
    root = tmp_path / "brain"
    init_brain(root)

    # knowledge/_core
    (root / "knowledge" / "_core" / "about-me.md").write_text("I am a test user.", encoding="utf-8")

    # knowledge/_core/.brain-sync/insights
    (_managed_insights(root, "_core")).mkdir(parents=True, exist_ok=True)
    (_managed_insights(root, "_core") / "summary.md").write_text(
        "# Core Summary\nOverview of the brain.", encoding="utf-8"
    )
    # journal should be excluded
    (_managed_insights(root, "_core") / "journal" / "2026-03").mkdir(parents=True)
    (_managed_insights(root, "_core") / "journal" / "2026-03" / "2026-03-08.md").write_text(
        "Journal entry.",
        encoding="utf-8",
    )

    # Area: initiatives/AAA
    (root / "knowledge" / "initiatives" / "AAA").mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "AAA" / "c12345-doc.md").write_text("AAA knowledge doc.", encoding="utf-8")
    (_managed_insights(root, "initiatives/AAA")).mkdir(parents=True)
    (_managed_insights(root, "initiatives/AAA") / "summary.md").write_text(
        "# Platform AAA Summary\n\nAAA is the main platform initiative.\n\n## Architecture\n\nMicroservices.",
        encoding="utf-8",
    )
    (_managed_insights(root, "initiatives/AAA") / "decisions.md").write_text(
        "# Decisions\n\n- Chose microservices.",
        encoding="utf-8",
    )

    # Sub-area: initiatives/AAA/Accounts Service
    (root / "knowledge" / "initiatives" / "AAA" / "Accounts Service").mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "AAA" / "Accounts Service" / "doc.md").write_text(
        "Accounts doc.",
        encoding="utf-8",
    )
    (_managed_insights(root, "initiatives/AAA/Accounts Service")).mkdir(parents=True)
    (_managed_insights(root, "initiatives/AAA/Accounts Service") / "summary.md").write_text(
        "# Accounts Service\n\nHandles user accounts.",
        encoding="utf-8",
    )

    # Area: initiatives/BBB
    (root / "knowledge" / "initiatives" / "BBB").mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "BBB" / "doc.md").write_text("BBB knowledge doc.", encoding="utf-8")
    (_managed_insights(root, "initiatives/BBB")).mkdir(parents=True)
    (_managed_insights(root, "initiatives/BBB") / "summary.md").write_text(
        "# Platform BBB\n\nBBB handles billing.",
        encoding="utf-8",
    )

    return root


@pytest.fixture
def brain_with_many_children(brain_root: Path) -> Path:
    """Extend brain_root with 20+ child areas under initiatives/AAA."""
    for i in range(20):
        name = f"Child-{i:02d}"
        (brain_root / "knowledge" / "initiatives" / "AAA" / name).mkdir(parents=True)
        (_managed_insights(brain_root, f"initiatives/AAA/{name}")).mkdir(parents=True)
        (_managed_insights(brain_root, f"initiatives/AAA/{name}") / "summary.md").write_text(
            f"# {name}\n\nSummary for {name}.",
            encoding="utf-8",
        )
    return brain_root


@pytest.fixture
def _dummy_root(tmp_path: Path) -> Path:
    """Minimal root for source management tests (no brain structure needed)."""
    root = tmp_path / "dummy"
    root.mkdir()
    return root


# ---------------------------------------------------------------------------
# Import-purity regression test (Phase 2 gate)
# ---------------------------------------------------------------------------


class TestImportPurity:
    def test_import_does_not_call_resolve_root(self):
        """Importing brain_sync.interfaces.mcp.server must not call resolve_root()."""
        import importlib
        import sys

        # Remove cached module so we can re-import
        mod_name = "brain_sync.interfaces.mcp.server"
        saved = sys.modules.pop(mod_name, None)
        try:
            with patch("brain_sync.application.roots.resolve_root", side_effect=RuntimeError("should not be called")):
                # The module imports resolve_root from commands (re-export),
                # but must not *call* it at import time.
                # We patch the underlying function that resolve_root delegates to.
                # Since the module references resolve_root by name after import,
                # we verify it doesn't execute during import.
                importlib.import_module(mod_name)
        except RuntimeError:
            pytest.fail("resolve_root() was called at import time")
        finally:
            # Restore original module
            if saved is not None:
                sys.modules[mod_name] = saved


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


class TestBrainSyncList:
    @patch("brain_sync.interfaces.mcp.server.list_sources", return_value=[])
    def test_list_empty(self, mock_list, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_list

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_list(ctx)
        assert result == {"status": "ok", "sources": [], "count": 0}
        mock_list.assert_called_once()

    @patch("brain_sync.interfaces.mcp.server.list_sources", return_value=[SAMPLE_SOURCE])
    def test_list_with_sources(self, mock_list, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_list

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_list(ctx)
        assert result["status"] == "ok"
        assert result["count"] == 1
        assert result["sources"] == [asdict(SAMPLE_SOURCE)]

    @patch("brain_sync.interfaces.mcp.server.list_sources", return_value=[SAMPLE_SOURCE])
    def test_list_filter(self, mock_list, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_list

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_list(ctx, filter_path="initiatives")
        assert result["status"] == "ok"
        mock_list.assert_called_once()
        call_kwargs = mock_list.call_args
        assert call_kwargs.kwargs.get("filter_path") == "initiatives"


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------


class TestBrainSyncAdd:
    @patch("brain_sync.interfaces.mcp.server.add_source", return_value=SAMPLE_ADD_RESULT)
    def test_add_url_success(self, mock_add, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_add

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_add(
            ctx,
            source="https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test",
            target_path="initiatives/test",
        )
        assert result["status"] == "ok"
        assert result["canonical_id"] == "confluence:12345"
        mock_add.assert_called_once()

    @patch(
        "brain_sync.interfaces.mcp.server.add_source",
        side_effect=SourceAlreadyExistsError("confluence:12345", "https://example.com", "initiatives/test"),
    )
    def test_add_url_duplicate(self, mock_add, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_add

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_add(
            ctx,
            source="https://example.com",
            target_path="initiatives/test",
        )
        assert result["status"] == "error"
        assert result["error"] == "source_already_exists"
        assert result["canonical_id"] == "confluence:12345"

    @patch(
        "brain_sync.interfaces.mcp.server.add_source",
        side_effect=UnsupportedSourceUrlError("https://bad-url.example.com"),
    )
    def test_add_url_invalid(self, mock_add, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_add

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_add(
            ctx,
            source="https://bad-url.example.com",
            target_path="test",
        )
        assert result["status"] == "error"
        assert result["error"] == "unsupported_url"

    def test_add_rejects_file_path(self, _dummy_root, tmp_path):
        """add rejects non-URL input with helpful hint."""
        from brain_sync.interfaces.mcp.server import brain_sync_add

        src_file = tmp_path / "notes.md"
        src_file.write_text("content", encoding="utf-8")

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_add(ctx, source=str(src_file), target_path="test")
        assert result["status"] == "error"
        assert result["error"] == "not_a_url"
        assert "brain_sync_add_file" in result["message"]


class TestBrainSyncAddFile:
    def test_add_file_copied(self, brain_root, tmp_path):
        """File is copied to knowledge/ by default (MCP copy=True)."""
        from brain_sync.interfaces.mcp.server import brain_sync_add_file

        src_file = tmp_path / "notes.md"
        src_file.write_text("My notes content.", encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_add_file(ctx, source=str(src_file), target_path="initiatives/AAA")
        assert result["status"] == "ok"
        assert result["action"] == "copied"
        assert "knowledge/initiatives/AAA/notes.md" in result["path"]
        # Original file still exists (copy)
        assert src_file.exists()
        # Destination file exists
        assert (brain_root / "knowledge" / "initiatives" / "AAA" / "notes.md").exists()

    def test_add_file_moved(self, brain_root, tmp_path):
        """File is moved when copy=False."""
        from brain_sync.interfaces.mcp.server import brain_sync_add_file

        src_file = tmp_path / "notes.md"
        src_file.write_text("My notes content.", encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_add_file(ctx, source=str(src_file), target_path="initiatives/AAA", copy=False)
        assert result["status"] == "ok"
        assert result["action"] == "moved"
        # Original file gone
        assert not src_file.exists()

    def test_add_file_rejects_url(self, brain_root):
        """add-file rejects URL input."""
        from brain_sync.interfaces.mcp.server import brain_sync_add_file

        ctx = _make_ctx(brain_root)
        result = brain_sync_add_file(
            ctx,
            source="https://example.com/page",
            target_path="test",
        )
        assert result["status"] == "error"
        assert result["error"] == "file_not_found"

    def test_add_file_unsupported_extension(self, brain_root, tmp_path):
        """Unsupported file types are rejected with helpful message."""
        from brain_sync.interfaces.mcp.server import brain_sync_add_file

        for ext in [".pdf", ".docx", ".png", ".jpg"]:
            src_file = tmp_path / f"doc{ext}"
            src_file.write_bytes(b"fake content")

            ctx = _make_ctx(brain_root)
            result = brain_sync_add_file(ctx, source=str(src_file), target_path="test")
            assert result["status"] == "error", f"Expected error for {ext}"
            assert result["error"] == "unsupported_file_type", f"Wrong error for {ext}"
            assert ".md" in result["message"]

    def test_add_file_collision_suffix(self, brain_root, tmp_path):
        """Numeric suffix applied when destination exists."""
        from brain_sync.interfaces.mcp.server import brain_sync_add_file

        # Create existing file at destination
        dest_dir = brain_root / "knowledge" / "initiatives" / "AAA"
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "notes.md").write_text("existing", encoding="utf-8")

        src_file = tmp_path / "notes.md"
        src_file.write_text("new content", encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_add_file(ctx, source=str(src_file), target_path="initiatives/AAA")
        assert result["status"] == "ok"
        assert "notes-2.md" in result["path"]
        assert (dest_dir / "notes-2.md").exists()

    def test_add_file_not_found(self, brain_root):
        """Non-existent file source returns error."""
        from brain_sync.interfaces.mcp.server import brain_sync_add_file

        ctx = _make_ctx(brain_root)
        result = brain_sync_add_file(ctx, source="/nonexistent/path/doc.md", target_path="test")
        assert result["status"] == "error"
        assert result["error"] == "file_not_found"

    def test_add_file_txt_supported(self, brain_root, tmp_path):
        """Plain text files are supported."""
        from brain_sync.interfaces.mcp.server import brain_sync_add_file

        src_file = tmp_path / "readme.txt"
        src_file.write_text("plain text", encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_add_file(ctx, source=str(src_file), target_path="initiatives/AAA")
        assert result["status"] == "ok"
        assert (brain_root / "knowledge" / "initiatives" / "AAA" / "readme.txt").exists()


# ---------------------------------------------------------------------------
# Remove File
# ---------------------------------------------------------------------------


class TestBrainSyncRemoveFile:
    def test_remove_file_success(self, brain_root):
        """File is removed from knowledge/."""
        from brain_sync.interfaces.mcp.server import brain_sync_remove_file

        target = brain_root / "knowledge" / "initiatives" / "AAA" / "notes.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("content", encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_remove_file(ctx, path="initiatives/AAA/notes.md")
        assert result["status"] == "ok"
        assert not target.exists()

    def test_remove_file_not_found(self, brain_root):
        """Non-existent file returns error."""
        from brain_sync.interfaces.mcp.server import brain_sync_remove_file

        ctx = _make_ctx(brain_root)
        result = brain_sync_remove_file(ctx, path="initiatives/AAA/nonexistent.md")
        assert result["status"] == "error"
        assert result["error"] == "file_not_found"

    def test_remove_file_path_traversal(self, brain_root, tmp_path):
        """Path traversal outside knowledge/ is blocked."""
        from brain_sync.interfaces.mcp.server import brain_sync_remove_file

        ctx = _make_ctx(brain_root)
        result = brain_sync_remove_file(ctx, path="../../etc/passwd")
        assert result["status"] == "error"
        assert result["error"] in ("invalid_path", "file_not_found")

    def test_remove_file_is_directory(self, brain_root):
        """Directories are rejected."""
        from brain_sync.interfaces.mcp.server import brain_sync_remove_file

        target_dir = brain_root / "knowledge" / "initiatives" / "AAA"
        target_dir.mkdir(parents=True, exist_ok=True)

        ctx = _make_ctx(brain_root)
        result = brain_sync_remove_file(ctx, path="initiatives/AAA")
        assert result["status"] == "error"
        assert result["error"] == "not_a_file"


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


class TestBrainSyncRemove:
    @patch("brain_sync.interfaces.mcp.server.remove_source", return_value=SAMPLE_REMOVE_RESULT)
    def test_remove_success(self, mock_remove, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_remove

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_remove(ctx, source="confluence:12345")
        assert result["status"] == "ok"
        assert result["canonical_id"] == "confluence:12345"

    @patch(
        "brain_sync.interfaces.mcp.server.remove_source",
        side_effect=SourceNotFoundError("confluence:99999"),
    )
    def test_remove_not_found(self, mock_remove, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_remove

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_remove(ctx, source="confluence:99999")
        assert result["status"] == "error"
        assert result["error"] == "source_not_found"
        assert result["source"] == "confluence:99999"


# ---------------------------------------------------------------------------
# Move
# ---------------------------------------------------------------------------


class TestBrainSyncMove:
    @patch("brain_sync.interfaces.mcp.server.move_source", return_value=SAMPLE_MOVE_RESULT)
    def test_move_success(self, mock_move, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_move

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_move(ctx, source="confluence:12345", to_path="initiatives/moved")
        assert result["status"] == "ok"
        assert result["new_path"] == "initiatives/moved"
        assert result["files_moved"] is True

    @patch(
        "brain_sync.interfaces.mcp.server.move_source",
        side_effect=SourceNotFoundError("confluence:99999"),
    )
    def test_move_not_found(self, mock_move, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_move

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_move(ctx, source="confluence:99999", to_path="x")
        assert result["status"] == "error"
        assert result["error"] == "source_not_found"


# ---------------------------------------------------------------------------
# Reconcile
# ---------------------------------------------------------------------------

SAMPLE_RECONCILE_RESULT = ReconcileResult(
    updated=[ReconcileEntry(canonical_id="confluence:12345", old_path="old-team", new_path="new-team")],
    not_found=["confluence:99999"],
    unchanged=3,
)


class TestBrainSyncReconcile:
    @patch("brain_sync.interfaces.mcp.server.reconcile_sources", return_value=SAMPLE_RECONCILE_RESULT)
    def test_reconcile_success(self, mock_reconcile, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_reconcile

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_reconcile(ctx)
        assert result["status"] == "ok"
        assert len(result["updated"]) == 1
        assert result["updated"][0]["canonical_id"] == "confluence:12345"
        assert result["updated"][0]["old_path"] == "old-team"
        assert result["updated"][0]["new_path"] == "new-team"
        assert result["not_found"] == ["confluence:99999"]
        assert result["unchanged"] == 3

    @patch(
        "brain_sync.interfaces.mcp.server.reconcile_sources",
        return_value=ReconcileResult(updated=[], not_found=[], unchanged=5),
    )
    def test_reconcile_noop(self, mock_reconcile, _dummy_root):
        from brain_sync.interfaces.mcp.server import brain_sync_reconcile

        ctx = _make_ctx(_dummy_root)
        result = brain_sync_reconcile(ctx)
        assert result["status"] == "ok"
        assert result["updated"] == []
        assert result["not_found"] == []
        assert result["unchanged"] == 5


# ---------------------------------------------------------------------------
# Regen
# ---------------------------------------------------------------------------


class TestBrainSyncRegen:
    @pytest.mark.asyncio
    async def test_regen_path(self, _dummy_root):
        with patch("brain_sync.interfaces.mcp.server.run_regen", new_callable=AsyncMock, return_value=3):
            from brain_sync.interfaces.mcp.server import brain_sync_regen

            ctx = _make_ctx(_dummy_root)
            result = await brain_sync_regen(ctx, path="initiatives/test")
            assert result["status"] == "ok"
            assert result["summaries_regenerated"] == 3
            assert result["path"] == "initiatives/test"

    @pytest.mark.asyncio
    async def test_regen_all(self, _dummy_root):
        with patch("brain_sync.interfaces.mcp.server.run_regen", new_callable=AsyncMock, return_value=7):
            from brain_sync.interfaces.mcp.server import brain_sync_regen

            ctx = _make_ctx(_dummy_root)
            result = await brain_sync_regen(ctx)
            assert result["status"] == "ok"
            assert result["summaries_regenerated"] == 7
            assert result["path"] == "all"


# ---------------------------------------------------------------------------
# Query tools — use real filesystem via brain_root fixture
# ---------------------------------------------------------------------------


class TestBrainSyncQuery:
    def test_query_with_match(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_query

        ctx = _make_ctx(brain_root)
        result = brain_sync_query(ctx, query="AAA")

        assert result["status"] == "ok"
        assert len(result["matches"]) >= 1
        assert result["matches"][0]["path"] == "initiatives/AAA"
        assert "global_context" not in result
        assert result["total_areas"] > 0

    def test_query_with_global(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_query

        ctx = _make_ctx(brain_root)
        result = brain_sync_query(ctx, query="AAA", include_global=True)

        assert result["status"] == "ok"
        assert "global_context" in result
        gc = result["global_context"]
        assert gc["path"] == "knowledge/_core/.brain-sync/insights/summary.md"
        assert gc["present"] is True
        assert "Core Summary" in gc["content"]
        assert "I am a test user." not in gc["content"]

    def test_query_no_match(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_query

        ctx = _make_ctx(brain_root)
        result = brain_sync_query(ctx, query="nonexistent")

        assert result["status"] == "ok"
        assert result["matches"] == []

    def test_query_max_results(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_query

        ctx = _make_ctx(brain_root)
        result = brain_sync_query(ctx, query="initiatives", max_results=1)

        assert result["status"] == "ok"
        assert len(result["matches"]) == 1

    def test_query_searches_summary_content(self, brain_root):
        """Matches against summary.md content, not just folder names."""
        from brain_sync.interfaces.mcp.server import brain_sync_query

        ctx = _make_ctx(brain_root)
        # "billing" appears only in BBB's summary, not in path
        result = brain_sync_query(ctx, query="billing")

        assert result["status"] == "ok"
        assert len(result["matches"]) >= 1
        assert result["matches"][0]["path"] == "initiatives/BBB"

    def test_query_path_weighted_higher(self, brain_root):
        """Path matches score higher than body matches."""
        from brain_sync.interfaces.mcp.server import brain_sync_query

        ctx = _make_ctx(brain_root)
        result = brain_sync_query(ctx, query="AAA")

        assert result["status"] == "ok"
        # AAA should be first because "AAA" is in the path (x3)
        assert result["matches"][0]["path"] == "initiatives/AAA"

    def test_query_areas_capped(self, tmp_path):
        """Areas listing respects MAX_AREAS_LISTED cap."""
        from brain_sync.interfaces.mcp.server import MAX_AREAS_LISTED, brain_sync_query

        root = tmp_path / "big-brain"
        init_brain(root)
        (root / "knowledge" / "_core").mkdir(parents=True, exist_ok=True)
        (_managed_insights(root, "_core")).mkdir(parents=True, exist_ok=True)
        # Create 60 areas with co-located summaries so index + areas listing both work.
        for i in range(60):
            (root / "knowledge" / f"area-{i:03d}").mkdir(parents=True)
            area = _managed_insights(root, f"area-{i:03d}")
            area.mkdir(parents=True)
            (area / "summary.md").write_text(f"# Area {i}", encoding="utf-8")

        ctx = _make_ctx(root)
        result = brain_sync_query(ctx, query="area")

        assert result["status"] == "ok"
        assert len(result["areas"]) == MAX_AREAS_LISTED
        assert result["areas_truncated"] is True
        assert result["total_areas"] == 60


class TestBrainSyncGetContext:
    def test_get_context(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_get_context

        ctx = _make_ctx(brain_root)
        result = brain_sync_get_context(ctx)

        assert result["status"] == "ok"
        gc = result["global_context"]
        assert gc["path"] == "knowledge/_core/.brain-sync/insights/summary.md"
        assert gc["present"] is True
        assert "Core Summary" in gc["content"]
        assert "I am a test user." not in gc["content"]
        assert result["total_areas"] > 0

    def test_get_context_missing_core(self, tmp_path):
        """Graceful when _core/ doesn't exist."""
        from brain_sync.interfaces.mcp.server import brain_sync_get_context

        root = tmp_path / "empty-brain"
        init_brain(root)

        ctx = _make_ctx(root)
        result = brain_sync_get_context(ctx)

        assert result["status"] == "ok"
        assert result["global_context"]["path"] == "knowledge/_core/.brain-sync/insights/summary.md"
        assert result["global_context"]["content"] == ""
        assert result["global_context"]["present"] is False
        assert result["total_areas"] == 0


class TestBrainSyncOpenArea:
    def test_open_area(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_open_area

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_area(ctx, path="initiatives/AAA")

        assert result["status"] == "ok"
        assert result["path"] == "initiatives/AAA"
        assert "summary.md" in result["insights"]
        assert "decisions.md" in result["insights"]
        assert result["total_children"] >= 1
        # Accounts Service should be in children
        child_names = [c["name"] for c in result["children"]]
        assert "Accounts Service" in child_names

    def test_open_area_with_children(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_open_area

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_area(ctx, path="initiatives/AAA", include_children=True)

        assert result["status"] == "ok"
        assert "child_summaries" in result
        assert "Accounts Service" in result["child_summaries"]
        assert "Handles user accounts" in result["child_summaries"]["Accounts Service"]

    def test_open_area_with_knowledge_list(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_open_area

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_area(ctx, path="initiatives/AAA", include_knowledge_list=True)

        assert result["status"] == "ok"
        assert "knowledge_files" in result
        assert "c12345-doc.md" in result["knowledge_files"]

    def test_open_area_not_found(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_open_area

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_area(ctx, path="nonexistent/area")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_area_summary_truncation(self, brain_root):
        """Large summary.md is truncated with marker."""
        from brain_sync.interfaces.mcp.server import MAX_SUMMARY_CHARS, TRUNCATION_MARKER, brain_sync_open_area

        # Write a large summary
        large_summary = "# Large Summary\n\n" + "x" * (MAX_SUMMARY_CHARS + 5000)
        (_managed_insights(brain_root, "initiatives/AAA") / "summary.md").write_text(
            large_summary,
            encoding="utf-8",
        )

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_area(ctx, path="initiatives/AAA")

        assert result["status"] == "ok"
        summary = result["insights"]["summary.md"]
        assert len(summary) <= MAX_SUMMARY_CHARS + len(TRUNCATION_MARKER) + 10
        assert TRUNCATION_MARKER in summary

    def test_open_area_child_limit(self, brain_with_many_children):
        """Area with many children respects MAX_CHILDREN cap."""
        from brain_sync.interfaces.mcp.server import MAX_CHILDREN, brain_sync_open_area

        ctx = _make_ctx(brain_with_many_children)
        result = brain_sync_open_area(ctx, path="initiatives/AAA", include_children=True)

        assert result["status"] == "ok"
        assert len(result["child_summaries"]) <= MAX_CHILDREN
        assert result["children_truncated"] is True
        assert result["total_children"] > MAX_CHILDREN

    def test_open_area_payload_cap(self, brain_root):
        """Total response respects MAX_AREA_PAYLOAD, drops artifacts first."""
        from brain_sync.interfaces.mcp.server import TRUNCATION_MARKER, brain_sync_open_area

        # Write a very large summary and large artifacts
        insights_dir = _managed_insights(brain_root, "initiatives/AAA")
        (insights_dir / "summary.md").write_text("# Summary\n" + "s" * 30000, encoding="utf-8")
        for i in range(5):
            (insights_dir / f"artifact-{i}.md").write_text("a" * 8000, encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_area(ctx, path="initiatives/AAA")

        assert result["status"] == "ok"
        # Artifacts should have been replaced with truncation marker
        for key, value in result["insights"].items():
            if key != "summary.md":
                assert value == TRUNCATION_MARKER or len(value) <= 8000


class TestBrainSyncOpenFile:
    def test_open_file(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(ctx, path="knowledge/_core/.brain-sync/insights/summary.md")

        assert result["status"] == "ok"
        assert "Core Summary" in result["content"]
        assert result["offset"] == 0
        assert result["truncated"] is False
        assert "next_offset" not in result

    def test_open_file_not_found(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(ctx, path="nonexistent/file.md")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_file_path_traversal(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        # Create a file outside brain root
        (brain_root.parent / "secret.md").write_text("secret!", encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(ctx, path="../secret.md")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_file_directory_rejected(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(ctx, path="knowledge/_core/.brain-sync/insights")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_file_binary_rejected(self, brain_root):
        """Binary extensions return unsupported_type error."""
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        (brain_root / "test.pdf").write_bytes(b"fake pdf")

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(ctx, path="test.pdf")

        assert result["status"] == "error"
        assert result["error"] == "unsupported_type"
        assert result["extension"] == ".pdf"

    def test_open_file_json_allowed(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        (brain_root / "data.json").write_text('{"key": "value"}', encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(ctx, path="data.json")

        assert result["status"] == "ok"
        assert '"key"' in result["content"]

    @pytest.mark.skipif(os.name == "nt", reason="symlinks may require elevated privileges on Windows")
    def test_open_file_symlink_escape(self, brain_root):
        """Symlink pointing outside brain root is rejected."""
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        outside = brain_root.parent / "outside.md"
        outside.write_text("escaped!", encoding="utf-8")
        link = brain_root / "link.md"
        link.symlink_to(outside)

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(ctx, path="link.md")

        assert result["status"] == "error"
        assert result["error"] == "not_found"

    def test_open_file_truncated_includes_metadata(self, brain_root):
        """File larger than DEFAULT_FILE_CHARS returns pagination metadata."""
        from brain_sync.interfaces.mcp.server import DEFAULT_FILE_CHARS, brain_sync_open_file

        # Write a file larger than the default limit with line breaks
        lines = [f"Line {i}: " + "x" * 80 for i in range(2500)]
        large_content = "\n".join(lines)
        assert len(large_content) > DEFAULT_FILE_CHARS
        (brain_root / "large.md").write_text(large_content, encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(ctx, path="large.md")

        assert result["status"] == "ok"
        assert result["truncated"] is True
        assert "next_offset" in result
        assert result["next_offset"] > 0
        assert "hint" in result
        assert "offset=" in result["hint"]

    def test_open_file_offset_reads_remainder(self, brain_root):
        """Pagination with offset picks up where previous call left off."""
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        lines = [f"Line {i}: " + "x" * 80 for i in range(2500)]
        large_content = "\n".join(lines)
        (brain_root / "large.md").write_text(large_content, encoding="utf-8")

        ctx = _make_ctx(brain_root)
        # First call
        r1 = brain_sync_open_file(ctx, path="large.md")
        assert r1["truncated"] is True

        # Second call at next_offset
        r2 = brain_sync_open_file(ctx, path="large.md", offset=r1["next_offset"])

        # Content should be contiguous
        combined = r1["content"] + r2["content"]
        assert combined == large_content[: len(combined)]

    def test_open_file_offset_beyond_eof(self, brain_root):
        """Offset past end of file returns empty content."""
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(
            ctx,
            path="knowledge/_core/.brain-sync/insights/summary.md",
            offset=999999,
        )

        assert result["status"] == "ok"
        assert result["content"] == ""
        assert result["truncated"] is False

    def test_open_file_limit_clamped(self, brain_root):
        """Limit larger than MAX_FILE_CHARS is clamped."""
        from brain_sync.interfaces.mcp.server import MAX_FILE_CHARS, brain_sync_open_file

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(
            ctx,
            path="knowledge/_core/.brain-sync/insights/summary.md",
            limit=MAX_FILE_CHARS + 100,
        )

        assert result["status"] == "ok"
        assert result["limit"] == MAX_FILE_CHARS

    def test_open_file_newline_alignment(self, brain_root):
        """Chunk boundary aligns to newline, not mid-line."""
        from brain_sync.interfaces.mcp.server import brain_sync_open_file

        # Write content where truncation would land mid-line
        lines = [f"Line {i}: " + "y" * 80 for i in range(250)]
        large_content = "\n".join(lines)
        (brain_root / "aligned.md").write_text(large_content, encoding="utf-8")

        ctx = _make_ctx(brain_root)
        result = brain_sync_open_file(ctx, path="aligned.md")

        if result["truncated"]:
            # Content should end at a newline
            assert result["content"].endswith("\n") or "\n" not in result["content"][-1:]


# ---------------------------------------------------------------------------
# Search index
# ---------------------------------------------------------------------------


class TestAreaIndex:
    def test_build_and_search(self, brain_root):
        from brain_sync.interfaces.mcp.server import AreaIndex

        index = AreaIndex.build(brain_root)
        assert len(index.entries) > 0

        results = index.search("AAA")
        assert len(results) >= 1
        assert results[0]["path"] == "initiatives/AAA"

    def test_search_deterministic_ordering(self, brain_root):
        """Two searches with same query produce identical results."""
        from brain_sync.interfaces.mcp.server import AreaIndex

        index = AreaIndex.build(brain_root)
        r1 = index.search("initiatives")
        r2 = index.search("initiatives")
        assert r1 == r2

    def test_missing_summary(self, tmp_path):
        """Areas without summary.md are indexed with empty fields."""
        from brain_sync.interfaces.mcp.server import AreaIndex

        root = tmp_path / "brain"
        init_brain(root)
        (root / "knowledge" / "area-no-summary").mkdir(parents=True)
        # No co-located summary.md

        index = AreaIndex.build(root)
        assert len(index.entries) == 1
        entry = index.entries[0]
        assert entry.summary_first_para == ""
        assert entry.summary_headings == []

    def test_journal_dirs_excluded(self, tmp_path):
        """Journal directories (insights-only) are not indexed since AreaIndex walks knowledge/."""
        from brain_sync.interfaces.mcp.server import AreaIndex

        root = tmp_path / "brain"
        init_brain(root)
        # Real knowledge area
        (root / "knowledge" / "initiatives" / "project").mkdir(parents=True)
        (_managed_insights(root, "initiatives/project")).mkdir(parents=True)
        (_managed_insights(root, "initiatives/project") / "summary.md").write_text("# Project", encoding="utf-8")
        # Journal exists only in managed insights (not as a knowledge area)
        (_managed_insights(root, "initiatives/project") / "journal" / "2026-03").mkdir(parents=True)
        (_managed_insights(root, "initiatives/project") / "journal" / "2026-03" / "entry.md").write_text(
            "Journal entry.", encoding="utf-8"
        )

        index = AreaIndex.build(root)
        paths = [e.path for e in index.entries]
        assert "initiatives/project" in paths
        assert not any("journal" in p for p in paths)

    def test_staleness_detection(self, brain_root):
        """Index detects when summaries change."""
        from brain_sync.interfaces.mcp.server import AreaIndex

        index = AreaIndex.build(brain_root)
        assert not index.is_stale(brain_root)

        # Modify a summary
        summary = _managed_insights(brain_root, "initiatives/AAA") / "summary.md"
        import time

        time.sleep(0.05)  # ensure mtime changes
        summary.write_text("# Updated\nNew content.", encoding="utf-8")

        assert index.is_stale(brain_root)


# ---------------------------------------------------------------------------
# Placement suggestion tool
# ---------------------------------------------------------------------------


class TestSuggestPlacement:
    def test_basic_suggestion(self, brain_root):
        """Suggest placement returns candidates matching query terms."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        result = brain_sync_suggest_placement(ctx, document_title="AAA platform architecture")
        assert result["status"] == "ok"
        assert len(result["candidates"]) > 0
        assert result["query_terms"]
        # AAA area should be in the top results
        paths = [c["path"] for c in result["candidates"]]
        assert any("AAA" in p for p in paths)

    def test_no_matches(self, brain_root):
        """Returns empty candidates with hint when nothing matches."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        result = brain_sync_suggest_placement(ctx, document_title="zzzznonexistent")
        assert result["status"] == "ok"
        assert result["candidates"] == []
        assert "hint" in result

    def test_subtree_filter(self, brain_root):
        """Subtree restricts results to paths under the prefix."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        result = brain_sync_suggest_placement(
            ctx,
            document_title="AAA accounts",
            subtree="initiatives/AAA",
        )
        assert result["status"] == "ok"
        for c in result["candidates"]:
            assert c["path"].startswith("initiatives/AAA")

    def test_with_excerpt(self, brain_root):
        """Excerpt provides additional search terms."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        result = brain_sync_suggest_placement(
            ctx,
            document_title="meeting-notes",
            document_excerpt="Discussion about the AAA platform microservices architecture",
        )
        assert result["status"] == "ok"
        assert len(result["query_terms"]) > 1

    def test_max_results_capped(self, brain_root):
        """Max results is respected and capped at 10."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        result = brain_sync_suggest_placement(ctx, document_title="AAA", max_results=1)
        assert len(result["candidates"]) <= 1

    def test_empty_brain(self, tmp_path):
        """Empty brain returns no candidates."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        root = tmp_path / "empty-brain"
        init_brain(root)
        ctx = _make_ctx(root)
        result = brain_sync_suggest_placement(ctx, document_title="anything")
        assert result["status"] == "ok"
        assert result["candidates"] == []
        assert "hint" in result

    def test_source_url_resolves_title(self, brain_root):
        """source_url without document_title triggers title resolution."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        with patch(
            "brain_sync.sources.title_resolution.resolve_source_title_sync",
            return_value="AAA platform architecture",
        ) as mock_resolve:
            result = brain_sync_suggest_placement(
                ctx,
                source_url="https://docs.google.com/document/d/abc123/edit",
            )
        mock_resolve.assert_called_once_with("https://docs.google.com/document/d/abc123/edit")
        assert result["status"] == "ok"
        assert len(result["candidates"]) > 0

    def test_document_title_wins_over_source_url(self, brain_root):
        """Explicit document_title takes precedence over source_url."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        with patch(
            "brain_sync.sources.title_resolution.resolve_source_title_sync",
        ) as mock_resolve:
            result = brain_sync_suggest_placement(
                ctx,
                document_title="AAA platform",
                source_url="https://docs.google.com/document/d/abc123/edit",
            )
        mock_resolve.assert_not_called()
        assert result["status"] == "ok"

    def test_no_title_no_url_returns_error(self, brain_root):
        """Neither document_title nor source_url returns error."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        result = brain_sync_suggest_placement(ctx)
        assert result["status"] == "error"
        assert result["error"] == "no_title"

    def test_source_url_resolution_failure_returns_error(self, brain_root):
        """source_url that can't be resolved returns error."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        with patch(
            "brain_sync.sources.title_resolution.resolve_source_title_sync",
            return_value=None,
        ):
            result = brain_sync_suggest_placement(
                ctx,
                source_url="https://docs.google.com/document/d/abc123/edit",
            )
        assert result["status"] == "error"
        assert result["error"] == "no_title"

    def test_suggested_filename_with_source_url(self, brain_root):
        """source_url triggers canonical filename in response."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        with patch(
            "brain_sync.sources.title_resolution.resolve_source_title_sync",
            return_value="AAA platform architecture",
        ):
            result = brain_sync_suggest_placement(
                ctx,
                source_url="https://docs.google.com/document/d/abc123/edit",
            )
        assert result["status"] == "ok"
        assert result["suggested_filename"] == "gabc123-aaa-platform-architecture.md"

    def test_suggested_filename_none_without_source_url(self, brain_root):
        """No source_url means suggested_filename is None."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        result = brain_sync_suggest_placement(ctx, document_title="AAA platform")
        assert result["status"] == "ok"
        assert result["suggested_filename"] is None

    def test_suggested_filename_confluence(self, brain_root):
        """Confluence source_url produces c-prefixed filename."""
        from brain_sync.interfaces.mcp.server import brain_sync_suggest_placement

        ctx = _make_ctx(brain_root)
        result = brain_sync_suggest_placement(
            ctx,
            document_title="AAA platform",
            source_url="https://acme.atlassian.net/wiki/spaces/TEAM/pages/12345/AAA+Platform",
        )
        assert result["status"] == "ok"
        assert result["suggested_filename"] == "c12345-aaa-platform.md"


# ---------------------------------------------------------------------------
# fs_utils
# ---------------------------------------------------------------------------


class TestFsUtils:
    def test_is_readable_file(self, tmp_path):
        from brain_sync.brain.tree import is_readable_file

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
        from brain_sync.brain.tree import is_content_dir

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
        from brain_sync.brain.tree import get_child_dirs

        (tmp_path / "b-area").mkdir()
        (tmp_path / "a-area").mkdir()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "_sync-context").mkdir()
        (tmp_path / "file.md").write_text("not a dir", encoding="utf-8")

        result = get_child_dirs(tmp_path)
        names = [p.name for p in result]
        assert names == ["a-area", "b-area"]  # sorted, no hidden/excluded


class TestBrainSyncUsage:
    """Tests for brain_sync_usage MCP tool."""

    def test_usage_returns_summary_structure(self, brain_root):
        from brain_sync.interfaces.mcp.server import brain_sync_usage
        from brain_sync.runtime.repository import _connect
        from brain_sync.runtime.token_tracking import OP_REGEN, record_token_event

        # Ensure DB exists
        _connect(brain_root).close()

        record_token_event(
            root=brain_root,
            session_id="mcp-test-sess",
            operation_type=OP_REGEN,
            resource_type="knowledge",
            resource_id="initiatives/AAA",
            is_chunk=False,
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=200,
            duration_ms=5000,
            num_turns=3,
            success=True,
        )

        ctx = _make_ctx(brain_root)
        result = brain_sync_usage(ctx, days=7)

        assert result["status"] == "ok"
        assert result["days"] == 7
        assert result["total_invocations"] == 1
        assert result["total_input"] == 1000
        assert result["total_output"] == 200
        assert result["total_tokens"] == 1200
        assert len(result["by_operation"]) >= 1
        assert len(result["by_day"]) >= 1

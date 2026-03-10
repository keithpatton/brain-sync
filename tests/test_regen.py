"""Tests for the insight regeneration engine."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from brain_sync.regen import (
    CHUNK_TARGET_CHARS,
    MAX_CHUNKS,
    MAX_PROMPT_TOKENS,
    PROMPT_VERSION,
    ClaudeResult,
    PromptResult,
    RegenConfig,
    RegenFailed,
    _build_chunk_prompt,
    _build_prompt,
    _collect_child_summaries,
    _collect_global_context,
    _compute_hash,
    _find_all_content_paths,
    _first_heading,
    _get_child_dirs,
    _is_content_dir,
    _preprocess_content,
    _split_markdown_chunks,
    folder_content_hash,
    invalidate_global_context_cache,
    regen_all,
    regen_path,
    text_similarity,
)
from brain_sync.retry import claude_breaker
from brain_sync.state import (
    InsightState,
    _connect,
    delete_insight_state,
    load_insight_state,
    save_insight_state,
)


@pytest.fixture(autouse=True)
def _reset_breaker():
    """Reset the global circuit breaker between tests."""
    claude_breaker.reset()
    yield
    claude_breaker.reset()


@pytest.fixture(autouse=True)
def _skip_retry_sleep():
    """Skip retry backoff sleeps in tests."""
    with patch("brain_sync.retry.asyncio.sleep", new_callable=AsyncMock):
        yield


@pytest.fixture
def brain(tmp_path):
    """Create a minimal brain structure with SQLite initialized."""
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / "insights").mkdir()
    # Initialize SQLite
    conn = _connect(root)
    conn.close()
    return root


class TestFolderContentHash:
    def test_empty_folder(self, tmp_path):
        folder = tmp_path / "empty"
        folder.mkdir()
        h = folder_content_hash(folder)
        assert isinstance(h, str)
        assert len(h) == 64  # sha256 hex

    def test_deterministic(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        (folder / "b.md").write_text("world", encoding="utf-8")
        h1 = folder_content_hash(folder)
        h2 = folder_content_hash(folder)
        assert h1 == h2

    def test_changes_with_content(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("v1", encoding="utf-8")
        h1 = folder_content_hash(folder)
        (folder / "a.md").write_text("v2", encoding="utf-8")
        h2 = folder_content_hash(folder)
        assert h1 != h2

    def test_ignores_non_readable_extensions(self, tmp_path):
        """Files with extensions not in READABLE_EXTENSIONS are ignored."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = folder_content_hash(folder)
        (folder / "archive.zip").write_bytes(b"PK\x03\x04")
        (folder / "binary.exe").write_bytes(b"\x00\x01")
        h2 = folder_content_hash(folder)
        assert h1 == h2

    def test_includes_readable_non_md_files(self, tmp_path):
        """Files with readable extensions (txt, pdf, etc.) are included in hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = folder_content_hash(folder)
        (folder / "notes.txt").write_text("included now", encoding="utf-8")
        h2 = folder_content_hash(folder)
        assert h1 != h2

    def test_ignores_hidden_and_underscore_files(self, tmp_path):
        """Files starting with _ or . are ignored regardless of extension."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = folder_content_hash(folder)
        (folder / ".hidden.md").write_text("hidden", encoding="utf-8")
        (folder / "_private.md").write_text("private", encoding="utf-8")
        h2 = folder_content_hash(folder)
        assert h1 == h2

    def test_new_file_changes_hash(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = folder_content_hash(folder)
        (folder / "b.md").write_text("new file", encoding="utf-8")
        h2 = folder_content_hash(folder)
        assert h1 != h2


class TestTextSimilarity:
    def test_identical(self):
        assert text_similarity("hello world", "hello world") == 1.0

    def test_whitespace_normalisation(self):
        assert text_similarity("hello  world", "hello world") == 1.0
        assert text_similarity("hello\n\nworld", "hello world") == 1.0

    def test_completely_different(self):
        sim = text_similarity("abc", "xyz")
        assert sim < 0.5

    def test_mostly_similar(self):
        a = "This is a summary about architecture decisions and patterns."
        b = "This is a summary about architecture decisions and design patterns."
        sim = text_similarity(a, b)
        assert sim > 0.8

    def test_empty_strings(self):
        assert text_similarity("", "") == 1.0

    def test_one_empty(self):
        assert text_similarity("hello", "") == 0.0


class TestInsightStateDB:
    def test_save_and_load(self, brain):
        istate = InsightState(
            knowledge_path="initiatives/test",
            content_hash="abc123",
            summary_hash="def456",
            last_regen_utc="2026-03-07T00:00:00Z",
            regen_status="idle",
        )
        save_insight_state(brain, istate)
        loaded = load_insight_state(brain, "initiatives/test")
        assert loaded is not None
        assert loaded.content_hash == "abc123"
        assert loaded.summary_hash == "def456"
        assert loaded.regen_status == "idle"

    def test_load_nonexistent(self, brain):
        result = load_insight_state(brain, "does/not/exist")
        assert result is None

    def test_upsert_updates(self, brain):
        istate = InsightState(knowledge_path="test", content_hash="v1")
        save_insight_state(brain, istate)

        istate.content_hash = "v2"
        istate.regen_status = "running"
        save_insight_state(brain, istate)

        loaded = load_insight_state(brain, "test")
        assert loaded.content_hash == "v2"
        assert loaded.regen_status == "running"


class TestRegenPath:
    """Tests for the regen_path loop with mocked Claude CLI."""

    def _mock_claude_return_summary(self, content: str = "# Test Summary\n\nGenerated insight summary content."):
        """Create a mock invoke_claude that returns summary text."""

        async def fake_invoke(prompt: str, cwd: Path, **kwargs):
            return ClaudeResult(success=True, output=content)

        return fake_invoke

    def test_leaf_regen_creates_summary(self, brain):
        """Leaf regen with md files creates summary."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Project Doc\nSome content.", encoding="utf-8")

        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_return_summary()):
            count = asyncio.run(regen_path(brain, "project"))

        assert count >= 1
        summary = brain / "insights" / "project" / "summary.md"
        assert summary.exists()

        # Check insight state was saved
        istate = load_insight_state(brain, "project")
        assert istate is not None
        assert istate.regen_status == "idle"
        assert istate.content_hash is not None

    def test_unchanged_content_skips_regen(self, brain):
        """If content hash matches, regen is skipped."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Stable Doc", encoding="utf-8")

        # Pre-populate insight state with matching hash
        # For a leaf (no child dirs), the unified hash equals folder_content_hash
        child_dirs = _get_child_dirs(kdir)
        unified_hash = _compute_hash(child_dirs, {}, kdir, True)

        save_insight_state(
            brain,
            InsightState(
                knowledge_path="project",
                content_hash=unified_hash,
                summary_hash="existing",
                regen_status="idle",
            ),
        )

        with patch("brain_sync.regen.invoke_claude") as mock_claude:
            count = asyncio.run(regen_path(brain, "project"))

        assert count == 0
        mock_claude.assert_not_called()

    def test_similarity_guard_discards_rewrite(self, brain):
        """If new summary is >97% similar, it's discarded."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc Content V2", encoding="utf-8")

        idir = brain / "insights" / "project"
        idir.mkdir(parents=True)
        old_summary = "# Project Summary\n\nThis is the existing summary about the project."
        (idir / "summary.md").write_text(old_summary, encoding="utf-8")

        # Mock Claude to write an almost-identical summary
        near_identical = "# Project Summary\n\nThis is the existing summary about the project ."

        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_return_summary(near_identical)):
            count = asyncio.run(regen_path(brain, "project"))

        # Summary should have been discarded (restored to old)
        assert count == 0
        current = (idir / "summary.md").read_text(encoding="utf-8")
        assert current == old_summary

    def test_claude_failure_marks_failed(self, brain):
        """If Claude CLI fails, insight state is marked as failed and RegenFailed raised."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")

        async def fail_invoke(*args, **kwargs):
            return ClaudeResult(success=False, output="")

        with patch("brain_sync.regen.invoke_claude", side_effect=fail_invoke):
            with pytest.raises(RegenFailed):
                asyncio.run(regen_path(brain, "project"))

        istate = load_insight_state(brain, "project")
        assert istate is not None
        assert istate.regen_status == "failed"

    def test_parent_reads_child_summaries(self, brain):
        """Parent regen reads child summaries, not raw knowledge."""
        # Create parent with two child areas
        for child in ["child-a", "child-b"]:
            kdir = brain / "knowledge" / "parent" / child
            kdir.mkdir(parents=True)
            (kdir / "doc.md").write_text(f"# {child} content", encoding="utf-8")

            idir = brain / "insights" / "parent" / child
            idir.mkdir(parents=True)
            (idir / "summary.md").write_text(f"# {child} Summary\nDetails.", encoding="utf-8")

        # Parent knowledge dir exists (it has subdirs)
        (brain / "knowledge" / "parent").mkdir(exist_ok=True)

        prompt_captured = []

        async def capture_and_return(prompt: str, cwd: Path, **kwargs):
            prompt_captured.append(prompt)
            return ClaudeResult(success=True, output="# Parent Summary\nOverview.")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture_and_return):
            count = asyncio.run(regen_path(brain, "parent"))

        assert count >= 1
        # Verify prompt contained child summaries
        assert len(prompt_captured) >= 1
        prompt = prompt_captured[0]
        assert "child-a" in prompt
        assert "child-b" in prompt
        assert "Sub-area summaries" in prompt

    def test_nonexistent_knowledge_dir_cleans_up(self, brain):
        """Regen for a nonexistent knowledge dir cleans up stale insights."""
        # Create stale insights with no corresponding knowledge
        idir = brain / "insights" / "deleted"
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("stale", encoding="utf-8")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="deleted",
                content_hash="old",
                regen_status="idle",
            ),
        )

        with patch("brain_sync.regen.invoke_claude") as mock:
            count = asyncio.run(regen_path(brain, "deleted"))
        assert count == 0
        mock.assert_not_called()
        # Insights should be cleaned up
        assert not idir.exists()
        assert load_insight_state(brain, "deleted") is None

    def test_empty_knowledge_dir(self, brain):
        """Regen for an empty knowledge dir (no readable files) cleans up."""
        kdir = brain / "knowledge" / "empty"
        kdir.mkdir(parents=True)
        # Create stale insight
        idir = brain / "insights" / "empty"
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("stale", encoding="utf-8")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="empty",
                content_hash="old",
                regen_status="idle",
            ),
        )

        with patch("brain_sync.regen.invoke_claude") as mock:
            count = asyncio.run(regen_path(brain, "empty"))
        assert count == 0
        mock.assert_not_called()
        # Stale insights cleaned up
        assert not idir.exists()
        assert load_insight_state(brain, "empty") is None

    def test_mixed_folder_includes_direct_files_in_prompt(self, brain):
        """Parent folder with direct files includes them in the prompt."""
        # Create mixed folder: overview.md + child dir with summary
        kdir = brain / "knowledge" / "initiative"
        kdir.mkdir(parents=True)
        (kdir / "overview.md").write_text("# Overview", encoding="utf-8")
        child_kdir = kdir / "meetings"
        child_kdir.mkdir()
        (child_kdir / "notes.md").write_text("# Meeting Notes", encoding="utf-8")

        # Pre-create child summary
        child_idir = brain / "insights" / "initiative" / "meetings"
        child_idir.mkdir(parents=True)
        (child_idir / "summary.md").write_text("# Meetings Summary", encoding="utf-8")

        prompt_captured = []

        async def capture_and_return(prompt: str, cwd: Path, **kwargs):
            prompt_captured.append(prompt)
            return ClaudeResult(success=True, output="# Initiative Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture_and_return):
            asyncio.run(regen_path(brain, "initiative"))

        assert len(prompt_captured) >= 1
        prompt = prompt_captured[0]
        # Should contain both direct file listing AND child summaries
        assert "overview.md" in prompt
        assert "Sub-area summaries" in prompt
        assert "meetings" in prompt

    def test_mixed_folder_direct_file_change_triggers_regen(self, brain):
        """Changing a direct file in a mixed folder triggers regen."""
        kdir = brain / "knowledge" / "initiative"
        kdir.mkdir(parents=True)
        (kdir / "overview.md").write_text("# V1", encoding="utf-8")
        child_kdir = kdir / "meetings"
        child_kdir.mkdir()
        (child_kdir / "notes.md").write_text("# Notes", encoding="utf-8")

        # Pre-create child summary
        child_idir = brain / "insights" / "initiative" / "meetings"
        child_idir.mkdir(parents=True)
        (child_idir / "summary.md").write_text("# Meetings Summary", encoding="utf-8")

        # First regen
        with patch(
            "brain_sync.regen.invoke_claude",
            side_effect=self._mock_claude_return_summary("# Summary V1\n\nInitiative overview content."),
        ):
            asyncio.run(regen_path(brain, "initiative"))

        # Change direct file
        (kdir / "overview.md").write_text("# V2 — significant change", encoding="utf-8")

        # Second regen should trigger (hash changed)
        with patch(
            "brain_sync.regen.invoke_claude",
            side_effect=self._mock_claude_return_summary(
                "# Summary V2\n\nCompletely different initiative overview.",
            ),
        ) as mock:
            count = asyncio.run(regen_path(brain, "initiative"))

        assert count >= 1
        mock.assert_called()

    def test_deleted_leaf_cleans_up_insights(self, brain):
        """Deleting all files from a leaf removes its insights."""
        kdir = brain / "knowledge" / "parent" / "child"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("content", encoding="utf-8")

        # Create insight for child
        idir = brain / "insights" / "parent" / "child"
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("child summary", encoding="utf-8")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="parent/child",
                content_hash="old",
                regen_status="idle",
            ),
        )

        # Delete all files from the leaf
        (kdir / "doc.md").unlink()

        with patch("brain_sync.regen.invoke_claude"):
            asyncio.run(regen_path(brain, "parent/child"))

        # Child insights should be cleaned up
        assert not idir.exists()
        assert load_insight_state(brain, "parent/child") is None

    def test_deleted_subfolder_cleans_up_insights(self, brain):
        """Deleting a knowledge subfolder cleans up corresponding insights."""
        # Create parent with child
        parent_kdir = brain / "knowledge" / "area"
        parent_kdir.mkdir(parents=True)
        child_kdir = parent_kdir / "sub"
        child_kdir.mkdir()
        (child_kdir / "doc.md").write_text("content", encoding="utf-8")

        # Create insights for child
        child_idir = brain / "insights" / "area" / "sub"
        child_idir.mkdir(parents=True)
        (child_idir / "summary.md").write_text("summary", encoding="utf-8")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/sub",
                content_hash="old",
                regen_status="idle",
            ),
        )

        # Delete the child knowledge folder
        import shutil

        shutil.rmtree(child_kdir)

        # Regen for the deleted child should clean up
        with patch("brain_sync.regen.invoke_claude"):
            asyncio.run(regen_path(brain, "area/sub"))

        assert not child_idir.exists()
        assert load_insight_state(brain, "area/sub") is None

    def test_folder_with_only_pdf_cleaned_up(self, brain):
        """A folder containing only a PDF (not in KNOWLEDGE_EXTENSIONS) is cleaned up."""
        kdir = brain / "knowledge" / "docs"
        kdir.mkdir(parents=True)
        (kdir / "report.pdf").write_bytes(b"%PDF-1.4 fake pdf content")

        with patch("brain_sync.regen.invoke_claude") as mock:
            count = asyncio.run(regen_path(brain, "docs"))

        # PDF is not a knowledge extension, so folder is treated as empty
        assert count == 0
        mock.assert_not_called()

    def test_folder_with_csv_triggers_regen(self, brain):
        """A folder containing a .csv file triggers regen."""
        kdir = brain / "knowledge" / "data"
        kdir.mkdir(parents=True)
        (kdir / "metrics.csv").write_text("a,b\n1,2", encoding="utf-8")

        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_return_summary()) as mock:
            asyncio.run(regen_path(brain, "data"))

        mock.assert_called()

    def test_folder_with_json_triggers_regen(self, brain):
        """A folder containing a .json file triggers regen."""
        kdir = brain / "knowledge" / "config"
        kdir.mkdir(parents=True)
        (kdir / "spec.json").write_text('{"key": "value"}', encoding="utf-8")

        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_return_summary()) as mock:
            asyncio.run(regen_path(brain, "config"))

        mock.assert_called()

    def test_readable_files_listed_in_prompt(self, brain):
        """Prompt lists readable files but not non-readable ones."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        (kdir / "diagram.png").write_bytes(b"\x89PNG fake")
        (kdir / "archive.zip").write_bytes(b"PK\x03\x04")

        prompt_captured = []

        async def capture_and_return(prompt: str, cwd: Path, **kwargs):
            prompt_captured.append(prompt)
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture_and_return):
            asyncio.run(regen_path(brain, "project"))

        prompt = prompt_captured[0]
        assert "doc.md" in prompt
        assert "diagram.png" in prompt
        assert "archive.zip" not in prompt

    def test_root_regeneration(self, brain):
        """Regen walks up to root and regenerates root summary."""
        # Create a leaf
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Area Doc", encoding="utf-8")

        prompts = []

        async def capture_and_return(prompt: str, cwd: Path, **kwargs):
            prompts.append(prompt)
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture_and_return):
            count = asyncio.run(regen_path(brain, "area"))

        # Should regenerate both the leaf and root
        assert count == 2
        assert len(prompts) == 2
        # First prompt is for "area", second is for root
        assert "area" in prompts[0]
        assert "(root)" in prompts[1]

    def test_unified_prompt_format(self, brain):
        """Unified prompt uses consistent format for both leaf and parent."""
        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")

        prompt_captured = []

        async def capture(prompt: str, cwd: Path, **kwargs):
            prompt_captured.append(prompt)
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture):
            asyncio.run(regen_path(brain, "leaf"))

        prompt = prompt_captured[0]
        # Unified format — no LEAF/PARENT distinction
        assert "regenerating the insight summary for knowledge area: leaf" in prompt
        assert "LEAF" not in prompt
        assert "PARENT" not in prompt


class TestIsContentDir:
    def test_excludes_sync_context(self, tmp_path):
        d = tmp_path / "_sync-context"
        d.mkdir()
        assert not _is_content_dir(d)

    def test_excludes_dotfiles(self, tmp_path):
        d = tmp_path / ".hidden"
        d.mkdir()
        assert not _is_content_dir(d)

    def test_includes_core(self, tmp_path):
        d = tmp_path / "_core"
        d.mkdir()
        assert _is_content_dir(d)

    def test_includes_normal(self, tmp_path):
        d = tmp_path / "initiatives"
        d.mkdir()
        assert _is_content_dir(d)

    def test_excludes_files(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("content", encoding="utf-8")
        assert not _is_content_dir(f)


class TestGetChildDirs:
    def test_excludes_sync_context(self, tmp_path):
        """_get_child_dirs excludes _sync-context."""
        root = tmp_path / "knowledge"
        root.mkdir()
        (root / "normal").mkdir()
        (root / "_sync-context").mkdir()
        result = _get_child_dirs(root)
        assert [p.name for p in result] == ["normal"]

    def test_includes_core(self, tmp_path):
        """_get_child_dirs includes _core."""
        root = tmp_path / "knowledge"
        root.mkdir()
        (root / "_core").mkdir()
        (root / "initiatives").mkdir()
        result = _get_child_dirs(root)
        assert [p.name for p in result] == ["_core", "initiatives"]

    def test_excludes_dot_prefixed(self, tmp_path):
        """_get_child_dirs excludes dirs starting with ."""
        root = tmp_path / "knowledge"
        root.mkdir()
        (root / "normal").mkdir()
        (root / ".git").mkdir()
        (root / ".hidden").mkdir()
        result = _get_child_dirs(root)
        assert [p.name for p in result] == ["normal"]

    def test_sorted_output(self, tmp_path):
        root = tmp_path / "knowledge"
        root.mkdir()
        (root / "zebra").mkdir()
        (root / "alpha").mkdir()
        result = _get_child_dirs(root)
        assert [p.name for p in result] == ["alpha", "zebra"]


class TestCollectChildSummaries:
    def test_reads_existing_summaries(self, brain):
        """Collects summaries from insights/ for each child dir."""
        # Create child dirs and summaries
        kdir = brain / "knowledge" / "parent"
        kdir.mkdir(parents=True)
        child_a = kdir / "alpha"
        child_a.mkdir()
        child_b = kdir / "beta"
        child_b.mkdir()

        idir_a = brain / "insights" / "parent" / "alpha"
        idir_a.mkdir(parents=True)
        (idir_a / "summary.md").write_text("Alpha summary", encoding="utf-8")

        idir_b = brain / "insights" / "parent" / "beta"
        idir_b.mkdir(parents=True)
        (idir_b / "summary.md").write_text("Beta summary", encoding="utf-8")

        result = _collect_child_summaries(brain, "parent", [child_a, child_b])
        assert result == {"alpha": "Alpha summary", "beta": "Beta summary"}

    def test_skips_missing_summaries(self, brain):
        """Skips children without summaries."""
        kdir = brain / "knowledge" / "parent"
        kdir.mkdir(parents=True)
        child_a = kdir / "alpha"
        child_a.mkdir()

        result = _collect_child_summaries(brain, "parent", [child_a])
        assert result == {}

    def test_root_path(self, brain):
        """Works correctly when current_path is empty (root)."""
        child = brain / "knowledge" / "area"
        child.mkdir(parents=True)

        idir = brain / "insights" / "area"
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("Area summary", encoding="utf-8")

        result = _collect_child_summaries(brain, "", [child])
        assert result == {"area": "Area summary"}


class TestComputeHash:
    def test_deterministic(self, tmp_path):
        """Same inputs produce same hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("content", encoding="utf-8")
        child = tmp_path / "child"
        child.mkdir()

        h1 = _compute_hash([child], {"child": "summary"}, folder, True)
        h2 = _compute_hash([child], {"child": "summary"}, folder, True)
        assert h1 == h2

    def test_sorted_dirs(self, tmp_path):
        """Dir order doesn't affect hash (sorted internally)."""
        folder = tmp_path / "docs"
        folder.mkdir()
        dir_a = tmp_path / "alpha"
        dir_a.mkdir()
        dir_b = tmp_path / "beta"
        dir_b.mkdir()

        h1 = _compute_hash([dir_a, dir_b], {}, folder, False)
        h2 = _compute_hash([dir_b, dir_a], {}, folder, False)
        assert h1 == h2

    def test_new_child_dir_changes_hash(self, tmp_path):
        """Adding a child dir changes the hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        dir_a = tmp_path / "alpha"
        dir_a.mkdir()
        dir_b = tmp_path / "beta"
        dir_b.mkdir()

        h1 = _compute_hash([dir_a], {}, folder, False)
        h2 = _compute_hash([dir_a, dir_b], {}, folder, False)
        assert h1 != h2


class TestStructuralHash:
    def test_new_child_dir_changes_parent_hash(self, brain):
        """Adding a new child dir changes the parent content hash."""
        kdir = brain / "knowledge" / "parent"
        kdir.mkdir(parents=True)
        child_a = kdir / "child-a"
        child_a.mkdir()
        (child_a / "doc.md").write_text("content", encoding="utf-8")

        # Create child summary
        idir = brain / "insights" / "parent" / "child-a"
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("summary a", encoding="utf-8")

        # First regen to establish parent hash
        with patch(
            "brain_sync.regen.invoke_claude",
            side_effect=TestRegenPath._mock_claude_return_summary(
                None,
                "# Parent V1\n\nParent summary content.",
            ),
        ):
            asyncio.run(regen_path(brain, "parent"))

        # Add a new child dir (empty for now, but structurally present)
        child_b = kdir / "child-b"
        child_b.mkdir()
        (child_b / "doc.md").write_text("content b", encoding="utf-8")
        child_b_idir = brain / "insights" / "parent" / "child-b"
        child_b_idir.mkdir(parents=True)
        (child_b_idir / "summary.md").write_text("summary b", encoding="utf-8")

        # Second regen should trigger (structural change)
        with patch(
            "brain_sync.regen.invoke_claude",
            side_effect=TestRegenPath._mock_claude_return_summary(
                None,
                "# Parent V2\n\nParent summary with both children included.",
            ),
        ) as mock:
            asyncio.run(regen_path(brain, "parent"))

        mock.assert_called()


class TestDeleteInsightState:
    def test_delete_existing(self, brain):
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="test",
                content_hash="abc",
                regen_status="idle",
            ),
        )
        assert load_insight_state(brain, "test") is not None
        delete_insight_state(brain, "test")
        assert load_insight_state(brain, "test") is None

    def test_delete_nonexistent(self, brain):
        """Deleting a non-existent entry is a no-op."""
        delete_insight_state(brain, "nonexistent")  # Should not raise


class TestFindAllContentPaths:
    def test_single_leaf(self, tmp_path):
        """Single leaf folder is found."""
        root = tmp_path / "knowledge"
        root.mkdir()
        area = root / "project"
        area.mkdir()
        (area / "doc.md").write_text("content", encoding="utf-8")

        paths = _find_all_content_paths(root)
        assert paths == ["project"]

    def test_bottom_up_order(self, tmp_path):
        """Deeper paths come before shallower ones."""
        root = tmp_path / "knowledge"
        root.mkdir()
        parent = root / "area"
        parent.mkdir()
        child = parent / "sub"
        child.mkdir()
        (child / "doc.md").write_text("content", encoding="utf-8")

        paths = _find_all_content_paths(root)
        assert paths == ["area/sub", "area"]

    def test_multi_level_tree(self, tmp_path):
        """Multi-level tree returns all content paths deepest first."""
        root = tmp_path / "knowledge"
        root.mkdir()
        # area-a/sub-1, area-a/sub-2, area-b
        area_a = root / "area-a"
        area_a.mkdir()
        sub1 = area_a / "sub-1"
        sub1.mkdir()
        (sub1 / "doc.md").write_text("content", encoding="utf-8")
        sub2 = area_a / "sub-2"
        sub2.mkdir()
        (sub2 / "doc.md").write_text("content", encoding="utf-8")
        area_b = root / "area-b"
        area_b.mkdir()
        (area_b / "doc.md").write_text("content", encoding="utf-8")

        paths = _find_all_content_paths(root)
        # sub-1, sub-2 before area-a; area-b independent
        assert paths == ["area-a/sub-1", "area-a/sub-2", "area-a", "area-b"]

    def test_excludes_sync_context_and_hidden(self, tmp_path):
        """_sync-context and hidden dirs are excluded, _core is included."""
        root = tmp_path / "knowledge"
        root.mkdir()
        core = root / "_core"
        core.mkdir()
        (core / "about.md").write_text("identity", encoding="utf-8")
        (root / "_sync-context").mkdir()
        (root / ".hidden").mkdir()
        normal = root / "visible"
        normal.mkdir()
        (normal / "doc.md").write_text("content", encoding="utf-8")

        paths = _find_all_content_paths(root)
        assert "_core" in paths
        assert "visible" in paths
        assert not any("_sync-context" in p for p in paths)
        assert not any(".hidden" in p for p in paths)

    def test_core_subfolders_included(self, tmp_path):
        """_core subfolders (Me/, Organisation/) are discovered."""
        root = tmp_path / "knowledge"
        root.mkdir()
        core = root / "_core"
        core.mkdir()
        me = core / "Me"
        me.mkdir()
        (me / "about-me.md").write_text("identity", encoding="utf-8")
        org = core / "Organisation"
        org.mkdir()
        (org / "org.md").write_text("org chart", encoding="utf-8")

        paths = _find_all_content_paths(root)
        assert "_core/Me" in paths
        assert "_core/Organisation" in paths
        assert "_core" in paths

    def test_empty_tree(self, tmp_path):
        """Empty knowledge root returns empty list."""
        root = tmp_path / "knowledge"
        root.mkdir()
        assert _find_all_content_paths(root) == []


class TestRegenAll:
    def _mock_claude_return_summary(self, content: str = "# Summary\n\nGenerated insight summary content."):
        """Create a mock invoke_claude that returns summary text."""

        async def fake_invoke(prompt: str, cwd: Path, **kwargs):
            return ClaudeResult(success=True, output=content)

        return fake_invoke

    def test_regen_all_bottom_up(self, brain):
        """regen_all processes a multi-level tree bottom-up."""
        # Create: area/sub with doc, area with overview
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "overview.md").write_text("# Overview", encoding="utf-8")
        sub = kdir / "sub"
        sub.mkdir()
        (sub / "doc.md").write_text("# Sub doc", encoding="utf-8")

        call_order = []

        async def track_and_return(prompt: str, cwd: Path, **kwargs):
            # Extract the knowledge area from prompt
            area = ""
            for line in prompt.split("\n"):
                if "regenerating the insight summary for knowledge area:" in line:
                    area = line.split(":")[-1].strip()
                    call_order.append(area)
                    break
            return ClaudeResult(success=True, output=f"# Summary for {area}\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.invoke_claude", side_effect=track_and_return):
            total = asyncio.run(regen_all(brain))

        assert total >= 2
        # sub should be processed before area (bottom-up)
        assert call_order.index("area/sub") < call_order.index("area")

    def test_regen_all_empty(self, brain):
        """regen_all with no content returns 0."""
        with patch("brain_sync.regen.invoke_claude") as mock:
            total = asyncio.run(regen_all(brain))
        assert total == 0
        mock.assert_not_called()

    def test_regen_all_cleans_orphaned_states(self, brain):
        """regen_all removes insight states for deleted knowledge dirs."""
        # Create and regen a path
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")

        # Simulate an orphaned state for a path that no longer exists
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="old/deleted",
                content_hash=None,
                summary_hash=None,
                regen_status="failed",
            ),
        )
        # Verify it exists
        assert load_insight_state(brain, "old/deleted") is not None

        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_return_summary()):
            asyncio.run(regen_all(brain))

        # Orphaned state should be cleaned up
        assert load_insight_state(brain, "old/deleted") is None


class TestRegenConfigDefaults:
    def test_max_turns_default(self):
        assert RegenConfig().max_turns == 6

    def test_effort_default(self):
        assert RegenConfig().effort == "low"

    def test_write_journal_default(self):
        assert RegenConfig().write_journal is False

    def test_load_with_new_fields(self, tmp_path):
        """Config loading handles write_journal field."""
        config_file = tmp_path / "config.json"
        config_file.write_text('{"regen": {"write_journal": true, "max_turns": 4}}', encoding="utf-8")
        with patch("brain_sync.regen.CONFIG_FILE", config_file):
            cfg = RegenConfig.load()
        assert cfg.write_journal is True
        assert cfg.max_turns == 4
        assert cfg.effort == "low"


class TestGlobalContext:
    def test_collects_core_knowledge(self, brain):
        """Global context inlines knowledge/_core files."""
        core = brain / "knowledge" / "_core"
        core.mkdir(parents=True)
        (core / "about.md").write_text("# About Me\nI am a test.", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "some/path")
        assert "knowledge/_core" in ctx
        assert "About Me" in ctx

    def test_collects_schemas(self, brain):
        """Global context inlines schemas files."""
        schemas = brain / "schemas" / "insights"
        schemas.mkdir(parents=True)
        (schemas / "summary.md").write_text("# Summary Schema", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "some/path")
        assert "schemas" in ctx
        assert "Summary Schema" in ctx

    def test_collects_insights_core(self, brain):
        """Global context inlines insights/_core files."""
        icore = brain / "insights" / "_core"
        icore.mkdir(parents=True)
        (icore / "summary.md").write_text("# Core Summary", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "some/path")
        assert "insights/_core" in ctx
        assert "Core Summary" in ctx

    def test_excludes_journal(self, brain):
        """Global context excludes insights/_core/journal."""
        icore = brain / "insights" / "_core"
        journal = icore / "journal" / "2026-03"
        journal.mkdir(parents=True)
        (journal / "2026-03-08.md").write_text("# Journal entry", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "some/path")
        assert "Journal entry" not in ctx

    def test_skips_self_for_core_regen(self, brain):
        """When regenerating _core, insights/_core/summary.md is excluded."""
        icore = brain / "insights" / "_core"
        icore.mkdir(parents=True)
        (icore / "summary.md").write_text("# Self Reference", encoding="utf-8")
        (icore / "glossary.md").write_text("# Glossary", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "_core")
        assert "Self Reference" not in ctx
        assert "Glossary" in ctx

    def test_handles_missing_dirs(self, brain):
        """Returns empty string when no global context dirs exist."""
        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "some/path")
        assert ctx == ""

    def test_cache_hit(self, brain):
        """Second call returns cached result."""
        core = brain / "knowledge" / "_core"
        core.mkdir(parents=True)
        (core / "about.md").write_text("# About", encoding="utf-8")

        invalidate_global_context_cache()
        ctx1 = _collect_global_context(brain, "path")
        ctx2 = _collect_global_context(brain, "path")
        assert ctx1 == ctx2


class TestPromptResult:
    def test_text_only_no_binary(self, brain):
        """Prompt with only text files does not mention binary files."""
        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        idir = brain / "insights" / "leaf"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain)
        assert isinstance(result, PromptResult)
        assert "binary files" not in result.text

    def test_binary_files_detected(self, brain):
        """Prompt with image files mentions them for context."""
        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        (kdir / "diagram.png").write_bytes(b"\x89PNG")
        idir = brain / "insights" / "leaf"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain)
        assert "diagram.png" in result.text


class TestJournalOptIn:
    def test_journal_absent_by_default(self, brain):
        """With default config, journal write path is not in prompt."""
        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        idir = brain / "insights" / "leaf"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain, write_journal=False)
        assert "Write the journal entry to:" not in result.text

    def test_journal_instructions_in_prompt(self, brain):
        """Journal instructions are included in the prompt via INSIGHT_INSTRUCTIONS."""
        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        idir = brain / "insights" / "leaf"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain, write_journal=True)
        assert "journal entry" in result.text.lower()


class TestPromptVersionAndContent:
    def test_prompt_version_in_instructions(self):
        """INSIGHT_INSTRUCTIONS.md contains the version marker."""
        from brain_sync.regen import _REGEN_INSTRUCTIONS

        assert "insight-v2" in _REGEN_INSTRUCTIONS

    def test_prompt_version_constant(self):
        assert PROMPT_VERSION == "insight-v2"

    def test_global_context_in_prompt(self, brain):
        """Global context is inlined in the prompt (not left for agent to discover)."""
        core = brain / "knowledge" / "_core"
        core.mkdir(parents=True)
        (core / "about.md").write_text("# Identity Info", encoding="utf-8")

        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        idir = brain / "insights" / "leaf"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain)
        assert "Identity Info" in result.text
        assert "Global Context" in result.text

    def test_no_glob_or_read_instructions(self, brain):
        """Prompt explicitly tells agent not to use Read or Glob."""
        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        idir = brain / "insights" / "leaf"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain)
        assert "Do NOT attempt to read additional files" in result.text


class TestOutputValidation:
    def test_empty_output_raises_regen_failed(self, brain):
        """Claude returning empty/tiny output raises RegenFailed."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")

        async def empty_output(prompt, cwd, **kwargs):
            return ClaudeResult(success=True, output="short")

        with patch("brain_sync.regen.invoke_claude", side_effect=empty_output):
            with pytest.raises(RegenFailed):
                asyncio.run(regen_path(brain, "project"))

    def test_valid_output_written(self, brain):
        """Valid summary output is written to summary.md by Python."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")

        async def valid_output(prompt, cwd, **kwargs):
            return ClaudeResult(success=True, output="# Summary\n\nThis is a valid summary.")

        with patch("brain_sync.regen.invoke_claude", side_effect=valid_output):
            asyncio.run(regen_path(brain, "project"))

        summary_path = brain / "insights" / "project" / "summary.md"
        assert summary_path.exists()
        assert "valid summary" in summary_path.read_text(encoding="utf-8")


class TestPreprocessing:
    """Tests for _preprocess_content()."""

    def test_strip_base64_data_uri(self):
        content = "Some text data:image/png;base64,iVBORw0KGgo= more text"
        result = _preprocess_content(content, "test.md")
        assert "iVBORw0KGgo" not in result
        assert "[image removed]" in result
        assert "Some text" in result
        assert "more text" in result

    def test_strip_base64_markdown_image(self):
        content = "![Login Screen](data:image/png;base64,iVBORw0KGgo=)\nSome text after."
        result = _preprocess_content(content, "test.md")
        assert "iVBORw0KGgo" not in result
        assert "[diagram: Login Screen]" in result
        assert "Some text after." in result

    def test_strip_base64_markdown_image_no_alt(self):
        content = "![](data:image/jpeg;base64,/9j/4AAQ=)\nAfter."
        result = _preprocess_content(content, "test.md")
        assert "[image removed]" in result

    def test_collapse_blank_lines(self):
        # 4+ newlines should collapse to 3 (2 blank lines)
        content = "line1\n\n\n\n\nline2"
        result = _preprocess_content(content, "test.md")
        assert result == "line1\n\n\nline2"
        # 3 newlines should be preserved
        content3 = "line1\n\n\nline2"
        result3 = _preprocess_content(content3, "test.md")
        assert result3 == "line1\n\n\nline2"

    def test_tables_preserved(self):
        table = "| Col1 | Col2 |\n| --- | --- |\n| val1 | val2 |"
        result = _preprocess_content(table, "test.md")
        assert result == table

    def test_base64_regex_single_line(self):
        """Regex must not consume across newlines."""
        # base64 payload on one line, important text on next line
        content = "data:image/png;base64,abc123=\nIMPORTANT: Keep this text"
        result = _preprocess_content(content, "test.md")
        assert "IMPORTANT: Keep this text" in result

    def test_no_change_clean_content(self):
        content = "# Heading\n\nSome normal markdown with no images."
        result = _preprocess_content(content, "test.md")
        assert result == content


class TestChunking:
    """Tests for _split_markdown_chunks() and related chunking logic."""

    def test_split_by_headings(self):
        content = "# Section 1\nContent 1\n\n# Section 2\nContent 2\n\n# Section 3\nContent 3"
        chunks = _split_markdown_chunks(content, target_chars=30)
        assert len(chunks) >= 2
        # Each chunk should contain at least one heading
        for chunk in chunks:
            assert "#" in chunk

    def test_split_fallback_paragraphs(self):
        # No headings, just paragraphs
        content = "Para 1 content here.\n\nPara 2 content here.\n\nPara 3 content here."
        chunks = _split_markdown_chunks(content, target_chars=30)
        assert len(chunks) >= 2

    def test_split_preserves_all_content(self):
        content = "# H1 First\nSome content here.\n\n# H1 Second\nMore content.\n\n## H2 Sub\nDeep content."
        chunks = _split_markdown_chunks(content, target_chars=40)
        # Lossless invariant (trailing newline tolerant)
        assert "".join(chunks).rstrip("\n") == content.rstrip("\n")

    def test_split_preserves_content_large(self):
        """Lossless invariant with realistic content."""
        sections = [f"## Section {i}\n{'x' * 500}\n" for i in range(20)]
        content = "\n".join(sections)
        chunks = _split_markdown_chunks(content, target_chars=2000)
        assert "".join(chunks).rstrip("\n") == content.rstrip("\n")

    def test_split_recursive_large_section(self):
        """Oversized H1 section should split at H2."""
        # One H1 with two H2s inside, each bigger than target
        content = "# Big Section\n\n## Sub A\n" + "a" * 200 + "\n\n## Sub B\n" + "b" * 200
        chunks = _split_markdown_chunks(content, target_chars=250)
        assert len(chunks) >= 2

    def test_small_content_no_split(self):
        content = "# Small\nJust a little content."
        chunks = _split_markdown_chunks(content, target_chars=1000)
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_chunk_count_guard(self, brain):
        """More than MAX_CHUNKS raises RegenFailed."""
        # Create content that will produce many chunks
        sections = [f"# Section {i}\n{'x' * 100}" for i in range(40)]
        content = "\n\n".join(sections)
        kdir = brain / "knowledge" / "huge"
        kdir.mkdir(parents=True)
        (kdir / "huge.md").write_text(content, encoding="utf-8")

        # Mock invoke_claude to return valid summary
        call_count = 0

        async def mock_invoke(prompt, cwd, **kwargs):
            nonlocal call_count
            call_count += 1
            return ClaudeResult(success=True, output="# Summary\n\nChunk summary content here.")

        # Patch _split_markdown_chunks to return >30 chunks
        fake_chunks = ["chunk"] * (MAX_CHUNKS + 1)
        with (
            patch("brain_sync.regen.invoke_claude", side_effect=mock_invoke),
            patch("brain_sync.regen._split_markdown_chunks", return_value=fake_chunks),
            patch("brain_sync.regen._preprocess_content", side_effect=lambda c, f: "x" * 200_000),
        ):
            with pytest.raises(RegenFailed, match="exceeds limit"):
                asyncio.run(regen_path(brain, "huge"))

    def test_chunk_prompt_format(self):
        prompt = _build_chunk_prompt("chunk content here", 2, 5, "prd.md", "Authentication Flow")
        assert "[Chunk 2/5" in prompt
        assert "Authentication Flow" in prompt
        assert "prd.md" in prompt
        assert "chunk content here" in prompt
        assert "[image removed]" in prompt  # placeholder instructions present

    def test_first_heading(self):
        assert _first_heading("# Top Level\nContent") == "Top Level"
        assert _first_heading("## Sub Level\nContent") == "Sub Level"
        assert _first_heading("No heading here") is None
        assert _first_heading("```\n#include <stdio.h>\n```") is None  # not a heading


class TestOversizedDetection:
    """Tests for oversized file detection in _build_prompt()."""

    def test_oversized_files_detected(self, brain):
        """Files larger than CHUNK_TARGET_CHARS go to oversized_files."""
        kdir = brain / "knowledge" / "big"
        kdir.mkdir(parents=True)
        (kdir / "huge.md").write_text("# Huge\n" + "x" * (CHUNK_TARGET_CHARS + 1000), encoding="utf-8")
        idir = brain / "insights" / "big"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("big", kdir, {}, idir, brain)
        assert result.oversized_files is not None
        assert "huge.md" in result.oversized_files
        assert "too large to inline" in result.text

    def test_small_files_not_chunked(self, brain):
        """Normal-sized files have no oversized_files."""
        kdir = brain / "knowledge" / "small"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Small doc\nSome content.", encoding="utf-8")
        idir = brain / "insights" / "small"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("small", kdir, {}, idir, brain)
        assert result.oversized_files is None

    def test_preprocessing_applied(self, brain):
        """Base64 images are stripped before size check."""
        # Content is over threshold due to base64, but under after preprocessing
        base64_payload = "A" * (CHUNK_TARGET_CHARS + 1000)
        content = f"# Doc\n![img](data:image/png;base64,{base64_payload})\nReal content."
        kdir = brain / "knowledge" / "b64"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text(content, encoding="utf-8")
        idir = brain / "insights" / "b64"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("b64", kdir, {}, idir, brain)
        # After stripping base64, should be small enough to inline
        assert result.oversized_files is None
        assert "[diagram: img]" in result.text


class TestChunkedRegenFlow:
    """End-to-end test for chunk-and-merge regen path."""

    def test_regen_path_chunked_flow(self, brain):
        """Oversized file triggers chunk calls then merge call."""
        kdir = brain / "knowledge" / "prd"
        kdir.mkdir(parents=True)
        # Create oversized file (no base64, just big)
        big_content = "\n\n".join(f"## Section {i}\n{'content ' * 100}" for i in range(30))
        (kdir / "prd.md").write_text(big_content, encoding="utf-8")

        call_count = 0

        async def mock_invoke(prompt, cwd, **kwargs):
            nonlocal call_count
            call_count += 1
            return ClaudeResult(
                success=True,
                output="# Summary\n\nThis is a thorough summary of the content.",
                input_tokens=1000,
                output_tokens=500,
            )

        with (
            patch("brain_sync.regen.invoke_claude", side_effect=mock_invoke),
            patch("brain_sync.regen.CHUNK_TARGET_CHARS", 2000),
        ):
            count = asyncio.run(regen_path(brain, "prd"))

        assert count >= 1
        # Should have been called multiple times: chunk calls + final merge
        assert call_count > 1
        summary_path = brain / "insights" / "prd" / "summary.md"
        assert summary_path.exists()

    def test_token_tracking_across_chunks(self, brain):
        """Total tokens include chunk + merge calls."""
        kdir = brain / "knowledge" / "tok"
        kdir.mkdir(parents=True)
        big_content = "\n\n".join(f"## Section {i}\n{'data ' * 100}" for i in range(20))
        (kdir / "tok.md").write_text(big_content, encoding="utf-8")

        async def mock_invoke(prompt, cwd, **kwargs):
            return ClaudeResult(
                success=True,
                output="# Summary\n\nDetailed summary of this section or merge.",
                input_tokens=500,
                output_tokens=200,
            )

        with (
            patch("brain_sync.regen.invoke_claude", side_effect=mock_invoke),
            patch("brain_sync.regen.CHUNK_TARGET_CHARS", 1500),
        ):
            asyncio.run(regen_path(brain, "tok"))

        istate = load_insight_state(brain, "tok")
        assert istate is not None
        # Total tokens should be > single call (chunks + merge)
        assert istate.input_tokens is not None
        assert istate.input_tokens > 500  # more than one call


class TestTokenBudgetEnforcement:
    """Tests for total token budget enforcement in _build_prompt()."""

    def test_many_files_triggers_chunking(self, brain):
        """20 files × ~25K chars collectively exceed budget → some deferred."""
        kdir = brain / "knowledge" / "many"
        kdir.mkdir(parents=True)
        for i in range(20):
            (kdir / f"doc{i:02d}.md").write_text(f"# Doc {i}\n" + "x" * 25_000, encoding="utf-8")
        idir = brain / "insights" / "many"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("many", kdir, {}, idir, brain)
        assert result.oversized_files is not None
        assert len(result.oversized_files) > 0
        assert len(result.text) // 3 <= MAX_PROMPT_TOKENS

    def test_largest_files_deferred_first(self, brain):
        """With a low budget, largest files get deferred first."""
        kdir = brain / "knowledge" / "vary"
        kdir.mkdir(parents=True)
        (kdir / "small.md").write_text("# Small\n" + "a" * 5_000, encoding="utf-8")
        (kdir / "medium.md").write_text("# Medium\n" + "b" * 10_000, encoding="utf-8")
        (kdir / "large.md").write_text("# Large\n" + "c" * 50_000, encoding="utf-8")
        (kdir / "huge.md").write_text("# Huge\n" + "d" * 80_000, encoding="utf-8")
        idir = brain / "insights" / "vary"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        # Set budget low enough that huge + large can't fit alongside overhead
        with patch("brain_sync.regen.MAX_PROMPT_TOKENS", 10_000):
            result = _build_prompt("vary", kdir, {}, idir, brain)

        assert result.oversized_files is not None
        assert "huge.md" in result.oversized_files
        assert "large.md" in result.oversized_files

    def test_under_budget_no_deferral(self, brain):
        """Small files totaling well under budget → no deferral."""
        kdir = brain / "knowledge" / "tiny"
        kdir.mkdir(parents=True)
        for i in range(5):
            (kdir / f"f{i}.md").write_text(f"# File {i}\nShort content.", encoding="utf-8")
        idir = brain / "insights" / "tiny"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("tiny", kdir, {}, idir, brain)
        assert result.oversized_files is None

    def test_deferred_files_have_placeholder(self, brain):
        """Deferred files show placeholder text in the prompt."""
        kdir = brain / "knowledge" / "defer"
        kdir.mkdir(parents=True)
        (kdir / "big.md").write_text("# Big\n" + "x" * 50_000, encoding="utf-8")
        idir = brain / "insights" / "defer"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        # Budget so low the file can't fit
        with patch("brain_sync.regen.MAX_PROMPT_TOKENS", 5_000):
            result = _build_prompt("defer", kdir, {}, idir, brain)

        assert result.oversized_files is not None
        assert "big.md" in result.oversized_files
        assert "too large to inline" in result.text

    def test_exact_budget_fit(self, brain):
        """File that exactly fits the remaining budget is not deferred."""
        kdir = brain / "knowledge" / "exact"
        kdir.mkdir(parents=True)
        # Create a small file that fits easily
        (kdir / "fits.md").write_text("# Fits\nok", encoding="utf-8")
        idir = brain / "insights" / "exact"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("exact", kdir, {}, idir, brain)
        assert result.oversized_files is None
        assert "fits.md" in result.text

    def test_all_files_deferred(self, brain):
        """All files exceed remaining budget after overhead → 0 inlined."""
        kdir = brain / "knowledge" / "allbig"
        kdir.mkdir(parents=True)
        for i in range(3):
            (kdir / f"big{i}.md").write_text(f"# Big {i}\n" + "z" * 30_000, encoding="utf-8")
        idir = brain / "insights" / "allbig"
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        # Budget so low nothing fits
        with patch("brain_sync.regen.MAX_PROMPT_TOKENS", 3_000):
            result = _build_prompt("allbig", kdir, {}, idir, brain)

        assert result.oversized_files is not None
        assert len(result.oversized_files) == 3
        # No file content blocks in prompt (only placeholders)
        assert "```\n" not in result.text.split("---")[-1]

    def test_end_to_end_many_files(self, brain):
        """Integration: many files with low budget triggers chunk-and-merge."""
        kdir = brain / "knowledge" / "e2e"
        kdir.mkdir(parents=True)
        for i in range(10):
            (kdir / f"file{i:02d}.md").write_text(
                f"# File {i}\n" + "content " * 500, encoding="utf-8"
            )

        call_count = 0

        async def mock_invoke(prompt, cwd, **kwargs):
            nonlocal call_count
            call_count += 1
            return ClaudeResult(
                success=True,
                output="# Summary\n\nThis is a thorough summary of the content.",
                input_tokens=1000,
                output_tokens=500,
            )

        with (
            patch("brain_sync.regen.invoke_claude", side_effect=mock_invoke),
            patch("brain_sync.regen.MAX_PROMPT_TOKENS", 5_000),
        ):
            count = asyncio.run(regen_path(brain, "e2e"))

        assert count >= 1
        # Multiple calls: chunk calls for deferred files + final merge
        assert call_count > 1
        summary_path = brain / "insights" / "e2e" / "summary.md"
        assert summary_path.exists()

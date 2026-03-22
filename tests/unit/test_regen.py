"""Tests for the insight regeneration engine."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from brain_sync.application.insights import InsightState, delete_insight_state, load_insight_state, save_insight_state
from brain_sync.brain.fileops import atomic_write_bytes
from brain_sync.brain.layout import area_insights_dir, area_journal_dir, area_summary_path, brain_manifest_path
from brain_sync.brain.tree import find_all_content_paths as _find_all_content_paths
from brain_sync.brain.tree import normalize_path
from brain_sync.regen import (
    RegenFailed,
    classify_folder_change,
    regen_all,
    regen_path,
)
from brain_sync.regen.engine import (
    _REGEN_INSTRUCTIONS,
    CHUNK_TARGET_CHARS,
    MAX_CHUNKS,
    MAX_PROMPT_TOKENS,
    PROMPT_VERSION,
    ClaudeResult,
    PromptResult,
    RegenConfig,
    _build_chunk_prompt,
    _build_prompt,
    _collect_child_summaries,
    _collect_global_context,
    _compute_content_hash,
    _compute_structure_hash,
    _first_heading,
    _get_child_dirs,
    _is_content_dir,
    _parse_stream_json,
    _parse_structured_output,
    _preprocess_content,
    _split_markdown_chunks,
    _write_journal_entry,
    classify_change,
    invalidate_global_context_cache,
    regen_single_folder,
    text_similarity,
)
from brain_sync.regen.topology import compute_waves, parent_dirty_reason, propagates_up
from brain_sync.runtime.repository import _connect
from brain_sync.util.retry import claude_breaker

pytestmark = pytest.mark.unit


def _long_relative_path(root: Path, filename: str, *, min_length: int = 280) -> Path:
    parts: list[str] = []
    index = 0
    while len(str(root / Path(*parts) / filename)) <= min_length:
        parts.append(f"segment-{index:02d}-with-extra-length-for-windows")
        index += 1
    return Path(*parts) / filename


@pytest.fixture(autouse=True)
def _reset_breaker():
    """Reset the global circuit breaker between tests."""
    claude_breaker.reset()
    yield
    claude_breaker.reset()


@pytest.fixture(autouse=True)
def _skip_retry_sleep():
    """Skip retry backoff sleeps in tests."""
    with patch("brain_sync.util.retry.asyncio.sleep", new_callable=AsyncMock):
        yield


@pytest.fixture
def brain(tmp_path):
    """Create a minimal brain structure with SQLite initialized."""
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    brain_manifest = brain_manifest_path(root)
    brain_manifest.parent.mkdir(parents=True, exist_ok=True)
    brain_manifest.write_text(json.dumps({"version": 1}) + "\n", encoding="utf-8")
    # Initialize SQLite
    conn = _connect(root)
    conn.close()
    return root


def managed_insights(root: Path, knowledge_path: str = "") -> Path:
    return area_insights_dir(root, knowledge_path)


def managed_summary(root: Path, knowledge_path: str = "") -> Path:
    return area_summary_path(root, knowledge_path)


def managed_journal(root: Path, knowledge_path: str = "") -> Path:
    return area_journal_dir(root, knowledge_path)


class TestComputeContentHash:
    """Tests for _compute_content_hash (rename-insensitive)."""

    def test_empty_folder(self, tmp_path):
        folder = tmp_path / "empty"
        folder.mkdir()
        h = _compute_content_hash({}, folder, False)
        assert isinstance(h, str)
        assert len(h) == 64  # sha256 hex

    def test_deterministic(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        (folder / "b.md").write_text("world", encoding="utf-8")
        h1 = _compute_content_hash({}, folder, True)
        h2 = _compute_content_hash({}, folder, True)
        assert h1 == h2

    def test_changes_with_content(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("v1", encoding="utf-8")
        h1 = _compute_content_hash({}, folder, True)
        (folder / "a.md").write_text("v2", encoding="utf-8")
        h2 = _compute_content_hash({}, folder, True)
        assert h1 != h2

    def test_text_line_endings_do_not_change_hash(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_bytes(b"hello\r\nworld\r\n")
        h1 = _compute_content_hash({}, folder, True)
        (folder / "a.md").write_bytes(b"hello\nworld\n")
        h2 = _compute_content_hash({}, folder, True)
        assert h1 == h2

    def test_binary_line_endings_still_affect_hash(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "diagram.png").write_bytes(b"\x89PNG\r\nchunk")
        h1 = _compute_content_hash({}, folder, True)
        (folder / "diagram.png").write_bytes(b"\x89PNG\nchunk")
        h2 = _compute_content_hash({}, folder, True)
        assert h1 != h2

    def test_ignores_non_readable_extensions(self, tmp_path):
        """Files with extensions not in READABLE_EXTENSIONS are ignored."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = _compute_content_hash({}, folder, True)
        (folder / "archive.zip").write_bytes(b"PK\x03\x04")
        (folder / "binary.exe").write_bytes(b"\x00\x01")
        h2 = _compute_content_hash({}, folder, True)
        assert h1 == h2

    def test_includes_readable_non_md_files(self, tmp_path):
        """Files with readable extensions (txt, pdf, etc.) are included in hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = _compute_content_hash({}, folder, True)
        (folder / "notes.txt").write_text("included now", encoding="utf-8")
        h2 = _compute_content_hash({}, folder, True)
        assert h1 != h2

    def test_ignores_hidden_and_underscore_files(self, tmp_path):
        """Files starting with _ or . are ignored regardless of extension."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = _compute_content_hash({}, folder, True)
        (folder / ".hidden.md").write_text("hidden", encoding="utf-8")
        (folder / "_private.md").write_text("private", encoding="utf-8")
        h2 = _compute_content_hash({}, folder, True)
        assert h1 == h2

    def test_new_file_changes_hash(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = _compute_content_hash({}, folder, True)
        (folder / "b.md").write_text("new file", encoding="utf-8")
        h2 = _compute_content_hash({}, folder, True)
        assert h1 != h2

    def test_rename_does_not_change_content_hash(self, tmp_path):
        """Renaming a file (same content) should NOT change the content hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = _compute_content_hash({}, folder, True)
        (folder / "a.md").rename(folder / "b.md")
        h2 = _compute_content_hash({}, folder, True)
        assert h1 == h2

    def test_child_summary_sorted_by_content(self, tmp_path):
        """Child summaries sorted by content, not key — rename doesn't change hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        sums_a = {"alpha": "summary-x", "beta": "summary-y"}
        sums_b = {"gamma": "summary-x", "delta": "summary-y"}
        h1 = _compute_content_hash(sums_a, folder, False)
        h2 = _compute_content_hash(sums_b, folder, False)
        assert h1 == h2


class TestComputeStructureHash:
    """Tests for _compute_structure_hash (rename-sensitive)."""

    def test_rename_changes_structure_hash(self, tmp_path):
        """Renaming a file changes structure hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        dir_list: list[Path] = []
        h1 = _compute_structure_hash(dir_list, folder, True)
        (folder / "a.md").rename(folder / "b.md")
        h2 = _compute_structure_hash(dir_list, folder, True)
        assert h1 != h2

    def test_dir_order_irrelevant(self, tmp_path):
        """Dir order doesn't affect hash (sorted internally)."""
        folder = tmp_path / "docs"
        folder.mkdir()
        dir_a = tmp_path / "alpha"
        dir_a.mkdir()
        dir_b = tmp_path / "beta"
        dir_b.mkdir()
        h1 = _compute_structure_hash([dir_a, dir_b], folder, False)
        h2 = _compute_structure_hash([dir_b, dir_a], folder, False)
        assert h1 == h2

    def test_new_child_dir_changes_hash(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        dir_a = tmp_path / "alpha"
        dir_a.mkdir()
        dir_b = tmp_path / "beta"
        dir_b.mkdir()
        h1 = _compute_structure_hash([dir_a], folder, False)
        h2 = _compute_structure_hash([dir_a, dir_b], folder, False)
        assert h1 != h2


class TestClassifyFolderChange:
    """Tests for the classify_folder_change() guard used by the watcher."""

    def test_content_when_no_insight_state(self, brain):
        """Returns 'content' when no prior insight state exists."""
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("hello", encoding="utf-8")
        event, _, _ = classify_folder_change(brain, "area")
        assert event.change_type == "content"

    def test_content_when_dir_missing(self, brain):
        """Returns 'content' when knowledge directory doesn't exist."""
        event, _, _ = classify_folder_change(brain, "nonexistent")
        assert event.change_type == "content"

    def test_none_when_hash_matches(self, brain):
        """Returns 'none' when both hashes match cached insight state."""
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("hello", encoding="utf-8")

        # Compute hashes the same way regen would
        child_dirs = _get_child_dirs(kdir)
        child_summaries = _collect_child_summaries(brain, "area", child_dirs)
        content_hash = _compute_content_hash(child_summaries, kdir, True)
        structure_hash = _compute_structure_hash(child_dirs, kdir, True)

        istate = InsightState(knowledge_path="area", content_hash=content_hash, structure_hash=structure_hash)
        save_insight_state(brain, istate)

        event, _, _ = classify_folder_change(brain, "area")
        assert event.change_type == "none"

    def test_content_when_file_added(self, brain):
        """Returns 'content' when a new file is added after state was saved."""
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("hello", encoding="utf-8")

        child_dirs = _get_child_dirs(kdir)
        child_summaries = _collect_child_summaries(brain, "area", child_dirs)
        content_hash = _compute_content_hash(child_summaries, kdir, True)
        structure_hash = _compute_structure_hash(child_dirs, kdir, True)
        istate = InsightState(knowledge_path="area", content_hash=content_hash, structure_hash=structure_hash)
        save_insight_state(brain, istate)

        (kdir / "new.md").write_text("new content", encoding="utf-8")
        event, _, _ = classify_folder_change(brain, "area")
        assert event.change_type == "content"

    def test_content_when_file_modified(self, brain):
        """Returns 'content' when file content changes after state was saved."""
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("original", encoding="utf-8")

        child_dirs = _get_child_dirs(kdir)
        child_summaries = _collect_child_summaries(brain, "area", child_dirs)
        content_hash = _compute_content_hash(child_summaries, kdir, True)
        structure_hash = _compute_structure_hash(child_dirs, kdir, True)
        istate = InsightState(knowledge_path="area", content_hash=content_hash, structure_hash=structure_hash)
        save_insight_state(brain, istate)

        (kdir / "doc.md").write_text("modified", encoding="utf-8")
        event, _, _ = classify_folder_change(brain, "area")
        assert event.change_type == "content"

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_none_when_overlong_path_hash_matches(self, brain):
        rel = _long_relative_path(brain / "knowledge", "doc.md")
        kdir = (brain / "knowledge" / rel).parent
        atomic_write_bytes(kdir / "doc.md", b"hello")

        child_dirs = _get_child_dirs(kdir)
        knowledge_path = normalize_path(kdir.relative_to(brain / "knowledge"))
        child_summaries = _collect_child_summaries(brain, knowledge_path, child_dirs)
        content_hash = _compute_content_hash(child_summaries, kdir, True)
        structure_hash = _compute_structure_hash(child_dirs, kdir, True)
        save_insight_state(
            brain,
            InsightState(knowledge_path=knowledge_path, content_hash=content_hash, structure_hash=structure_hash),
        )

        event, _, _ = classify_folder_change(brain, knowledge_path)
        assert event.change_type == "none"

    def test_rename_when_file_renamed(self, brain):
        """Returns 'rename' when a file is renamed but content is unchanged."""
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "old-name.md").write_text("hello", encoding="utf-8")

        child_dirs = _get_child_dirs(kdir)
        child_summaries = _collect_child_summaries(brain, "area", child_dirs)
        content_hash = _compute_content_hash(child_summaries, kdir, True)
        structure_hash = _compute_structure_hash(child_dirs, kdir, True)
        istate = InsightState(knowledge_path="area", content_hash=content_hash, structure_hash=structure_hash)
        save_insight_state(brain, istate)

        (kdir / "old-name.md").rename(kdir / "new-name.md")
        event, _, _ = classify_folder_change(brain, "area")
        assert event.change_type == "rename"
        assert event.structural is True

    def test_backfill_returns_none_after_migration(self, brain):
        """Pre-v18 state (structure_hash=None) with existing summary returns 'none' and backfills."""
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("hello", encoding="utf-8")

        # Create existing summary on disk
        idir = managed_insights(brain, "area")
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("# Existing Summary", encoding="utf-8")

        # Save pre-v18 state: has content_hash but no structure_hash
        istate = InsightState(knowledge_path="area", content_hash="old-hash-value", structure_hash=None)
        save_insight_state(brain, istate)

        event, new_content_hash, new_structure_hash = classify_folder_change(brain, "area")
        assert event.change_type == "none"

        # Verify state was backfilled: content_hash updated to new algorithm, structure_hash set
        loaded = load_insight_state(brain, "area")
        assert loaded is not None
        assert loaded.content_hash == new_content_hash
        assert loaded.content_hash != "old-hash-value"
        assert loaded.structure_hash == new_structure_hash
        assert loaded.structure_hash is not None

    def test_no_backfill_without_summary(self, brain):
        """Pre-v18 state without summary.md on disk falls through to normal classify."""
        kdir = brain / "knowledge" / "area"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("hello", encoding="utf-8")

        # Save pre-v18 state: has content_hash but no structure_hash, NO summary on disk
        istate = InsightState(knowledge_path="area", content_hash="old-hash-value", structure_hash=None)
        save_insight_state(brain, istate)

        event, _, _ = classify_folder_change(brain, "area")
        # Old content_hash won't match new content_hash → "content" change
        assert event.change_type == "content"


class TestClassifyChange:
    """Unit tests for classify_change() decision function."""

    def test_none_when_both_unchanged(self):
        event = classify_change("aaa", "aaa", "bbb", "bbb")
        assert event.change_type == "none"
        assert event.structural is False

    def test_rename_when_only_structure_changed(self):
        event = classify_change("aaa", "aaa", "bbb", "ccc")
        assert event.change_type == "rename"
        assert event.structural is True

    def test_content_when_content_changed(self):
        event = classify_change("aaa", "xxx", "bbb", "bbb")
        assert event.change_type == "content"
        assert event.structural is False

    def test_content_when_both_changed(self):
        event = classify_change("aaa", "xxx", "bbb", "yyy")
        assert event.change_type == "content"
        assert event.structural is False

    def test_content_when_old_is_none(self):
        event = classify_change(None, "aaa", None, "bbb")
        assert event.change_type == "content"


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
        assert loaded is not None
        assert loaded.content_hash == "v2"
        assert loaded.regen_status == "running"


class TestRegenPath:
    """Tests for the regen_path loop with mocked Claude CLI."""

    @staticmethod
    def _mock_claude_return_summary(content: str = "# Test Summary\n\nGenerated insight summary content."):
        """Create a mock invoke_claude that returns summary text."""

        async def fake_invoke(prompt: str, cwd: Path, **kwargs):
            return ClaudeResult(success=True, output=content)

        return fake_invoke

    def test_leaf_regen_creates_summary(self, brain):
        """Leaf regen with md files creates summary."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Project Doc\nSome content.", encoding="utf-8")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude_return_summary()):
            count = asyncio.run(regen_path(brain, "project"))

        assert count >= 1
        summary = managed_summary(brain, "project")
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

        # Pre-populate insight state with matching hashes
        child_dirs = _get_child_dirs(kdir)
        child_summaries = _collect_child_summaries(brain, "project", child_dirs)
        content_hash = _compute_content_hash(child_summaries, kdir, True)
        structure_hash = _compute_structure_hash(child_dirs, kdir, True)

        save_insight_state(
            brain,
            InsightState(
                knowledge_path="project",
                content_hash=content_hash,
                summary_hash="existing",
                structure_hash=structure_hash,
                regen_status="idle",
            ),
        )

        with patch("brain_sync.regen.engine.invoke_claude") as mock_claude:
            count = asyncio.run(regen_path(brain, "project"))

        assert count == 0
        mock_claude.assert_not_called()

    def test_similarity_guard_discards_rewrite(self, brain):
        """If new summary is >97% similar, it's discarded."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc Content V2", encoding="utf-8")

        idir = managed_insights(brain, "project")
        idir.mkdir(parents=True)
        old_summary = "# Project Summary\n\nThis is the existing summary about the project."
        (idir / "summary.md").write_text(old_summary, encoding="utf-8")

        # Mock Claude to write an almost-identical summary
        near_identical = "# Project Summary\n\nThis is the existing summary about the project ."

        with patch(
            "brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude_return_summary(near_identical)
        ):
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

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=fail_invoke):
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

            idir = managed_insights(brain, f"parent/{child}")
            idir.mkdir(parents=True)
            (idir / "summary.md").write_text(f"# {child} Summary\nDetails.", encoding="utf-8")

        # Parent knowledge dir exists (it has subdirs)
        (brain / "knowledge" / "parent").mkdir(exist_ok=True)

        prompt_captured = []

        async def capture_and_return(prompt: str, cwd: Path, **kwargs):
            prompt_captured.append(prompt)
            return ClaudeResult(success=True, output="# Parent Summary\nOverview.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=capture_and_return):
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
        idir = managed_insights(brain, "deleted")
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

        with patch("brain_sync.regen.engine.invoke_claude") as mock:
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
        idir = managed_insights(brain, "empty")
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

        with patch("brain_sync.regen.engine.invoke_claude") as mock:
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
        child_idir = managed_insights(brain, "initiative/meetings")
        child_idir.mkdir(parents=True)
        (child_idir / "summary.md").write_text("# Meetings Summary", encoding="utf-8")

        prompt_captured = []

        async def capture_and_return(prompt: str, cwd: Path, **kwargs):
            prompt_captured.append(prompt)
            return ClaudeResult(success=True, output="# Initiative Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=capture_and_return):
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
        child_idir = managed_insights(brain, "initiative/meetings")
        child_idir.mkdir(parents=True)
        (child_idir / "summary.md").write_text("# Meetings Summary", encoding="utf-8")

        # First regen
        with patch(
            "brain_sync.regen.engine.invoke_claude",
            side_effect=self._mock_claude_return_summary("# Summary V1\n\nInitiative overview content."),
        ):
            asyncio.run(regen_path(brain, "initiative"))

        # Change direct file
        (kdir / "overview.md").write_text("# V2 — significant change", encoding="utf-8")

        # Second regen should trigger (hash changed)
        with patch(
            "brain_sync.regen.engine.invoke_claude",
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
        idir = managed_insights(brain, "parent/child")
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

        with patch("brain_sync.regen.engine.invoke_claude"):
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
        child_idir = managed_insights(brain, "area/sub")
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
        with patch("brain_sync.regen.engine.invoke_claude"):
            asyncio.run(regen_path(brain, "area/sub"))

        assert not child_idir.exists()
        assert load_insight_state(brain, "area/sub") is None

    def test_folder_with_only_pdf_cleaned_up(self, brain):
        """A folder containing only a PDF (not in KNOWLEDGE_EXTENSIONS) is cleaned up."""
        kdir = brain / "knowledge" / "docs"
        kdir.mkdir(parents=True)
        (kdir / "report.pdf").write_bytes(b"%PDF-1.4 fake pdf content")

        with patch("brain_sync.regen.engine.invoke_claude") as mock:
            count = asyncio.run(regen_path(brain, "docs"))

        # PDF is not a knowledge extension, so folder is treated as empty
        assert count == 0
        mock.assert_not_called()

    def test_folder_with_csv_triggers_regen(self, brain):
        """A folder containing a .csv file triggers regen."""
        kdir = brain / "knowledge" / "data"
        kdir.mkdir(parents=True)
        (kdir / "metrics.csv").write_text("a,b\n1,2", encoding="utf-8")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude_return_summary()) as mock:
            asyncio.run(regen_path(brain, "data"))

        mock.assert_called()

    def test_folder_with_json_triggers_regen(self, brain):
        """A folder containing a .json file triggers regen."""
        kdir = brain / "knowledge" / "config"
        kdir.mkdir(parents=True)
        (kdir / "spec.json").write_text('{"key": "value"}', encoding="utf-8")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude_return_summary()) as mock:
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

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=capture_and_return):
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

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=capture_and_return):
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

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=capture):
            asyncio.run(regen_path(brain, "leaf"))

        prompt = prompt_captured[0]
        # Unified format — no LEAF/PARENT distinction
        assert "regenerating the insight summary for knowledge area: leaf" in prompt
        assert "LEAF" not in prompt
        assert "PARENT" not in prompt

    def test_backfill_skips_regen_after_migration(self, brain):
        """Pre-v18 state with existing summary → no Claude call, hashes updated, returns 0."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")

        # Create existing summary
        idir = managed_insights(brain, "project")
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("# Existing Summary", encoding="utf-8")

        # Save pre-v18 state: content_hash set, structure_hash=None
        istate = InsightState(
            knowledge_path="project", content_hash="old-hash-value", structure_hash=None, regen_status="idle"
        )
        save_insight_state(brain, istate)

        with patch("brain_sync.regen.engine.invoke_claude") as mock_claude:
            count = asyncio.run(regen_path(brain, "project", max_depth=1))

        assert count == 0
        mock_claude.assert_not_called()

        # Verify state: content_hash updated to new algorithm, structure_hash set
        loaded = load_insight_state(brain, "project")
        assert loaded is not None
        assert loaded.content_hash != "old-hash-value"
        assert loaded.content_hash is not None
        assert loaded.structure_hash is not None

    def test_backfill_ancestor_not_regenerated_on_second_visit(self, brain):
        """Leaf backfill must not walk up into a pre-v18 ancestor."""
        # Create two leaf folders under a shared parent
        for leaf in ("parent/leaf-a", "parent/leaf-b"):
            kdir = brain / "knowledge" / leaf
            kdir.mkdir(parents=True)
            (kdir / "doc.md").write_text(f"content for {leaf}", encoding="utf-8")
            idir = managed_insights(brain, leaf)
            idir.mkdir(parents=True)
            (idir / "summary.md").write_text(f"# Summary for {leaf}", encoding="utf-8")
            save_insight_state(
                brain,
                InsightState(knowledge_path=leaf, content_hash="old-hash", structure_hash=None, regen_status="idle"),
            )

        # Parent also has pre-v18 state
        pdir = managed_insights(brain, "parent")
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "summary.md").write_text("# Parent Summary", encoding="utf-8")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="parent", content_hash="old-parent-hash", structure_hash=None, regen_status="idle"
            ),
        )

        with patch("brain_sync.regen.engine.invoke_claude") as mock_claude:
            count_a = asyncio.run(regen_path(brain, "parent/leaf-a", max_depth=2))
            count_b = asyncio.run(regen_path(brain, "parent/leaf-b", max_depth=2))

        # Neither call should have invoked Claude — leaves backfilled and stopped
        assert count_a == 0
        assert count_b == 0
        mock_claude.assert_not_called()

        # Parent should remain untouched because metadata-only backfill does not
        # change a parent-visible input under the shared propagation matrix.
        loaded_parent = load_insight_state(brain, "parent")
        assert loaded_parent is not None
        assert loaded_parent.content_hash == "old-parent-hash"
        assert loaded_parent.structure_hash is None

    def test_local_structure_only_rename_does_not_walk_up_to_parent(self, brain):
        """Renaming a file inside a leaf should stop at that leaf."""
        parent = brain / "knowledge" / "parent"
        parent.mkdir(parents=True)
        (parent / "overview.md").write_text("# Parent", encoding="utf-8")
        leaf = parent / "leaf"
        leaf.mkdir()
        (leaf / "old-name.md").write_text("# Leaf", encoding="utf-8")

        async def fake_invoke(prompt: str, cwd: Path, **kwargs):
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=fake_invoke):
            asyncio.run(regen_single_folder(brain, "parent"))
            asyncio.run(regen_single_folder(brain, "parent/leaf"))

        parent_before = load_insight_state(brain, "parent")
        assert parent_before is not None

        (leaf / "old-name.md").rename(leaf / "new-name.md")

        with patch("brain_sync.regen.engine.invoke_claude") as mock_claude:
            count = asyncio.run(regen_path(brain, "parent/leaf", max_depth=2))

        parent_after = load_insight_state(brain, "parent")

        assert count == 0
        mock_claude.assert_not_called()
        assert parent_after is not None
        assert parent_after.content_hash == parent_before.content_hash
        assert parent_after.summary_hash == parent_before.summary_hash
        assert parent_after.structure_hash == parent_before.structure_hash


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

        idir_a = managed_insights(brain, "parent/alpha")
        idir_a.mkdir(parents=True)
        (idir_a / "summary.md").write_text("Alpha summary", encoding="utf-8")

        idir_b = managed_insights(brain, "parent/beta")
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

        idir = managed_insights(brain, "area")
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("Area summary", encoding="utf-8")

        result = _collect_child_summaries(brain, "", [child])
        assert result == {"area": "Area summary"}


class TestComputeHashes:
    """Tests for the split content/structure hash functions together."""

    def test_content_hash_deterministic(self, tmp_path):
        """Same inputs produce same content hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("content", encoding="utf-8")

        h1 = _compute_content_hash({"child": "summary"}, folder, True)
        h2 = _compute_content_hash({"child": "summary"}, folder, True)
        assert h1 == h2

    def test_structure_hash_sorted_dirs(self, tmp_path):
        """Dir order doesn't affect structure hash (sorted internally)."""
        folder = tmp_path / "docs"
        folder.mkdir()
        dir_a = tmp_path / "alpha"
        dir_a.mkdir()
        dir_b = tmp_path / "beta"
        dir_b.mkdir()

        h1 = _compute_structure_hash([dir_a, dir_b], folder, False)
        h2 = _compute_structure_hash([dir_b, dir_a], folder, False)
        assert h1 == h2

    def test_new_child_dir_changes_structure_hash(self, tmp_path):
        """Adding a child dir changes the structure hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        dir_a = tmp_path / "alpha"
        dir_a.mkdir()
        dir_b = tmp_path / "beta"
        dir_b.mkdir()

        h1 = _compute_structure_hash([dir_a], folder, False)
        h2 = _compute_structure_hash([dir_a, dir_b], folder, False)
        assert h1 != h2

    def test_child_rename_changes_structure_not_content(self, tmp_path):
        """Renaming a child dir changes structure hash but not content hash."""
        folder = tmp_path / "docs"
        folder.mkdir()
        dir_a = tmp_path / "alpha"
        dir_a.mkdir()

        # Same summary content, different key names
        sums_before = {"alpha": "child summary"}
        sh1 = _compute_structure_hash([dir_a], folder, False)
        ch1 = _compute_content_hash(sums_before, folder, False)

        dir_a_renamed = tmp_path / "renamed"
        dir_a.rename(dir_a_renamed)

        sums_after = {"renamed": "child summary"}
        sh2 = _compute_structure_hash([dir_a_renamed], folder, False)
        ch2 = _compute_content_hash(sums_after, folder, False)

        assert sh1 != sh2  # structure changed
        assert ch1 == ch2  # content unchanged


class TestStructuralHash:
    def test_new_child_dir_changes_parent_hash(self, brain):
        """Adding a new child dir changes the parent content hash."""
        kdir = brain / "knowledge" / "parent"
        kdir.mkdir(parents=True)
        child_a = kdir / "child-a"
        child_a.mkdir()
        (child_a / "doc.md").write_text("content", encoding="utf-8")

        # Create child summary
        idir = managed_insights(brain, "parent/child-a")
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("summary a", encoding="utf-8")

        # First regen to establish parent hash
        with patch(
            "brain_sync.regen.engine.invoke_claude",
            side_effect=TestRegenPath._mock_claude_return_summary(
                "# Parent V1\n\nParent summary content.",
            ),
        ):
            asyncio.run(regen_path(brain, "parent"))

        # Add a new child dir (empty for now, but structurally present)
        child_b = kdir / "child-b"
        child_b.mkdir()
        (child_b / "doc.md").write_text("content b", encoding="utf-8")
        child_b_idir = managed_insights(brain, "parent/child-b")
        child_b_idir.mkdir(parents=True)
        (child_b_idir / "summary.md").write_text("summary b", encoding="utf-8")

        # Second regen should trigger (structural change)
        with patch(
            "brain_sync.regen.engine.invoke_claude",
            side_effect=TestRegenPath._mock_claude_return_summary(
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

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=track_and_return):
            total = asyncio.run(regen_all(brain))

        assert total >= 2
        # sub should be processed before area (bottom-up)
        assert call_order.index("area/sub") < call_order.index("area")

    def test_regen_all_empty(self, brain):
        """regen_all with no content returns 0."""
        with patch("brain_sync.regen.engine.invoke_claude") as mock:
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

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude_return_summary()):
            asyncio.run(regen_all(brain))

        # Orphaned state should be cleaned up
        assert load_insight_state(brain, "old/deleted") is None


class TestRegenConfigDefaults:
    def test_max_turns_default(self):
        assert RegenConfig().max_turns == 6

    def test_effort_default(self):
        assert RegenConfig().effort == "low"

    def test_load_with_new_fields(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text('{"regen": {"max_turns": 4}}', encoding="utf-8")
        with patch("brain_sync.runtime.config.CONFIG_FILE", config_file):
            cfg = RegenConfig.load()
        assert cfg.max_turns == 4
        assert cfg.effort == "low"

    def test_load_ignores_removed_journal_fields(self, tmp_path):
        config_file = tmp_path / "config.json"
        config_file.write_text(
            '{"regen": {"disable_journal": true, "write_journal": false, "max_turns": 4}}',
            encoding="utf-8",
        )
        with patch("brain_sync.runtime.config.CONFIG_FILE", config_file):
            cfg = RegenConfig.load()
        assert cfg.max_turns == 4
        assert not hasattr(cfg, "write_journal")


class TestGlobalContext:
    def test_non_core_uses_core_summary_only(self, brain):
        """Non-_core regen sees only distilled _core meaning."""
        core = brain / "knowledge" / "_core"
        core.mkdir(parents=True)
        (core / "about.md").write_text("# About Me\nI am a test.", encoding="utf-8")
        icore = managed_insights(brain, "_core")
        icore.mkdir(parents=True)
        (icore / "summary.md").write_text("# Core Summary\nShared orientation.", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "some/path")
        assert "knowledge/_core/.brain-sync/insights/summary.md" in ctx
        assert "Core Summary" in ctx
        assert "About Me" not in ctx

    def test_ignores_legacy_schemas(self, brain):
        """Legacy top-level schemas files are ignored by v23 global context."""
        schemas = brain / "schemas" / "insights"
        schemas.mkdir(parents=True)
        (schemas / "summary.md").write_text("# Summary Schema", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "some/path")
        assert "schemas" not in ctx
        assert "Summary Schema" not in ctx

    def test_non_core_does_not_fallback_to_raw_core(self, brain):
        """Non-_core regen gets no global context when _core summary is missing."""
        core = brain / "knowledge" / "_core"
        core.mkdir(parents=True)
        (core / "about.md").write_text("# About Me\nI am a test.", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "some/path")
        assert ctx == ""

    def test_core_regen_uses_raw_core_only(self, brain):
        """_core regen inlines raw _core files and excludes managed insight files."""
        core = brain / "knowledge" / "_core"
        core.mkdir(parents=True)
        (core / "about.md").write_text("# About Me\nI am a test.", encoding="utf-8")
        icore = managed_insights(brain, "_core")
        icore.mkdir(parents=True)
        (icore / "summary.md").write_text("# Core Summary", encoding="utf-8")
        (icore / "glossary.md").write_text("# Glossary", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "_core")
        assert "knowledge/_core" in ctx
        assert "About Me" in ctx
        assert "Core Summary" not in ctx
        assert "Glossary" not in ctx

    def test_excludes_journal(self, brain):
        """Non-_core global context excludes co-located _core journal entries."""
        icore = managed_insights(brain, "_core")
        icore.mkdir(parents=True)
        (icore / "summary.md").write_text("# Core Summary", encoding="utf-8")
        journal = managed_journal(brain, "_core") / "2026-03"
        journal.mkdir(parents=True)
        (journal / "2026-03-08.md").write_text("# Journal entry", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "some/path")
        assert "Core Summary" in ctx
        assert "Journal entry" not in ctx

    def test_core_regen_does_not_inline_managed_summary(self, brain):
        """When regenerating _core, managed _core summaries are excluded."""
        core = brain / "knowledge" / "_core"
        core.mkdir(parents=True)
        (core / "about.md").write_text("# About Me", encoding="utf-8")
        icore = managed_insights(brain, "_core")
        icore.mkdir(parents=True)
        (icore / "summary.md").write_text("# Self Reference", encoding="utf-8")

        invalidate_global_context_cache()
        ctx = _collect_global_context(brain, "_core")
        assert "Self Reference" not in ctx
        assert "About Me" in ctx

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
        idir = managed_insights(brain, "leaf")
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
        idir = managed_insights(brain, "leaf")
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain)
        assert "diagram.png" in result.text


class TestJournalPrompting:
    def test_journal_present_by_default(self, brain):
        """Default config includes journal instructions and structured output tags."""
        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        idir = managed_insights(brain, "leaf")
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain)
        assert "journal entry" in result.text.lower()
        assert "<summary>" in result.text
        assert "<journal>" in result.text

    def test_journal_instructions_in_prompt(self, brain):
        """Prompt assembly always includes journal instructions and XML output format."""
        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        idir = managed_insights(brain, "leaf")
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain)
        assert "journal entry" in result.text.lower()
        assert "<summary>" in result.text
        assert "<journal>" in result.text
        assert "Do not include any text outside the tags" in result.text


class TestPromptVersionAndContent:
    def test_prompt_version_in_instructions(self):
        """INSIGHT_INSTRUCTIONS.md contains the version marker."""
        assert "insight-v2" in _REGEN_INSTRUCTIONS

    def test_prompt_version_constant(self):
        assert PROMPT_VERSION == "insight-v2"

    def test_global_context_in_prompt(self, brain):
        """Global context is inlined in the prompt (not left for agent to discover)."""
        core = brain / "knowledge" / "_core"
        core.mkdir(parents=True)
        (core / "about.md").write_text("# Identity Info", encoding="utf-8")
        icore = managed_insights(brain, "_core")
        icore.mkdir(parents=True)
        (icore / "summary.md").write_text("# Core Summary\nShared meaning.", encoding="utf-8")

        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        idir = managed_insights(brain, "leaf")
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("leaf", kdir, {}, idir, brain)
        assert "Core Summary" in result.text
        assert "Global Context" in result.text
        assert "Identity Info" not in result.text

    def test_no_glob_or_read_instructions(self, brain):
        """Prompt explicitly tells agent not to use Read or Glob."""
        kdir = brain / "knowledge" / "leaf"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        idir = managed_insights(brain, "leaf")
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

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=empty_output):
            with pytest.raises(RegenFailed):
                asyncio.run(regen_path(brain, "project"))

    def test_valid_output_written(self, brain):
        """Valid summary output is written to summary.md by Python."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")

        async def valid_output(prompt, cwd, **kwargs):
            return ClaudeResult(success=True, output="# Summary\n\nThis is a valid summary.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=valid_output):
            asyncio.run(regen_path(brain, "project"))

        summary_path = managed_summary(brain, "project")
        assert summary_path.exists()
        assert "valid summary" in summary_path.read_text(encoding="utf-8")

    def test_journal_only_xml_raises_regen_failed_without_writing_summary(self, brain):
        """Malformed structured output must not leak journal XML into summary.md."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")

        async def malformed_output(prompt, cwd, **kwargs):
            return ClaudeResult(success=True, output="<journal>\nOnly journal\n</journal>")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=malformed_output):
            with pytest.raises(RegenFailed, match="suspiciously small output"):
                asyncio.run(regen_path(brain, "project"))

        assert not managed_summary(brain, "project").exists()
        assert not managed_journal(brain, "project").exists()

    def test_broken_journal_tag_raises_regen_failed_without_writing_artifacts(self, brain):
        """Malformed journal tags must fail safely with no writes."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")

        async def malformed_output(prompt, cwd, **kwargs):
            return ClaudeResult(
                success=True,
                output="<summary>\nValid enough summary text.\n</summary>\n<journal>\nBroken",
            )

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=malformed_output):
            with pytest.raises(RegenFailed, match="suspiciously small output"):
                asyncio.run(regen_path(brain, "project"))

        assert not managed_summary(brain, "project").exists()
        assert not managed_journal(brain, "project").exists()

    def test_text_outside_xml_envelope_raises_regen_failed_without_writing_artifacts(self, brain):
        """Extra text outside the XML wrapper must fail safely with no writes."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")

        async def malformed_output(prompt, cwd, **kwargs):
            output = "prefix\n<summary>\nValid enough summary text.\n</summary>\n<journal>\nEntry\n</journal>\nsuffix"
            return ClaudeResult(
                success=True,
                output=output,
            )

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=malformed_output):
            with pytest.raises(RegenFailed, match="suspiciously small output"):
                asyncio.run(regen_path(brain, "project"))

        assert not managed_summary(brain, "project").exists()
        assert not managed_journal(brain, "project").exists()


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

    def test_chunk_count_guard(self, brain, monkeypatch):
        """More than MAX_CHUNKS raises RegenFailed when budget pressure forces chunking."""
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
        monkeypatch.setattr("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 5_000)
        with (
            patch("brain_sync.regen.engine.invoke_claude", side_effect=mock_invoke),
            patch("brain_sync.regen.engine._split_markdown_chunks", return_value=fake_chunks),
            patch("brain_sync.regen.engine._preprocess_content", side_effect=lambda c, f: "x" * 200_000),
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

    def test_oversized_files_detected(self, brain, monkeypatch):
        """Files are deferred when the effective prompt budget cannot inline them."""
        kdir = brain / "knowledge" / "big"
        kdir.mkdir(parents=True)
        (kdir / "huge.md").write_text("# Huge\n" + "x" * (CHUNK_TARGET_CHARS + 1000), encoding="utf-8")
        idir = managed_insights(brain, "big")
        idir.mkdir(parents=True)

        monkeypatch.setattr("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 5_000)
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
        idir = managed_insights(brain, "small")
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
        idir = managed_insights(brain, "b64")
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("b64", kdir, {}, idir, brain)
        # After stripping base64, should be small enough to inline
        assert result.oversized_files is None
        assert "[diagram: img]" in result.text


class TestChunkedRegenFlow:
    """End-to-end test for chunk-and-merge regen path."""

    def test_regen_path_chunked_flow(self, brain, monkeypatch):
        """Budget-driven deferral triggers chunk calls then a merge call."""
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

        monkeypatch.setattr("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 5_000)
        with (
            patch("brain_sync.regen.engine.invoke_claude", side_effect=mock_invoke),
            patch("brain_sync.regen.engine.CHUNK_TARGET_CHARS", 2000),
        ):
            count = asyncio.run(regen_path(brain, "prd"))

        assert count >= 1
        # Should have been called multiple times: chunk calls + final merge
        assert call_count > 1
        summary_path = managed_summary(brain, "prd")
        assert summary_path.exists()

    def test_token_tracking_across_chunks(self, brain, monkeypatch):
        """Token telemetry params are passed through chunk + merge calls."""
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
                duration_ms=1000,
            )

        telemetry_calls: list[dict] = []

        def capture_telemetry(result, **kwargs):
            telemetry_calls.append(kwargs)

        monkeypatch.setattr("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 2_000)
        with (
            patch("brain_sync.regen.engine.invoke_claude", side_effect=mock_invoke),
            patch("brain_sync.regen.engine._record_telemetry", side_effect=capture_telemetry),
            patch("brain_sync.regen.engine.CHUNK_TARGET_CHARS", 1500),
        ):
            asyncio.run(regen_path(brain, "tok", session_id="test-session-1"))

        istate = load_insight_state(brain, "tok")
        assert istate is not None
        # Verify telemetry was recorded for chunk + merge calls
        assert len(telemetry_calls) > 1  # chunks + final
        chunk_calls = [t for t in telemetry_calls if t.get("is_chunk") is True]
        final_calls = [t for t in telemetry_calls if t.get("is_chunk") is False]
        assert len(chunk_calls) >= 1
        assert len(final_calls) >= 1
        # All telemetry calls should have session_id and operation_type
        for t in telemetry_calls:
            assert t.get("session_id") == "test-session-1"
            assert t.get("operation_type") == "regen"
            assert t.get("resource_type") == "knowledge"


class TestTokenBudgetEnforcement:
    """Tests for total token budget enforcement in _build_prompt()."""

    def test_many_files_triggers_chunking(self, brain):
        """20 files x ~25K chars collectively exceed budget -> some deferred."""
        kdir = brain / "knowledge" / "many"
        kdir.mkdir(parents=True)
        for i in range(20):
            (kdir / f"doc{i:02d}.md").write_text(f"# Doc {i}\n" + "x" * 25_000, encoding="utf-8")
        idir = managed_insights(brain, "many")
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
        idir = managed_insights(brain, "vary")
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        # Set budget low enough that huge + large can't fit alongside overhead
        with patch("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 10_000):
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
        idir = managed_insights(brain, "tiny")
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        result = _build_prompt("tiny", kdir, {}, idir, brain)
        assert result.oversized_files is None

    def test_deferred_files_have_placeholder(self, brain):
        """Deferred files show placeholder text in the prompt."""
        kdir = brain / "knowledge" / "defer"
        kdir.mkdir(parents=True)
        (kdir / "big.md").write_text("# Big\n" + "x" * 50_000, encoding="utf-8")
        idir = managed_insights(brain, "defer")
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        # Budget so low the file can't fit
        with patch("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 5_000):
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
        idir = managed_insights(brain, "exact")
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
        idir = managed_insights(brain, "allbig")
        idir.mkdir(parents=True)

        invalidate_global_context_cache()
        # Budget so low nothing fits
        with patch("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 3_000):
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
            (kdir / f"file{i:02d}.md").write_text(f"# File {i}\n" + "content " * 500, encoding="utf-8")

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
            patch("brain_sync.regen.engine.invoke_claude", side_effect=mock_invoke),
            patch("brain_sync.regen.engine.MAX_PROMPT_TOKENS", 5_000),
        ):
            count = asyncio.run(regen_path(brain, "e2e"))

        assert count >= 1
        # Multiple calls: chunk calls for deferred files + final merge
        assert call_count > 1
        summary_path = managed_summary(brain, "e2e")
        assert summary_path.exists()


class TestParseStructuredOutput:
    def test_both_sections(self):
        """Valid XML with summary + journal returns both."""
        raw = "<summary>\n# Summary\nHello world\n</summary>\n\n<journal>\nMeeting notes added.\n</journal>"
        summary, journal = _parse_structured_output(raw)
        assert summary == "# Summary\nHello world"
        assert journal == "Meeting notes added."

    def test_empty_journal(self):
        """Empty <journal> tag returns (summary, None)."""
        raw = "<summary>\n# Summary\n</summary>\n\n<journal>\n</journal>"
        summary, journal = _parse_structured_output(raw)
        assert summary == "# Summary"
        assert journal is None

    def test_whitespace_only_journal(self):
        """Whitespace-only journal returns None."""
        raw = "<summary>\n# Summary\n</summary>\n\n<journal>\n   \n</journal>"
        summary, journal = _parse_structured_output(raw)
        assert summary == "# Summary"
        assert journal is None

    def test_no_tags_fallback(self):
        """Raw text without XML tags falls back to entire output as summary."""
        raw = "# Summary\nJust plain text"
        summary, journal = _parse_structured_output(raw)
        assert summary == raw
        assert journal is None

    def test_journal_only_xml_is_rejected(self):
        """Malformed structured output without <summary> is rejected."""
        raw = "<journal>\nOnly journal\n</journal>"
        summary, journal = _parse_structured_output(raw)
        assert summary == ""
        assert journal is None

    def test_malformed_summary_tag_is_rejected(self):
        """Structured markers without a valid closed <summary> are rejected."""
        raw = "<summary>\nUnclosed summary\n<journal>\nEntry\n</journal>"
        summary, journal = _parse_structured_output(raw)
        assert summary == ""
        assert journal is None

    def test_malformed_journal_tag_is_rejected(self):
        """Structured markers without a valid closed <journal> are rejected."""
        raw = "<summary>\nContent\n</summary>\n<journal>\nBroken"
        summary, journal = _parse_structured_output(raw)
        assert summary == ""
        assert journal is None

    def test_text_outside_xml_envelope_is_rejected(self):
        """Any text outside the required XML sections is rejected."""
        raw = "prefix\n<summary>\nContent\n</summary>\n<journal>\nEntry\n</journal>\nsuffix"
        summary, journal = _parse_structured_output(raw)
        assert summary == ""
        assert journal is None

    def test_leading_whitespace_stripped(self):
        """Leading/trailing whitespace on raw input is stripped before parsing."""
        raw = "\n\n  <summary>\nContent\n</summary>\n\n<journal>\nEntry\n</journal>  \n"
        summary, journal = _parse_structured_output(raw)
        assert summary == "Content"
        assert journal == "Entry"


class TestJournalWriting:
    def test_journal_written_on_summary_change(self, brain):
        """Default config writes a journal file when Claude returns journal content."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Meeting Notes\nDecided to use MCP.", encoding="utf-8")

        structured_output = (
            "<summary>\n# Project Summary\nNew summary with MCP decision.\n</summary>\n\n"
            "<journal>\nMeeting notes added. Decision: adopt MCP for all services.\n</journal>"
        )

        async def mock_invoke(prompt, cwd, **kwargs):
            return ClaudeResult(success=True, output=structured_output)

        config = RegenConfig()
        with patch("brain_sync.regen.engine.invoke_claude", side_effect=mock_invoke):
            asyncio.run(regen_path(brain, "project", config=config))

        # Summary written
        summary_path = managed_summary(brain, "project")
        assert summary_path.exists()
        assert "MCP decision" in summary_path.read_text(encoding="utf-8")

        # Journal written
        journal_dir = managed_journal(brain, "project")
        assert journal_dir.exists()
        journal_files = list(journal_dir.rglob("*.md"))
        assert len(journal_files) == 1
        journal_content = journal_files[0].read_text(encoding="utf-8")
        assert "## " in journal_content  # has timestamp heading
        assert "adopt MCP" in journal_content

    def test_journal_written_when_similarity_guard_blocks_summary(self, brain):
        """Journal is written even when the similarity guard discards the summary rewrite."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\nSome content here.", encoding="utf-8")
        idir = managed_insights(brain, "project")
        idir.mkdir(parents=True)
        # Write an existing summary that will be near-identical to Claude's output
        existing = "# Project Summary\nThis is the existing summary."
        (idir / "summary.md").write_text(existing, encoding="utf-8")

        # Claude returns near-identical summary but with a journal entry
        structured_output = f"<summary>\n{existing}\n</summary>\n\n<journal>\nMinor context update noted.\n</journal>"

        async def mock_invoke(prompt, cwd, **kwargs):
            return ClaudeResult(success=True, output=structured_output)

        config = RegenConfig(similarity_threshold=0.97)
        with patch("brain_sync.regen.engine.invoke_claude", side_effect=mock_invoke):
            count = asyncio.run(regen_path(brain, "project", config=config))

        # Summary NOT rewritten (similarity guard blocked it)
        assert count == 0
        assert (idir / "summary.md").read_text(encoding="utf-8") == existing

        # Journal IS written
        journal_files = list(managed_journal(brain, "project").rglob("*.md"))
        assert len(journal_files) == 1
        assert "Minor context update" in journal_files[0].read_text(encoding="utf-8")

    def test_journal_append_same_day(self, tmp_path):
        """Two journal writes on the same day append to the same file."""
        insights_dir = managed_insights(tmp_path, "area")
        insights_dir.mkdir(parents=True)

        _write_journal_entry(insights_dir, "First entry.", "abc123", "area")
        _write_journal_entry(insights_dir, "Second entry.", "def456", "area")

        journal_files = list(managed_journal(tmp_path, "area").rglob("*.md"))
        assert len(journal_files) == 1
        content = journal_files[0].read_text(encoding="utf-8")
        assert "First entry." in content
        assert "Second entry." in content
        # Two timestamped headings
        assert content.count("## ") == 2

    def test_no_journal_when_empty(self, brain):
        """Empty journal section does not create a journal file."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc\nContent.", encoding="utf-8")

        structured_output = "<summary>\n# Project Summary\nA valid summary.\n</summary>\n\n<journal>\n</journal>"

        async def mock_invoke(prompt, cwd, **kwargs):
            return ClaudeResult(success=True, output=structured_output)

        config = RegenConfig()
        with patch("brain_sync.regen.engine.invoke_claude", side_effect=mock_invoke):
            asyncio.run(regen_path(brain, "project", config=config))

        # Summary written
        assert managed_summary(brain, "project").exists()

        # No journal directory created
        journal_dir = managed_journal(brain, "project")
        assert not journal_dir.exists()


# ---------------------------------------------------------------------------
# _parse_stream_json tests
# ---------------------------------------------------------------------------


def _ndjson(*events: dict) -> str:  # type: ignore[type-arg]
    """Build NDJSON string from event dicts."""
    return "\n".join(json.dumps(e) for e in events) + "\n"


class TestParseStreamJson:
    """Tests for _parse_stream_json using the actual CLI verbose stream-json format.

    The CLI emits high-level NDJSON events:
    - {"type":"system","subtype":"init",...}
    - {"type":"assistant","message":{"usage":{...},"content":[{"type":"text","text":"..."}]}}
    - {"type":"result","usage":{...},"num_turns":N,"is_error":false,...}
    """

    def test_single_turn(self):
        stdout = _ndjson(
            {"type": "system", "subtype": "init", "model": "claude-sonnet-4-6"},
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Hello world"}],
                    "usage": {
                        "input_tokens": 50000,
                        "cache_creation_input_tokens": 5000,
                        "cache_read_input_tokens": 10000,
                        "output_tokens": 2000,
                    },
                },
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "num_turns": 1,
                "result": "Hello world",
                "usage": {
                    "input_tokens": 50000,
                    "cache_creation_input_tokens": 5000,
                    "cache_read_input_tokens": 10000,
                    "output_tokens": 2000,
                },
            },
        )
        r = _parse_stream_json(stdout)
        # cache_read excluded from billable total: 50000 + 5000 = 55000
        assert r.input_tokens == 55000
        assert r.output_tokens == 2000
        assert r.text == "Hello world"
        assert r.num_turns == 1
        assert r.is_error is False

    def test_multi_turn_text_concatenated(self):
        """Multi-turn: text assembled from assistant events, tokens from result."""
        stdout = _ndjson(
            {"type": "system", "subtype": "init"},
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Turn 1. "}],
                    "usage": {"input_tokens": 30000, "output_tokens": 500},
                },
            },
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "Turn 2."}],
                    "usage": {"input_tokens": 35000, "output_tokens": 800},
                },
            },
            {
                "type": "result",
                "subtype": "success",
                "is_error": False,
                "num_turns": 2,
                "usage": {
                    "input_tokens": 65000,
                    "cache_creation_input_tokens": 3000,
                    "cache_read_input_tokens": 0,
                    "output_tokens": 1300,
                },
            },
        )
        r = _parse_stream_json(stdout)
        assert r.text == "Turn 1. Turn 2."
        # Tokens from result event: 65000 + 3000 = 68000
        assert r.input_tokens == 68000
        assert r.output_tokens == 1300
        assert r.num_turns == 2

    def test_error_result(self):
        stdout = _ndjson(
            {"type": "system", "subtype": "init"},
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "partial"}],
                    "usage": {"input_tokens": 500, "output_tokens": 50},
                },
            },
            {
                "type": "result",
                "num_turns": 1,
                "is_error": True,
                "subtype": "error_max_turns",
                "usage": {"input_tokens": 500, "output_tokens": 50},
            },
        )
        r = _parse_stream_json(stdout)
        assert r.is_error is True
        assert r.error_subtype == "error_max_turns"
        assert r.text == "partial"

    def test_empty_input(self):
        r = _parse_stream_json("")
        assert r.text == ""
        assert r.input_tokens is None
        assert r.output_tokens is None
        assert r.num_turns is None
        assert r.is_error is False

    def test_malformed_lines_skipped(self):
        stdout = "not json at all\n\n{bad json\n" + _ndjson(
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "ok"}],
                    "usage": {"input_tokens": 42, "output_tokens": 10},
                },
            },
            {
                "type": "result",
                "num_turns": 1,
                "is_error": False,
                "subtype": "success",
                "usage": {"input_tokens": 42, "output_tokens": 10},
            },
        )
        r = _parse_stream_json(stdout)
        assert r.input_tokens == 42
        assert r.output_tokens == 10
        assert r.text == "ok"

    def test_tool_use_content_ignored(self):
        """Non-text content blocks should not contribute to text."""
        stdout = _ndjson(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "t1", "name": "foo", "input": {}},
                        {"type": "text", "text": "real text"},
                    ],
                    "usage": {"input_tokens": 100, "output_tokens": 20},
                },
            },
            {
                "type": "result",
                "num_turns": 1,
                "is_error": False,
                "subtype": "success",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )
        r = _parse_stream_json(stdout)
        assert r.text == "real text"

    def test_result_text_fallback(self):
        """If no assistant events, fall back to result.result for text."""
        stdout = _ndjson(
            {
                "type": "result",
                "result": "fallback text",
                "num_turns": 1,
                "is_error": False,
                "subtype": "success",
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )
        r = _parse_stream_json(stdout)
        assert r.text == "fallback text"
        assert r.input_tokens == 100


class TestComputeWaves:
    """Tests for compute_waves() — depth-ordered wave computation."""

    def test_basic(self):
        waves = compute_waves(["a/b/c", "a/b/d", "x/y"])
        assert len(waves) == 4
        assert waves[0] == ["a/b/c", "a/b/d"]  # depth 3
        assert waves[1] == ["a/b", "x/y"]  # depth 2
        assert waves[2] == ["a", "x"]  # depth 1
        assert waves[3] == [""]  # depth 0

    def test_empty(self):
        assert compute_waves([]) == []

    def test_single_leaf(self):
        waves = compute_waves(["project"])
        assert waves == [["project"], [""]]

    def test_root_only(self):
        waves = compute_waves([""])
        assert waves == [[""]]

    def test_deterministic_sorting(self):
        """Within each wave, paths are alphabetically sorted."""
        waves = compute_waves(["z/b", "a/c", "m/d"])
        # Depth 2 wave should be sorted
        assert waves[0] == ["a/c", "m/d", "z/b"]
        # Depth 1 wave
        assert waves[1] == ["a", "m", "z"]
        # Root
        assert waves[2] == [""]

    def test_shared_ancestors_deduped(self):
        """Shared ancestors appear only once in their wave."""
        waves = compute_waves(["a/b/c", "a/b/d"])
        # "a/b" should appear once, not twice
        depth2 = waves[1]
        assert depth2.count("a/b") == 1


class TestPropagationMatrix:
    def test_backfill_stops_walkup_and_wave_propagation(self):
        assert propagates_up("skipped_backfill") is False
        assert parent_dirty_reason("skipped_backfill") is None

    def test_local_structure_only_rename_does_not_propagate(self):
        assert propagates_up("skipped_rename") is False
        assert parent_dirty_reason("skipped_rename") is None

    def test_regenerated_propagates_for_child_summary_change(self):
        assert propagates_up("regenerated") is True
        assert parent_dirty_reason("regenerated") == "child_summary_changed"


class TestRegenSingleFolder:
    """Tests for regen_single_folder() — single folder processing."""

    def _mock_claude(self, content: str = "# Summary\n\nGenerated insight summary content."):
        async def fake_invoke(prompt: str, cwd: Path, **kwargs):
            return ClaudeResult(success=True, output=content)

        return fake_invoke

    def test_leaf_regen_returns_regenerated(self, brain):
        """New content triggers Claude and returns 'regenerated'."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude()):
            result = asyncio.run(regen_single_folder(brain, "project"))

        assert result.action == "regenerated"
        assert result.knowledge_path == "project"
        assert managed_summary(brain, "project").exists()

    def test_unchanged_returns_skipped(self, brain):
        """Matching content hash returns 'skipped_unchanged'."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")

        # First regen to populate hashes
        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude()):
            asyncio.run(regen_single_folder(brain, "project"))

        # Second call — nothing changed
        with patch("brain_sync.regen.engine.invoke_claude") as mock:
            result = asyncio.run(regen_single_folder(brain, "project"))

        assert result.action == "skipped_unchanged"
        mock.assert_not_called()

    def test_rename_returns_skipped_rename(self, brain):
        """Structure-only change returns 'skipped_rename'."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")
        sub = kdir / "sub1"
        sub.mkdir()
        (sub / "file.md").write_text("sub content", encoding="utf-8")

        # First regen
        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude()):
            asyncio.run(regen_single_folder(brain, "project"))

        # Rename sub dir (content unchanged, structure changed)
        sub.rename(kdir / "sub2")

        result = asyncio.run(regen_single_folder(brain, "project"))
        assert result.action == "skipped_rename"

    def test_no_content_returns_skipped_no_content(self, brain):
        """Empty folder returns 'skipped_no_content'."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        # Folder exists but has no readable files or child dirs

        result = asyncio.run(regen_single_folder(brain, "project"))
        assert result.action == "skipped_no_content"

    def test_cleaned_up_when_folder_missing(self, brain):
        """Missing folder clears stale state and returns 'cleaned_up'."""
        save_insight_state(brain, InsightState(knowledge_path="gone", content_hash=None, regen_status="idle"))

        result = asyncio.run(regen_single_folder(brain, "gone"))
        assert result.action == "cleaned_up"
        assert load_insight_state(brain, "gone") is None

    def test_similarity_returns_skipped_similarity(self, brain):
        """Similarity guard returns 'skipped_similarity'."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")

        summary_text = "# Summary\n\nThis is the generated summary."

        # First regen
        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude(summary_text)):
            asyncio.run(regen_single_folder(brain, "project"))

        # Modify content to trigger regen
        (kdir / "doc.md").write_text("# Updated Content", encoding="utf-8")

        # Return nearly identical summary (>97% similar)
        similar = "# Summary\n\nThis is the generated summary."
        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude(similar)):
            result = asyncio.run(regen_single_folder(brain, "project"))

        assert result.action == "skipped_similarity"

    def test_backfill_returns_skipped_backfill(self, brain):
        """Pre-v18 state with existing summary returns 'skipped_backfill'."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")
        idir = managed_insights(brain, "project")
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("# Old Summary", encoding="utf-8")

        # Pre-v18 state: has content_hash but no structure_hash
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="project",
                content_hash="old_hash",
                summary_hash="old_summary_hash",
                structure_hash=None,  # pre-v18
                regen_status="idle",
            ),
        )

        result = asyncio.run(regen_single_folder(brain, "project"))
        assert result.action == "skipped_backfill"

        # Verify structure_hash was set
        loaded = load_insight_state(brain, "project")
        assert loaded is not None
        assert loaded.structure_hash is not None

    def test_failure_raises_regen_failed(self, brain):
        """Claude error raises RegenFailed."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")

        async def fail_invoke(prompt: str, cwd: Path, **kwargs):
            return ClaudeResult(success=False, output="")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=fail_invoke):
            with pytest.raises(RegenFailed):
                asyncio.run(regen_single_folder(brain, "project"))

    def test_failure_preserves_portable_insight_state_bytes(self, brain):
        """Running/failed lifecycle updates do not rewrite portable insight-state."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")

        save_insight_state(
            brain,
            InsightState(
                knowledge_path="project",
                content_hash="old-hash",
                summary_hash="old-summary-hash",
                structure_hash="old-structure-hash",
                last_regen_utc="2026-03-10T00:00:00Z",
                regen_status="idle",
            ),
        )
        sidecar_path = managed_insights(brain, "project") / "insight-state.json"
        before_bytes = sidecar_path.read_bytes()

        async def fail_invoke(prompt: str, cwd: Path, **kwargs):
            return ClaudeResult(success=False, output="")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=fail_invoke):
            with pytest.raises(RegenFailed):
                asyncio.run(regen_single_folder(brain, "project"))

        loaded = load_insight_state(brain, "project")

        assert loaded is not None
        assert loaded.regen_status == "failed"
        assert loaded.last_regen_utc == "2026-03-10T00:00:00Z"
        assert sidecar_path.read_bytes() == before_bytes


class TestRegenAllWave:
    """Tests for wave-based regen_all() behavior."""

    def _mock_claude(self, content: str = "# Summary\n\nGenerated insight summary content."):
        async def fake_invoke(prompt: str, cwd: Path, **kwargs):
            return ClaudeResult(success=True, output=content)

        return fake_invoke

    def test_no_redundant_calls(self, brain):
        """3 sibling leaves: each folder gets at most 1 Claude call."""
        parent = brain / "knowledge" / "area"
        parent.mkdir(parents=True)
        (parent / "overview.md").write_text("# Overview", encoding="utf-8")
        for name in ("sub1", "sub2", "sub3"):
            d = parent / name
            d.mkdir()
            (d / "doc.md").write_text(f"# {name}", encoding="utf-8")

        call_paths: list[str] = []

        async def track_invoke(prompt: str, cwd: Path, **kwargs):
            for line in prompt.split("\n"):
                if "regenerating the insight summary for knowledge area:" in line:
                    area = line.split(":")[-1].strip()
                    call_paths.append(area)
                    break
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=track_invoke):
            total = asyncio.run(regen_all(brain))

        # Each path should appear at most once
        for p in ("area/sub1", "area/sub2", "area/sub3", "area"):
            assert call_paths.count(p) <= 1, f"{p} called {call_paths.count(p)} times"
        assert total >= 4  # sub1, sub2, sub3, area (+ possibly root)

    def test_dirty_propagation_skips_unchanged_parent(self, brain):
        """If all children are unchanged, parent is not processed."""
        parent = brain / "knowledge" / "area"
        parent.mkdir(parents=True)
        (parent / "overview.md").write_text("# Overview", encoding="utf-8")
        sub1 = parent / "sub1"
        sub1.mkdir()
        (sub1 / "doc.md").write_text("# Sub1", encoding="utf-8")
        sub2 = parent / "sub2"
        sub2.mkdir()
        (sub2 / "doc.md").write_text("# Sub2", encoding="utf-8")

        # First regen — populate all hashes
        with patch("brain_sync.regen.engine.invoke_claude", side_effect=self._mock_claude()):
            asyncio.run(regen_all(brain))

        # Second regen — nothing changed
        call_count = 0

        async def count_invoke(prompt: str, cwd: Path, **kwargs):
            nonlocal call_count
            call_count += 1
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=count_invoke):
            total = asyncio.run(regen_all(brain))

        assert total == 0
        assert call_count == 0

    def test_mixed_dirty_propagation(self, brain):
        """If one child changed and one didn't, parent is processed once."""
        parent = brain / "knowledge" / "area"
        parent.mkdir(parents=True)
        (parent / "overview.md").write_text("# Overview", encoding="utf-8")
        sub1 = parent / "sub1"
        sub1.mkdir()
        (sub1 / "doc.md").write_text("# Sub1", encoding="utf-8")
        sub2 = parent / "sub2"
        sub2.mkdir()
        (sub2 / "doc.md").write_text("# Sub2", encoding="utf-8")

        # First regen — each path gets a unique summary
        call_idx = 0

        async def unique_invoke(prompt: str, cwd: Path, **kwargs):
            nonlocal call_idx
            call_idx += 1
            return ClaudeResult(success=True, output=f"# Summary v{call_idx}\n\nGenerated insight content v{call_idx}.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=unique_invoke):
            asyncio.run(regen_all(brain))

        # Modify only sub1
        (sub1 / "doc.md").write_text("# Updated Sub1 content", encoding="utf-8")

        call_paths: list[str] = []

        async def track_invoke(prompt: str, cwd: Path, **kwargs):
            nonlocal call_idx
            call_idx += 1
            for line in prompt.split("\n"):
                if "regenerating the insight summary for knowledge area:" in line:
                    area = line.split(":")[-1].strip()
                    call_paths.append(area)
                    break
            return ClaudeResult(success=True, output=f"# Summary v{call_idx}\n\nGenerated insight content v{call_idx}.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=track_invoke):
            total = asyncio.run(regen_all(brain))

        # sub1 changed → parent dirtied → parent processed once
        assert "area/sub1" in call_paths
        assert "area/sub2" not in call_paths  # unchanged
        assert call_paths.count("area") == 1  # parent processed exactly once
        assert total >= 1

    def test_failure_does_not_propagate(self, brain):
        """Failed leaf does not dirty its parent (parent has no direct files)."""
        # Parent has NO direct files — it only gets dirtied via child propagation
        parent = brain / "knowledge" / "area"
        parent.mkdir(parents=True)
        sub1 = parent / "sub1"
        sub1.mkdir()
        (sub1 / "doc.md").write_text("# Sub1", encoding="utf-8")

        call_paths: list[str] = []

        async def fail_on_sub1(prompt: str, cwd: Path, **kwargs):
            for line in prompt.split("\n"):
                if "regenerating the insight summary for knowledge area:" in line:
                    area = line.split(":")[-1].strip()
                    call_paths.append(area)
                    if area == "area/sub1":
                        return ClaudeResult(success=False, output="")
                    break
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=fail_on_sub1):
            asyncio.run(regen_all(brain))

        # sub1 failed → parent should NOT be processed
        # (parent is not in content_paths since it has no direct files,
        # and sub1's failure does not propagate dirtiness)
        assert "area/sub1" in call_paths
        assert "area" not in call_paths

    def test_backfill_does_not_propagate(self, brain):
        """Pre-v18 backfill does not dirty parent."""
        parent = brain / "knowledge" / "area"
        parent.mkdir(parents=True)
        (parent / "overview.md").write_text("# Overview", encoding="utf-8")
        sub = parent / "sub"
        sub.mkdir()
        (sub / "doc.md").write_text("# Sub", encoding="utf-8")

        # Create pre-v18 state for sub (with existing summary)
        idir = managed_insights(brain, "area/sub")
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("# Existing Summary", encoding="utf-8")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/sub",
                content_hash="old_hash",
                summary_hash="old_summary_hash",
                structure_hash=None,  # pre-v18
                regen_status="idle",
            ),
        )
        # Also create pre-v18 state for parent
        pdir = managed_insights(brain, "area")
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "summary.md").write_text("# Parent Summary", encoding="utf-8")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area",
                content_hash="old_parent_hash",
                summary_hash="old_parent_summary",
                structure_hash=None,  # pre-v18
                regen_status="idle",
            ),
        )

        call_count = 0

        async def count_invoke(prompt: str, cwd: Path, **kwargs):
            nonlocal call_count
            call_count += 1
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        with patch("brain_sync.regen.engine.invoke_claude", side_effect=count_invoke):
            asyncio.run(regen_all(brain))

        # Backfill should NOT trigger any Claude calls — parent not dirtied
        assert call_count == 0

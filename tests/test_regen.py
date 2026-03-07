"""Tests for the insight regeneration engine."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from brain_sync.regen import (
    SIMILARITY_THRESHOLD,
    ClaudeResult,
    folder_content_hash,
    regen_path,
    text_similarity,
)
from brain_sync.state import (
    InsightState,
    _connect,
    load_insight_state,
    save_insight_state,
)


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

    def test_ignores_non_md_files(self, tmp_path):
        folder = tmp_path / "docs"
        folder.mkdir()
        (folder / "a.md").write_text("hello", encoding="utf-8")
        h1 = folder_content_hash(folder)
        (folder / "notes.txt").write_text("ignored", encoding="utf-8")
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
            retry_count=0,
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

    def _mock_claude_write_summary(self, content: str = "# Test Summary\n\nGenerated."):
        """Create a mock invoke_claude that writes a summary.md file."""
        async def fake_invoke(prompt: str, cwd: Path, **kwargs):
            # Extract the summary path from the prompt
            # The prompt ends with "Write the summary to: <path>" or
            # "Write the parent summary to: <path>"
            for line in prompt.split("\n"):
                if line.startswith("Write the") and "summary to:" in line:
                    path_str = line.split(":", 1)[-1].strip()
                    summary_path = Path(path_str)
                    summary_path.parent.mkdir(parents=True, exist_ok=True)
                    summary_path.write_text(content, encoding="utf-8")
                    break
            return ClaudeResult(success=True, output="Done")
        return fake_invoke

    def test_leaf_regen_creates_summary(self, brain):
        """Leaf regen with md files creates summary."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Project Doc\nSome content.", encoding="utf-8")

        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_write_summary()):
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

        content_hash = folder_content_hash(kdir)

        # Pre-populate insight state with matching hash
        save_insight_state(brain, InsightState(
            knowledge_path="project",
            content_hash=content_hash,
            summary_hash="existing",
            regen_status="idle",
        ))

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

        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_write_summary(near_identical)):
            count = asyncio.run(regen_path(brain, "project"))

        # Summary should have been discarded (restored to old)
        assert count == 0
        current = (idir / "summary.md").read_text(encoding="utf-8")
        assert current == old_summary

    def test_claude_failure_marks_failed(self, brain):
        """If Claude CLI fails, insight state is marked as failed."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Content", encoding="utf-8")

        async def fail_invoke(*args, **kwargs):
            return ClaudeResult(success=False, output="")

        with patch("brain_sync.regen.invoke_claude", side_effect=fail_invoke):
            count = asyncio.run(regen_path(brain, "project"))

        assert count == 0
        istate = load_insight_state(brain, "project")
        assert istate is not None
        assert istate.regen_status == "failed"
        assert istate.retry_count == 1

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

        async def capture_and_write(prompt: str, cwd: Path, **kwargs):
            prompt_captured.append(prompt)
            summary_path = brain / "insights" / "parent" / "summary.md"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text("# Parent Summary\nOverview.", encoding="utf-8")
            return ClaudeResult(success=True, output="Done")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture_and_write):
            count = asyncio.run(regen_path(brain, "parent"))

        assert count >= 1
        # Verify prompt contained child summaries
        assert len(prompt_captured) >= 1
        prompt = prompt_captured[0]
        assert "child-a" in prompt
        assert "child-b" in prompt
        assert "PARENT regeneration" in prompt

    def test_nonexistent_knowledge_dir(self, brain):
        """Regen for a nonexistent knowledge dir does nothing."""
        with patch("brain_sync.regen.invoke_claude") as mock:
            count = asyncio.run(regen_path(brain, "nonexistent"))
        assert count == 0
        mock.assert_not_called()

    def test_empty_knowledge_dir(self, brain):
        """Regen for an empty knowledge dir (no .md files) does nothing."""
        kdir = brain / "knowledge" / "empty"
        kdir.mkdir(parents=True)

        with patch("brain_sync.regen.invoke_claude") as mock:
            count = asyncio.run(regen_path(brain, "empty"))
        assert count == 0
        mock.assert_not_called()

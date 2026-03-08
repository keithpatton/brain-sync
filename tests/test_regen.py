"""Tests for the insight regeneration engine."""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from brain_sync.fileops import KNOWLEDGE_EXTENSIONS
from brain_sync.regen import (
    SIMILARITY_THRESHOLD,
    ClaudeResult,
    _collect_child_summaries,
    _compute_hash,
    _find_all_content_paths,
    _get_child_dirs,
    _is_readable_file,
    folder_content_hash,
    regen_all,
    regen_path,
    text_similarity,
)
from brain_sync.state import (
    InsightState,
    _connect,
    delete_insight_state,
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
            for line in prompt.split("\n"):
                if "Write the summary to:" in line:
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
        # For a leaf (no child dirs), the unified hash equals folder_content_hash
        child_dirs = _get_child_dirs(kdir)
        unified_hash = _compute_hash(child_dirs, {}, kdir, True)

        save_insight_state(brain, InsightState(
            knowledge_path="project",
            content_hash=unified_hash,
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
        assert "sub-areas" in prompt

    def test_nonexistent_knowledge_dir_cleans_up(self, brain):
        """Regen for a nonexistent knowledge dir cleans up stale insights."""
        # Create stale insights with no corresponding knowledge
        idir = brain / "insights" / "deleted"
        idir.mkdir(parents=True)
        (idir / "summary.md").write_text("stale", encoding="utf-8")
        save_insight_state(brain, InsightState(
            knowledge_path="deleted", content_hash="old", regen_status="idle",
        ))

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
        save_insight_state(brain, InsightState(
            knowledge_path="empty", content_hash="old", regen_status="idle",
        ))

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

        async def capture_and_write(prompt: str, cwd: Path, **kwargs):
            prompt_captured.append(prompt)
            summary_path = brain / "insights" / "initiative" / "summary.md"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text("# Initiative Summary", encoding="utf-8")
            return ClaudeResult(success=True, output="Done")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture_and_write):
            asyncio.run(regen_path(brain, "initiative"))

        assert len(prompt_captured) >= 1
        prompt = prompt_captured[0]
        # Should contain both direct file listing AND child summaries
        assert "overview.md" in prompt
        assert "sub-areas" in prompt
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
        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_write_summary("# Summary V1")):
            asyncio.run(regen_path(brain, "initiative"))

        # Change direct file
        (kdir / "overview.md").write_text("# V2 — significant change", encoding="utf-8")

        # Second regen should trigger (hash changed)
        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_write_summary("# Summary V2 — very different")) as mock:
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
        save_insight_state(brain, InsightState(
            knowledge_path="parent/child", content_hash="old", regen_status="idle",
        ))

        # Delete all files from the leaf
        (kdir / "doc.md").unlink()

        with patch("brain_sync.regen.invoke_claude") as mock:
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
        save_insight_state(brain, InsightState(
            knowledge_path="area/sub", content_hash="old", regen_status="idle",
        ))

        # Delete the child knowledge folder
        import shutil
        shutil.rmtree(child_kdir)

        # Regen for the deleted child should clean up
        with patch("brain_sync.regen.invoke_claude") as mock:
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

        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_write_summary()) as mock:
            count = asyncio.run(regen_path(brain, "data"))

        mock.assert_called()

    def test_folder_with_json_triggers_regen(self, brain):
        """A folder containing a .json file triggers regen."""
        kdir = brain / "knowledge" / "config"
        kdir.mkdir(parents=True)
        (kdir / "spec.json").write_text('{"key": "value"}', encoding="utf-8")

        with patch("brain_sync.regen.invoke_claude", side_effect=self._mock_claude_write_summary()) as mock:
            count = asyncio.run(regen_path(brain, "config"))

        mock.assert_called()

    def test_readable_files_listed_in_prompt(self, brain):
        """Prompt lists readable files but not non-readable ones."""
        kdir = brain / "knowledge" / "project"
        kdir.mkdir(parents=True)
        (kdir / "doc.md").write_text("# Doc", encoding="utf-8")
        (kdir / "diagram.png").write_bytes(b"\x89PNG fake")
        (kdir / "archive.zip").write_bytes(b"PK\x03\x04")

        prompt_captured = []

        async def capture_and_write(prompt: str, cwd: Path, **kwargs):
            prompt_captured.append(prompt)
            summary_path = brain / "insights" / "project" / "summary.md"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text("# Summary", encoding="utf-8")
            return ClaudeResult(success=True, output="Done")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture_and_write):
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

        async def capture_and_write(prompt: str, cwd: Path, **kwargs):
            prompts.append(prompt)
            # Parse summary path from prompt
            for line in prompt.split("\n"):
                if "Write the summary to:" in line:
                    path_str = line.split(":", 1)[-1].strip()
                    summary_path = Path(path_str)
                    summary_path.parent.mkdir(parents=True, exist_ok=True)
                    summary_path.write_text("# Summary", encoding="utf-8")
                    break
            return ClaudeResult(success=True, output="Done")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture_and_write):
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
            summary_path = brain / "insights" / "leaf" / "summary.md"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text("# Summary", encoding="utf-8")
            return ClaudeResult(success=True, output="Done")

        with patch("brain_sync.regen.invoke_claude", side_effect=capture):
            asyncio.run(regen_path(brain, "leaf"))

        prompt = prompt_captured[0]
        # Unified format — no LEAF/PARENT distinction
        assert "regenerating the insight summary for knowledge area: leaf" in prompt
        assert "LEAF" not in prompt
        assert "PARENT" not in prompt


class TestGetChildDirs:
    def test_excludes_underscore_prefixed(self, tmp_path):
        """_get_child_dirs excludes dirs starting with _."""
        root = tmp_path / "knowledge"
        root.mkdir()
        (root / "normal").mkdir()
        (root / "_sync-context").mkdir()
        (root / "_notes").mkdir()
        result = _get_child_dirs(root)
        assert [p.name for p in result] == ["normal"]

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
        with patch("brain_sync.regen.invoke_claude", side_effect=TestRegenPath._mock_claude_write_summary(None, "# Parent V1")):
            asyncio.run(regen_path(brain, "parent"))

        old_istate = load_insight_state(brain, "parent")

        # Add a new child dir (empty for now, but structurally present)
        child_b = kdir / "child-b"
        child_b.mkdir()
        (child_b / "doc.md").write_text("content b", encoding="utf-8")
        child_b_idir = brain / "insights" / "parent" / "child-b"
        child_b_idir.mkdir(parents=True)
        (child_b_idir / "summary.md").write_text("summary b", encoding="utf-8")

        # Second regen should trigger (structural change)
        with patch("brain_sync.regen.invoke_claude", side_effect=TestRegenPath._mock_claude_write_summary(None, "# Parent V2 with both children")) as mock:
            asyncio.run(regen_path(brain, "parent"))

        mock.assert_called()


class TestDeleteInsightState:
    def test_delete_existing(self, brain):
        save_insight_state(brain, InsightState(
            knowledge_path="test", content_hash="abc", regen_status="idle",
        ))
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

    def test_excludes_hidden_and_underscore(self, tmp_path):
        """Hidden and underscore-prefixed dirs are excluded."""
        root = tmp_path / "knowledge"
        root.mkdir()
        (root / "_core").mkdir()
        (root / ".hidden").mkdir()
        normal = root / "visible"
        normal.mkdir()
        (normal / "doc.md").write_text("content", encoding="utf-8")

        paths = _find_all_content_paths(root)
        assert paths == ["visible"]

    def test_empty_tree(self, tmp_path):
        """Empty knowledge root returns empty list."""
        root = tmp_path / "knowledge"
        root.mkdir()
        assert _find_all_content_paths(root) == []


class TestRegenAll:
    def _mock_claude_write_summary(self, content: str = "# Summary\n\nGenerated."):
        """Create a mock invoke_claude that writes a summary.md file."""
        async def fake_invoke(prompt: str, cwd: Path, **kwargs):
            for line in prompt.split("\n"):
                if "Write the summary to:" in line:
                    path_str = line.split(":", 1)[-1].strip()
                    summary_path = Path(path_str)
                    summary_path.parent.mkdir(parents=True, exist_ok=True)
                    summary_path.write_text(content, encoding="utf-8")
                    break
            return ClaudeResult(success=True, output="Done")
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

        async def track_and_write(prompt: str, cwd: Path, **kwargs):
            # Extract the knowledge area from prompt
            for line in prompt.split("\n"):
                if "regenerating the insight summary for knowledge area:" in line:
                    area = line.split(":")[-1].strip()
                    call_order.append(area)
                if "Write the summary to:" in line:
                    path_str = line.split(":", 1)[-1].strip()
                    summary_path = Path(path_str)
                    summary_path.parent.mkdir(parents=True, exist_ok=True)
                    summary_path.write_text(f"# Summary for {area}", encoding="utf-8")
                    break
            return ClaudeResult(success=True, output="Done")

        with patch("brain_sync.regen.invoke_claude", side_effect=track_and_write):
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

import sys
from pathlib import Path

import pytest

from brain_sync.fileops import (
    atomic_write_bytes,
    clean_insights_tree,
    content_hash,
    rediscover_local_path,
    win_long_path,
    write_if_changed,
)
from brain_sync.layout import INSIGHT_STATE_FILENAME

pytestmark = pytest.mark.unit


class TestContentHash:
    def test_deterministic(self):
        data = b"hello world"
        assert content_hash(data) == content_hash(data)

    def test_different_content_different_hash(self):
        assert content_hash(b"a") != content_hash(b"b")


class TestWriteIfChanged:
    def test_creates_new_file(self, tmp_path):
        target = tmp_path / "out.md"
        changed = write_if_changed(target, "# Hello\n")
        assert changed is True
        assert target.read_text(encoding="utf-8") == "# Hello\n"

    def test_no_change_returns_false(self, tmp_path):
        target = tmp_path / "out.md"
        write_if_changed(target, "# Hello\n")
        changed = write_if_changed(target, "# Hello\n")
        assert changed is False

    def test_changed_content_returns_true(self, tmp_path):
        target = tmp_path / "out.md"
        write_if_changed(target, "# V1\n")
        changed = write_if_changed(target, "# V2\n")
        assert changed is True
        assert target.read_text(encoding="utf-8") == "# V2\n"

    def test_creates_parent_dirs(self, tmp_path):
        target = tmp_path / "sub" / "dir" / "out.md"
        changed = write_if_changed(target, "content\n")
        assert changed is True
        assert target.exists()


class TestRediscoverLocalPath:
    def test_finds_confluence_page(self, tmp_path):
        (tmp_path / "sub").mkdir()
        f = tmp_path / "sub" / "c123456-my-page.md"
        f.write_text("content")
        result = rediscover_local_path(tmp_path, "confluence:123456")
        assert result is not None
        assert result.name == "c123456-my-page.md"

    def test_finds_attachment(self, tmp_path):
        (tmp_path / "attachments").mkdir()
        f = tmp_path / "attachments" / "a789-diagram.png"
        f.write_bytes(b"png")
        result = rediscover_local_path(tmp_path, "confluence-attachment:789")
        assert result is not None
        assert result.name == "a789-diagram.png"

    def test_finds_google_doc(self, tmp_path):
        f = tmp_path / "gABC123-my-doc.md"
        f.write_text("content")
        result = rediscover_local_path(tmp_path, "gdoc:ABC123")
        assert result is not None
        assert result.name == "gABC123-my-doc.md"

    def test_returns_none_when_not_found(self, tmp_path):
        result = rediscover_local_path(tmp_path, "confluence:999999")
        assert result is None

    def test_finds_titleless_file(self, tmp_path):
        f = tmp_path / "c456.md"
        f.write_text("content")
        result = rediscover_local_path(tmp_path, "confluence:456")
        assert result is not None
        assert result.name == "c456.md"

    def test_finds_in_nested_dir(self, tmp_path):
        nested = tmp_path / "deep" / "nested" / "dir"
        nested.mkdir(parents=True)
        f = nested / "c100-moved-here.md"
        f.write_text("content")
        result = rediscover_local_path(tmp_path, "confluence:100")
        assert result is not None
        assert result.name == "c100-moved-here.md"

    def test_ignores_directories(self, tmp_path):
        d = tmp_path / "c100-not-a-file"
        d.mkdir()
        result = rediscover_local_path(tmp_path, "confluence:100")
        assert result is None


class TestWinLongPath:
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_adds_prefix_on_windows(self, tmp_path):
        p = tmp_path / "file.txt"
        result = win_long_path(p)
        assert str(result).startswith("\\\\?\\")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
    def test_no_double_prefix(self, tmp_path):
        p = tmp_path / "file.txt"
        result = win_long_path(win_long_path(p))
        assert str(result).count("\\\\?\\") == 1

    @pytest.mark.skipif(sys.platform == "win32", reason="Non-Windows only")
    def test_noop_on_non_windows(self, tmp_path):
        p = tmp_path / "file.txt"
        assert win_long_path(p) == p


class TestCleanInsightsTree:
    def test_removes_summary_and_sidecar(self, tmp_path):
        """Flat dir with only regenerable files → fully removed."""
        d = tmp_path / "area"
        d.mkdir()
        (d / "summary.md").write_text("summary")
        (d / INSIGHT_STATE_FILENAME).write_text("{}")
        assert clean_insights_tree(d) is True
        assert not d.exists()

    def test_preserves_journal(self, tmp_path):
        """Dir with summary + journal/ → summary removed, journal preserved."""
        d = tmp_path / "area"
        d.mkdir()
        (d / "summary.md").write_text("summary")
        (d / INSIGHT_STATE_FILENAME).write_text("{}")
        journal = d / "journal" / "2026-03"
        journal.mkdir(parents=True)
        (journal / "2026-03-11.md").write_text("entry")

        assert clean_insights_tree(d) is False
        assert not (d / "summary.md").exists()
        assert not (d / INSIGHT_STATE_FILENAME).exists()
        assert (journal / "2026-03-11.md").read_text() == "entry"

    def test_recursive_subtree(self, tmp_path):
        """Nested subtree: regenerable files removed, journals preserved, empty dirs pruned."""
        root = tmp_path / "project"
        sub = root / "subarea"
        sub.mkdir(parents=True)
        (sub / "summary.md").write_text("sub summary")
        (sub / INSIGHT_STATE_FILENAME).write_text("{}")
        journal = sub / "journal" / "2026-03"
        journal.mkdir(parents=True)
        (journal / "2026-03-11.md").write_text("entry")

        (root / "summary.md").write_text("root summary")
        (root / INSIGHT_STATE_FILENAME).write_text("{}")

        assert clean_insights_tree(root) is False
        # Regenerable files removed at both levels
        assert not (root / "summary.md").exists()
        assert not (sub / "summary.md").exists()
        # Journal preserved
        assert (journal / "2026-03-11.md").read_text() == "entry"
        # Root still exists because journal subtree remains
        assert root.is_dir()

    def test_nonexistent_dir(self, tmp_path):
        """Non-existent dir → returns False, no error."""
        assert clean_insights_tree(tmp_path / "nope") is False


class TestAtomicWriteBytesLongPath:
    def test_writes_to_deeply_nested_path(self, tmp_path):
        """Ensure atomic_write_bytes works with long directory structures."""
        # Build a path with many nested directories
        deep = tmp_path
        for i in range(15):
            deep = deep / f"level-{i:02d}-with-a-longer-name"
        target = deep / "output-file-with-a-very-long-descriptive-name.md"
        atomic_write_bytes(target, b"hello world")
        assert target.exists() or Path(str(win_long_path(target))).exists()

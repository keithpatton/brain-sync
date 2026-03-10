"""Tests for brain_sync.fs_utils."""

from pathlib import Path

import pytest

from brain_sync.fs_utils import (
    find_all_content_paths,
    get_child_dirs,
    is_content_dir,
    is_readable_file,
    normalize_path,
)

pytestmark = pytest.mark.unit


class TestNormalizePath:
    def test_dot_path_returns_empty(self):
        assert normalize_path(Path(".")) == ""

    def test_dot_string_returns_empty(self):
        assert normalize_path(".") == ""

    def test_backslashes(self):
        assert normalize_path("foo\\bar\\baz") == "foo/bar/baz"

    def test_normal(self):
        assert normalize_path("foo/bar") == "foo/bar"

    def test_empty_string(self):
        assert normalize_path("") == ""


class TestIsReadableFile:
    def test_markdown_file(self, tmp_path):
        f = tmp_path / "doc.md"
        f.write_text("hello")
        assert is_readable_file(f) is True

    def test_txt_file(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("hello")
        assert is_readable_file(f) is True

    def test_image_file(self, tmp_path):
        f = tmp_path / "photo.png"
        f.write_bytes(b"\x89PNG")
        assert is_readable_file(f) is True

    def test_unsupported_extension(self, tmp_path):
        f = tmp_path / "data.xml"
        f.write_text("<xml/>")
        assert is_readable_file(f) is False

    def test_hidden_file(self, tmp_path):
        f = tmp_path / ".hidden.md"
        f.write_text("hello")
        assert is_readable_file(f) is False

    def test_underscore_prefix(self, tmp_path):
        f = tmp_path / "_private.md"
        f.write_text("hello")
        assert is_readable_file(f) is False

    def test_directory_returns_false(self, tmp_path):
        d = tmp_path / "subdir"
        d.mkdir()
        assert is_readable_file(d) is False


class TestIsContentDir:
    def test_normal_dir(self, tmp_path):
        d = tmp_path / "project"
        d.mkdir()
        assert is_content_dir(d) is True

    def test_dotdir_excluded(self, tmp_path):
        d = tmp_path / ".git"
        d.mkdir()
        assert is_content_dir(d) is False

    def test_sync_context_excluded(self, tmp_path):
        d = tmp_path / "_sync-context"
        d.mkdir()
        assert is_content_dir(d) is False

    def test_file_returns_false(self, tmp_path):
        f = tmp_path / "file.md"
        f.write_text("hello")
        assert is_content_dir(f) is False


class TestGetChildDirs:
    def test_returns_sorted_content_dirs(self, tmp_path):
        (tmp_path / "beta").mkdir()
        (tmp_path / "alpha").mkdir()
        (tmp_path / ".hidden").mkdir()
        (tmp_path / "file.md").write_text("hello")
        result = get_child_dirs(tmp_path)
        assert [p.name for p in result] == ["alpha", "beta"]

    def test_nonexistent_dir_returns_empty(self, tmp_path):
        assert get_child_dirs(tmp_path / "nope") == []

    def test_empty_dir_returns_empty(self, tmp_path):
        assert get_child_dirs(tmp_path) == []


class TestFindAllContentPaths:
    def test_flat_structure(self, tmp_path):
        root = tmp_path / "knowledge"
        (root / "project").mkdir(parents=True)
        (root / "project" / "doc.md").write_text("hello")
        result = find_all_content_paths(root)
        assert result == ["project"]

    def test_nested_deepest_first(self, tmp_path):
        root = tmp_path / "knowledge"
        (root / "area" / "sub").mkdir(parents=True)
        (root / "area" / "doc.md").write_text("parent")
        (root / "area" / "sub" / "doc.md").write_text("child")
        result = find_all_content_paths(root)
        assert result == ["area/sub", "area"]

    def test_excludes_empty_dirs(self, tmp_path):
        root = tmp_path / "knowledge"
        (root / "empty").mkdir(parents=True)
        (root / "has_file").mkdir(parents=True)
        (root / "has_file" / "doc.md").write_text("hello")
        result = find_all_content_paths(root)
        assert result == ["has_file"]

    def test_excludes_hidden_dirs(self, tmp_path):
        root = tmp_path / "knowledge"
        (root / ".hidden").mkdir(parents=True)
        (root / ".hidden" / "doc.md").write_text("hello")
        (root / "visible").mkdir(parents=True)
        (root / "visible" / "doc.md").write_text("hello")
        result = find_all_content_paths(root)
        assert result == ["visible"]

    def test_nonexistent_root_returns_empty(self, tmp_path):
        assert find_all_content_paths(tmp_path / "nope") == []

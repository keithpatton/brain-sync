"""Path safety and traversal prevention tests.

Supplements test_fs_utils.py (normalize_path) and test_mcp.py (open_file traversal)
with edge cases not covered elsewhere.
"""

from pathlib import Path

import pytest

from brain_sync.application.browse import _safe_resolve
from brain_sync.brain.tree import is_readable_file, normalize_path

pytestmark = pytest.mark.unit


# --- normalize_path edge cases ---


class TestNormalizePathEdgeCases:
    def test_mixed_separators(self):
        assert normalize_path("foo/bar\\baz") == "foo/bar/baz"

    def test_traversal_not_resolved(self):
        """normalize_path only replaces backslashes — it does NOT resolve '..'."""
        assert normalize_path("folder/../file.md") == "folder/../file.md"


# --- _safe_resolve security boundary ---


class TestSafeResolve:
    def test_normal_relative_path(self, tmp_path: Path):
        target = tmp_path / "insights" / "area" / "summary.md"
        target.parent.mkdir(parents=True)
        target.touch()

        result = _safe_resolve(tmp_path, "insights/area/summary.md")
        assert result is not None
        assert result == target.resolve()

    def test_absolute_path_rejected(self, tmp_path: Path):
        assert _safe_resolve(tmp_path, "/etc/passwd") is None

    def test_chained_dotdot_rejected(self, tmp_path: Path):
        assert _safe_resolve(tmp_path, "a/b/../../../../etc/passwd") is None

    def test_empty_path(self, tmp_path: Path):
        result = _safe_resolve(tmp_path, "")
        # Empty path resolves to root itself — must not crash or return None
        assert result is not None
        assert result == tmp_path.resolve()


# --- Unicode content discovery ---


class TestUnicodeContentDiscovery:
    def test_is_readable_file_unicode_filename(self, tmp_path: Path):
        f = tmp_path / "café-notes.md"
        f.write_text("# Notes", encoding="utf-8")
        assert is_readable_file(f) is True

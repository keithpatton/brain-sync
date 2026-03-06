from pathlib import Path

from brain_sync.fileops import (
    content_hash,
    resolve_dirty_path,
    touch_dirty,
    write_if_changed,
)
from brain_sync.manifest import Manifest, SourceEntry


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


class TestResolveDirtyPath:
    def _make_manifest(self, tmp_path, dirty_rel=None):
        manifest_path = tmp_path / "folder" / "sync-manifest.yaml"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.touch()
        return Manifest(
            path=manifest_path.resolve(),
            touch_dirty_relative_path=dirty_rel,
            sources=[],
        )

    def test_default_dirty_in_manifest_folder(self, tmp_path):
        m = self._make_manifest(tmp_path)
        dirty = resolve_dirty_path(m)
        assert dirty == m.path.parent / ".dirty"

    def test_relative_dirty_path(self, tmp_path):
        m = self._make_manifest(tmp_path, dirty_rel="../.dirty")
        dirty = resolve_dirty_path(m)
        assert dirty == (m.path.parent / "../.dirty").resolve()


class TestTouchDirty:
    def test_creates_file_if_not_exists(self, tmp_path):
        dirty = tmp_path / "sub" / ".dirty"
        touch_dirty(dirty)
        assert dirty.exists()

    def test_updates_mtime(self, tmp_path):
        import time
        dirty = tmp_path / ".dirty"
        dirty.touch()
        mtime1 = dirty.stat().st_mtime
        time.sleep(0.05)
        touch_dirty(dirty)
        mtime2 = dirty.stat().st_mtime
        assert mtime2 > mtime1

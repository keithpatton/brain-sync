from pathlib import Path

from brain_sync.fileops import (
    content_hash,
    rediscover_local_path,
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

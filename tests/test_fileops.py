from brain_sync.fileops import (
    content_hash,
    rediscover_local_path,
    write_if_changed,
)


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

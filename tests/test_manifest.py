from pathlib import Path

import pytest

from brain_sync.manifest import ManifestError, discover_manifests, load_manifest


def _write_manifest(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class TestLoadManifest:
    def test_valid_manifest(self, tmp_path):
        p = _write_manifest(tmp_path / "sync-manifest.yaml", """
touch_dirty_relative_path: ../.dirty
sources:
  - url: https://serko.atlassian.net/wiki/spaces/X/pages/123/Foo
    file: foo.md
  - url: https://docs.google.com/document/d/abc123
    file: bar.md
""")
        m = load_manifest(p)
        assert len(m.sources) == 2
        assert m.sources[0].url == "https://serko.atlassian.net/wiki/spaces/X/pages/123/Foo"
        assert m.sources[0].file == "foo.md"
        assert m.sources[1].file == "bar.md"
        assert m.touch_dirty_relative_path == "../.dirty"
        assert m.path == p.resolve()

    def test_no_dirty_path_defaults_to_none(self, tmp_path):
        p = _write_manifest(tmp_path / "sync-manifest.yaml", """
sources:
  - url: https://example.atlassian.net/wiki/spaces/X/pages/1/Test
    file: test.md
""")
        m = load_manifest(p)
        assert m.touch_dirty_relative_path is None

    def test_missing_url_raises(self, tmp_path):
        p = _write_manifest(tmp_path / "sync-manifest.yaml", """
sources:
  - file: test.md
""")
        with pytest.raises(ManifestError, match="url is required"):
            load_manifest(p)

    def test_missing_file_raises(self, tmp_path):
        p = _write_manifest(tmp_path / "sync-manifest.yaml", """
sources:
  - url: https://example.com
""")
        with pytest.raises(ManifestError, match="file is required"):
            load_manifest(p)

    def test_file_with_path_separator_raises(self, tmp_path):
        p = _write_manifest(tmp_path / "sync-manifest.yaml", """
sources:
  - url: https://example.com
    file: ../escape.md
""")
        with pytest.raises(ManifestError, match="bare filename"):
            load_manifest(p)

    def test_empty_sources_raises(self, tmp_path):
        p = _write_manifest(tmp_path / "sync-manifest.yaml", """
sources: []
""")
        with pytest.raises(ManifestError, match="non-empty list"):
            load_manifest(p)

    def test_invalid_yaml_raises(self, tmp_path):
        p = _write_manifest(tmp_path / "sync-manifest.yaml", "{{invalid")
        with pytest.raises(ManifestError, match="Invalid YAML"):
            load_manifest(p)

    def test_unknown_keys_ignored(self, tmp_path):
        p = _write_manifest(tmp_path / "sync-manifest.yaml", """
extra_key: whatever
sources:
  - url: https://example.atlassian.net/wiki/spaces/X/pages/1/Test
    file: test.md
    also_extra: true
""")
        m = load_manifest(p)
        assert len(m.sources) == 1


class TestDiscoverManifests:
    def test_finds_nested_manifests(self, tmp_path):
        _write_manifest(tmp_path / "a" / "sync-manifest.yaml", """
sources:
  - url: https://example.atlassian.net/wiki/spaces/X/pages/1/A
    file: a.md
""")
        _write_manifest(tmp_path / "b" / "c" / "sync-manifest.yaml", """
sources:
  - url: https://example.atlassian.net/wiki/spaces/X/pages/2/B
    file: b.md
""")
        manifests = discover_manifests(tmp_path)
        assert len(manifests) == 2

    def test_skips_invalid_manifests(self, tmp_path):
        _write_manifest(tmp_path / "good" / "sync-manifest.yaml", """
sources:
  - url: https://example.atlassian.net/wiki/spaces/X/pages/1/G
    file: good.md
""")
        _write_manifest(tmp_path / "bad" / "sync-manifest.yaml", "not valid yaml: {{")
        manifests = discover_manifests(tmp_path)
        assert len(manifests) == 1

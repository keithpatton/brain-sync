"""Unit tests for manifest.py — source manifest read/write utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_sync.manifest import (
    MANIFEST_DIR,
    MANIFEST_VERSION,
    SourceManifest,
    SyncHint,
    UnsupportedManifestVersion,
    clear_manifest_missing,
    delete_source_manifest,
    manifest_filename,
    mark_manifest_missing,
    read_all_source_manifests,
    read_source_manifest,
    update_manifest_materialized_path,
    update_manifest_sync_hint,
    write_source_manifest,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Create a minimal brain root with .brain-sync/sources/."""
    r = tmp_path / "brain"
    r.mkdir()
    (r / MANIFEST_DIR).mkdir(parents=True)
    return r


def _make_manifest(
    cid: str = "confluence:12345",
    url: str = "https://acme.atlassian.net/wiki/spaces/ENG/pages/12345",
    stype: str = "confluence",
    materialized: str = "engineering/c12345-some-page.md",
    **kwargs,
) -> SourceManifest:
    return SourceManifest(
        manifest_version=MANIFEST_VERSION,
        canonical_id=cid,
        source_url=url,
        source_type=stype,
        materialized_path=materialized,
        fetch_children=False,
        sync_attachments=True,
        **kwargs,
    )


class TestManifestFilename:
    def test_confluence(self):
        assert manifest_filename("confluence:12345") == "confluence-12345.json"

    def test_gdoc(self):
        assert manifest_filename("gdoc:abc123") == "gdoc-abc123.json"

    def test_attachment(self):
        assert manifest_filename("confluence-attachment:789") == "confluence-attachment-789.json"


class TestRoundTrip:
    def test_basic_roundtrip(self, root: Path):
        m = _make_manifest()
        write_source_manifest(root, m)
        loaded = read_source_manifest(root, m.canonical_id)
        assert loaded is not None
        assert loaded.canonical_id == m.canonical_id
        assert loaded.source_url == m.source_url
        assert loaded.materialized_path == m.materialized_path
        assert loaded.fetch_children is False
        assert loaded.sync_attachments is True
        assert loaded.status == "active"
        assert loaded.child_path is None
        assert loaded.sync_hint is None

    def test_roundtrip_with_sync_hint(self, root: Path):
        m = _make_manifest(sync_hint=SyncHint(content_hash="abc123", last_synced_utc="2026-03-14T10:00:00+00:00"))
        write_source_manifest(root, m)
        loaded = read_source_manifest(root, m.canonical_id)
        assert loaded is not None
        assert loaded.sync_hint is not None
        assert loaded.sync_hint.content_hash == "abc123"
        assert loaded.sync_hint.last_synced_utc == "2026-03-14T10:00:00+00:00"

    def test_roundtrip_with_child_path(self, root: Path):
        m = _make_manifest(child_path="children")
        write_source_manifest(root, m)
        loaded = read_source_manifest(root, m.canonical_id)
        assert loaded is not None
        assert loaded.child_path == "children"

    def test_roundtrip_with_missing_status(self, root: Path):
        m = _make_manifest(status="missing", missing_since_utc="2026-03-14T10:00:00+00:00")
        write_source_manifest(root, m)
        loaded = read_source_manifest(root, m.canonical_id)
        assert loaded is not None
        assert loaded.status == "missing"
        assert loaded.missing_since_utc == "2026-03-14T10:00:00+00:00"


class TestReadWrite:
    def test_read_nonexistent_returns_none(self, root: Path):
        assert read_source_manifest(root, "confluence:99999") is None

    def test_delete_removes_file(self, root: Path):
        m = _make_manifest()
        write_source_manifest(root, m)
        assert read_source_manifest(root, m.canonical_id) is not None
        delete_source_manifest(root, m.canonical_id)
        assert read_source_manifest(root, m.canonical_id) is None

    def test_delete_nonexistent_is_noop(self, root: Path):
        delete_source_manifest(root, "confluence:99999")  # should not raise

    def test_write_creates_dir_if_missing(self, tmp_path: Path):
        root = tmp_path / "brain"
        root.mkdir()
        # No .brain-sync/sources/ created yet
        m = _make_manifest()
        write_source_manifest(root, m)
        assert read_source_manifest(root, m.canonical_id) is not None

    def test_overwrite_existing(self, root: Path):
        m = _make_manifest(materialized="old/path.md")
        write_source_manifest(root, m)
        m.materialized_path = "new/path.md"
        write_source_manifest(root, m)
        loaded = read_source_manifest(root, m.canonical_id)
        assert loaded is not None
        assert loaded.materialized_path == "new/path.md"

    def test_malformed_json_returns_none(self, root: Path):
        path = root / MANIFEST_DIR / "confluence-12345.json"
        path.write_text("not json at all")
        assert read_source_manifest(root, "confluence:12345") is None


class TestReadAll:
    def test_empty_dir(self, root: Path):
        assert read_all_source_manifests(root) == {}

    def test_multiple_manifests(self, root: Path):
        m1 = _make_manifest(cid="confluence:111", url="https://acme.atlassian.net/wiki/spaces/A/pages/111")
        m2 = _make_manifest(cid="gdoc:abc", url="https://docs.google.com/document/d/abc/edit", stype="googledocs")
        write_source_manifest(root, m1)
        write_source_manifest(root, m2)
        all_m = read_all_source_manifests(root)
        assert len(all_m) == 2
        assert "confluence:111" in all_m
        assert "gdoc:abc" in all_m

    def test_skips_malformed(self, root: Path):
        m = _make_manifest()
        write_source_manifest(root, m)
        bad = root / MANIFEST_DIR / "bad-manifest.json"
        bad.write_text("{invalid")
        all_m = read_all_source_manifests(root)
        assert len(all_m) == 1

    def test_no_manifest_dir(self, tmp_path: Path):
        root = tmp_path / "brain"
        root.mkdir()
        assert read_all_source_manifests(root) == {}


class TestMissingStatus:
    def test_mark_and_clear(self, root: Path):
        m = _make_manifest()
        write_source_manifest(root, m)

        mark_manifest_missing(root, m.canonical_id, "2026-03-14T12:00:00+00:00")
        loaded = read_source_manifest(root, m.canonical_id)
        assert loaded is not None
        assert loaded.status == "missing"
        assert loaded.missing_since_utc == "2026-03-14T12:00:00+00:00"

        clear_manifest_missing(root, m.canonical_id)
        loaded = read_source_manifest(root, m.canonical_id)
        assert loaded is not None
        assert loaded.status == "active"
        assert loaded.missing_since_utc is None

    def test_mark_nonexistent_is_noop(self, root: Path):
        mark_manifest_missing(root, "confluence:99999", "2026-03-14T12:00:00+00:00")


class TestUpdateHelpers:
    def test_update_materialized_path(self, root: Path):
        m = _make_manifest(materialized="old/c12345-page.md")
        write_source_manifest(root, m)
        update_manifest_materialized_path(root, m.canonical_id, "new/c12345-page.md")
        loaded = read_source_manifest(root, m.canonical_id)
        assert loaded is not None
        assert loaded.materialized_path == "new/c12345-page.md"

    def test_update_sync_hint(self, root: Path):
        m = _make_manifest()
        write_source_manifest(root, m)
        update_manifest_sync_hint(root, m.canonical_id, "hash123", "2026-03-14T15:00:00+00:00")
        loaded = read_source_manifest(root, m.canonical_id)
        assert loaded is not None
        assert loaded.sync_hint is not None
        assert loaded.sync_hint.content_hash == "hash123"
        assert loaded.sync_hint.last_synced_utc == "2026-03-14T15:00:00+00:00"

    def test_update_nonexistent_is_noop(self, root: Path):
        update_manifest_materialized_path(root, "confluence:99999", "any/path.md")
        update_manifest_sync_hint(root, "confluence:99999", "hash", "2026-01-01")


class TestJsonFormat:
    def test_omits_none_optional_fields(self, root: Path):
        m = _make_manifest()
        write_source_manifest(root, m)
        path = root / MANIFEST_DIR / manifest_filename(m.canonical_id)
        data = json.loads(path.read_text())
        assert "missing_since_utc" not in data
        assert "child_path" not in data
        assert "sync_hint" not in data

    def test_version_field_present(self, root: Path):
        m = _make_manifest()
        write_source_manifest(root, m)
        path = root / MANIFEST_DIR / manifest_filename(m.canonical_id)
        data = json.loads(path.read_text())
        assert data["manifest_version"] == MANIFEST_VERSION


class TestVersionValidation:
    def test_unsupported_version_raises_on_single_read(self, root: Path):
        m = _make_manifest()
        write_source_manifest(root, m)
        # Overwrite with a future version
        path = root / MANIFEST_DIR / manifest_filename(m.canonical_id)
        data = json.loads(path.read_text())
        data["manifest_version"] = 999
        path.write_text(json.dumps(data))
        with pytest.raises(UnsupportedManifestVersion) as exc_info:
            read_source_manifest(root, m.canonical_id)
        assert exc_info.value.version == 999

    def test_unsupported_version_raises_on_read_all(self, root: Path):
        m = _make_manifest()
        write_source_manifest(root, m)
        path = root / MANIFEST_DIR / manifest_filename(m.canonical_id)
        data = json.loads(path.read_text())
        data["manifest_version"] = 999
        path.write_text(json.dumps(data))
        with pytest.raises(UnsupportedManifestVersion):
            read_all_source_manifests(root)

    def test_missing_version_returns_none(self, root: Path):
        path = root / MANIFEST_DIR / "confluence-12345.json"
        path.write_text(json.dumps({"canonical_id": "confluence:12345"}))
        assert read_source_manifest(root, "confluence:12345") is None

    def test_invalid_version_type_returns_none(self, root: Path):
        path = root / MANIFEST_DIR / "confluence-12345.json"
        path.write_text(json.dumps({"manifest_version": "not_a_number", "canonical_id": "confluence:12345"}))
        assert read_source_manifest(root, "confluence:12345") is None

    def test_zero_version_returns_none(self, root: Path):
        path = root / MANIFEST_DIR / "confluence-12345.json"
        path.write_text(json.dumps({"manifest_version": 0, "canonical_id": "confluence:12345"}))
        assert read_source_manifest(root, "confluence:12345") is None

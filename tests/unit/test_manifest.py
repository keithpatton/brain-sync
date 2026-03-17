"""Unit tests for spec-aligned source manifests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_sync.brain.manifest import (
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
    result = tmp_path / "brain"
    result.mkdir()
    (result / MANIFEST_DIR).mkdir(parents=True)
    return result


def _make_manifest(**kwargs: object) -> SourceManifest:
    return SourceManifest(
        version=MANIFEST_VERSION,
        canonical_id="confluence:12345",
        source_url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345",
        source_type="confluence",
        materialized_path="engineering/c12345-some-page.md",
        sync_attachments=True,
        target_path="engineering",
        **kwargs,
    )


class TestManifestFilename:
    def test_uses_source_dir_id_for_confluence(self) -> None:
        assert manifest_filename("confluence:12345") == "c12345.json"

    def test_uses_source_dir_id_for_google_docs(self) -> None:
        assert manifest_filename("gdoc:abc123") == "gabc123.json"

    def test_uses_source_dir_id_for_attachments(self) -> None:
        assert manifest_filename("confluence-attachment:789") == "a789.json"


class TestRoundTrip:
    def test_basic_roundtrip(self, root: Path) -> None:
        manifest = _make_manifest()
        write_source_manifest(root, manifest)

        loaded = read_source_manifest(root, manifest.canonical_id)

        assert loaded is not None
        assert loaded.version == MANIFEST_VERSION
        assert loaded.canonical_id == manifest.canonical_id
        assert loaded.target_path == "engineering"
        assert loaded.status == "active"
        assert loaded.fetch_children is False
        assert loaded.child_path is None

    def test_sync_hint_roundtrip(self, root: Path) -> None:
        manifest = _make_manifest(sync_hint=SyncHint(content_hash="abc123", last_synced_utc="2026-03-14T10:00:00Z"))
        write_source_manifest(root, manifest)

        loaded = read_source_manifest(root, manifest.canonical_id)

        assert loaded is not None
        assert loaded.sync_hint is not None
        assert loaded.sync_hint.content_hash == "abc123"
        assert loaded.sync_hint.last_synced_utc == "2026-03-14T10:00:00Z"

    def test_missing_status_roundtrip(self, root: Path) -> None:
        manifest = _make_manifest(status="missing", missing_since_utc="2026-03-14T10:00:00Z")
        write_source_manifest(root, manifest)

        loaded = read_source_manifest(root, manifest.canonical_id)

        assert loaded is not None
        assert loaded.status == "missing"
        assert loaded.missing_since_utc == "2026-03-14T10:00:00Z"


class TestLegacyReadTolerance:
    def test_reads_manifest_version_and_one_shot_fields_as_fallback(self, root: Path) -> None:
        path = root / MANIFEST_DIR / "c12345.json"
        path.write_text(
            json.dumps(
                {
                    "manifest_version": 1,
                    "canonical_id": "confluence:12345",
                    "source_url": "https://example.com",
                    "source_type": "confluence",
                    "materialized_path": "",
                    "target_path": "",
                    "sync_attachments": False,
                    "fetch_children": True,
                    "child_path": "children",
                }
            ),
            encoding="utf-8",
        )

        loaded = read_source_manifest(root, "confluence:12345")

        assert loaded is not None
        assert loaded.version == 1
        assert loaded.fetch_children is True
        assert loaded.child_path == "children"

    def test_reads_google_doc_durable_type_and_maps_back_to_runtime_value(self, root: Path) -> None:
        manifest = SourceManifest(
            version=1,
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
            materialized_path="shared/gabc123-doc.md",
            sync_attachments=False,
            target_path="shared",
        )
        write_source_manifest(root, manifest)

        data = json.loads((root / MANIFEST_DIR / "gabc123.json").read_text(encoding="utf-8"))
        loaded = read_source_manifest(root, "gdoc:abc123")

        assert data["source_type"] == "google_doc"
        assert loaded is not None
        assert loaded.source_type == "googledocs"


class TestUpdateHelpers:
    def test_delete_and_update_helpers(self, root: Path) -> None:
        manifest = _make_manifest()
        write_source_manifest(root, manifest)

        update_manifest_materialized_path(root, manifest.canonical_id, "moved/c12345.md")
        update_manifest_sync_hint(root, manifest.canonical_id, "hash123", "2026-03-14T15:00:00Z")
        mark_manifest_missing(root, manifest.canonical_id, "2026-03-14T16:00:00Z")
        clear_manifest_missing(root, manifest.canonical_id)

        loaded = read_source_manifest(root, manifest.canonical_id)
        assert loaded is not None
        assert loaded.materialized_path == "moved/c12345.md"
        assert loaded.sync_hint is not None
        assert loaded.sync_hint.content_hash == "hash123"
        assert loaded.status == "active"

        delete_source_manifest(root, manifest.canonical_id)
        assert read_source_manifest(root, manifest.canonical_id) is None


class TestJsonFormat:
    def test_writes_version_and_omits_removed_runtime_only_fields(self, root: Path) -> None:
        manifest = _make_manifest(fetch_children=True, child_path="children")
        write_source_manifest(root, manifest)

        data = json.loads((root / MANIFEST_DIR / "c12345.json").read_text(encoding="utf-8"))

        assert data["version"] == MANIFEST_VERSION
        assert data["target_path"] == "engineering"
        assert "manifest_version" not in data
        assert "fetch_children" not in data
        assert "child_path" not in data


class TestVersionValidation:
    def test_unsupported_version_raises(self, root: Path) -> None:
        manifest = _make_manifest()
        write_source_manifest(root, manifest)
        path = root / MANIFEST_DIR / "c12345.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["version"] = 999
        path.write_text(json.dumps(data), encoding="utf-8")

        with pytest.raises(UnsupportedManifestVersion):
            read_source_manifest(root, manifest.canonical_id)

    def test_read_all_returns_manifests_by_canonical_id(self, root: Path) -> None:
        write_source_manifest(root, _make_manifest())
        write_source_manifest(
            root,
            SourceManifest(
                version=1,
                canonical_id="gdoc:abc123",
                source_url="https://docs.google.com/document/d/abc123/edit",
                source_type="googledocs",
                materialized_path="shared/gabc123-doc.md",
                sync_attachments=False,
                target_path="shared",
            ),
        )

        manifests = read_all_source_manifests(root)

        assert set(manifests) == {"confluence:12345", "gdoc:abc123"}

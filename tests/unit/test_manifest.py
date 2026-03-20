"""Unit tests for Brain Format 1.2 source manifests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_sync.brain.manifest import (
    MANIFEST_DIR,
    MANIFEST_VERSION,
    ManifestValidationError,
    SourceManifest,
    UnsupportedManifestVersion,
    clear_manifest_missing,
    delete_source_manifest,
    derive_provisional_knowledge_path,
    manifest_filename,
    mark_manifest_missing,
    read_all_source_manifests,
    read_source_manifest,
    update_manifest_knowledge_path,
    update_manifest_materialization,
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
    data: dict[str, object] = {
        "version": MANIFEST_VERSION,
        "canonical_id": "confluence:12345",
        "source_url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/12345",
        "source_type": "confluence",
        "sync_attachments": True,
        "knowledge_path": "engineering/c12345-some-page.md",
        "knowledge_state": "materialized",
        "content_hash": "sha256:abc123",
        "remote_fingerprint": "42",
        "materialized_utc": "2026-03-19T08:00:00+00:00",
    }
    data.update(kwargs)
    return SourceManifest(**data)


def test_manifest_filename_uses_source_dir_id() -> None:
    assert manifest_filename("confluence:12345") == "c12345.json"
    assert manifest_filename("gdoc:abc123") == "gabc123.json"


def test_derive_provisional_knowledge_path_anchors_to_area() -> None:
    assert derive_provisional_knowledge_path("engineering", "confluence:12345") == "engineering/c12345.md"
    assert derive_provisional_knowledge_path("", "confluence:12345") == "c12345.md"


def test_roundtrip_materialized_manifest(root: Path) -> None:
    manifest = _make_manifest()
    write_source_manifest(root, manifest)

    loaded = read_source_manifest(root, manifest.canonical_id)

    assert loaded == manifest
    assert loaded is not None
    assert loaded.target_path == "engineering"


@pytest.mark.parametrize(
    ("knowledge_state", "expected_json"),
    [
        ("awaiting", {"knowledge_state": "awaiting", "knowledge_path": "engineering/c12345-awaiting.md"}),
        (
            "materialized",
            {
                "knowledge_state": "materialized",
                "knowledge_path": "engineering/c12345-some-page.md",
                "content_hash": "sha256:abc123",
                "remote_fingerprint": "42",
                "materialized_utc": "2026-03-19T08:00:00+00:00",
            },
        ),
        (
            "stale",
            {
                "knowledge_state": "stale",
                "knowledge_path": "engineering/c12345-some-page.md",
                "content_hash": "sha256:abc123",
                "remote_fingerprint": "42",
                "materialized_utc": "2026-03-19T08:00:00+00:00",
            },
        ),
        (
            "missing",
            {
                "knowledge_state": "missing",
                "knowledge_path": "engineering/c12345-some-page.md",
                "content_hash": "sha256:abc123",
                "remote_fingerprint": "42",
                "materialized_utc": "2026-03-19T08:00:00+00:00",
            },
        ),
    ],
)
def test_state_matrix_serializes_valid_pairings(
    root: Path,
    knowledge_state: str,
    expected_json: dict[str, str],
) -> None:
    if knowledge_state == "awaiting":
        manifest = SourceManifest(
            version=MANIFEST_VERSION,
            canonical_id="confluence:12345",
            source_url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345",
            source_type="confluence",
            sync_attachments=False,
            knowledge_path="engineering/c12345-awaiting.md",
            knowledge_state="awaiting",
        )
    elif knowledge_state == "missing":
        manifest = _make_manifest(knowledge_state="missing")
    else:
        manifest = _make_manifest(knowledge_state=knowledge_state)

    write_source_manifest(root, manifest)
    data = json.loads((root / MANIFEST_DIR / "c12345.json").read_text(encoding="utf-8"))

    for key, value in expected_json.items():
        assert data[key] == value


@pytest.mark.parametrize(
    "kwargs",
    [
        {"knowledge_state": "awaiting", "content_hash": "sha256:bad"},
        {"knowledge_state": "materialized", "content_hash": None},
        {"knowledge_state": "materialized", "remote_fingerprint": None},
        {"knowledge_state": "stale", "materialized_utc": None},
        {"knowledge_path": "engineering"},
        {"knowledge_path": "../escape.md"},
    ],
)
def test_invalid_state_pairings_raise(kwargs: dict[str, object]) -> None:
    with pytest.raises(ManifestValidationError):
        _make_manifest(**kwargs)


def test_missing_helpers_and_materialization_helpers(root: Path) -> None:
    manifest = _make_manifest()
    write_source_manifest(root, manifest)

    mark_manifest_missing(root, manifest.canonical_id, "2026-03-19T10:00:00+00:00")
    missing_manifest = read_source_manifest(root, manifest.canonical_id)
    assert missing_manifest is not None
    assert missing_manifest.knowledge_state == "missing"
    assert missing_manifest.missing_since_utc is None

    clear_manifest_missing(root, manifest.canonical_id)
    stale_manifest = read_source_manifest(root, manifest.canonical_id)
    assert stale_manifest is not None
    assert stale_manifest.knowledge_state == "stale"
    assert stale_manifest.missing_since_utc is None
    update_manifest_knowledge_path(root, manifest.canonical_id, "archive/c12345-renamed.md")
    update_manifest_materialization(
        root,
        manifest.canonical_id,
        knowledge_path="archive/c12345-renamed.md",
        content_hash="sha256:def456",
        remote_fingerprint="43",
        materialized_utc="2026-03-19T11:00:00+00:00",
    )

    loaded = read_source_manifest(root, manifest.canonical_id)
    assert loaded is not None
    assert loaded.knowledge_path == "archive/c12345-renamed.md"
    assert loaded.knowledge_state == "materialized"
    assert loaded.content_hash == "sha256:def456"
    assert loaded.remote_fingerprint == "43"

    delete_source_manifest(root, manifest.canonical_id)
    assert read_source_manifest(root, manifest.canonical_id) is None


def test_read_all_returns_manifests_by_canonical_id(root: Path) -> None:
    write_source_manifest(root, _make_manifest())
    write_source_manifest(
        root,
        SourceManifest(
            version=MANIFEST_VERSION,
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
            sync_attachments=False,
            knowledge_path="shared/gabc123-doc.md",
            knowledge_state="awaiting",
        ),
    )

    manifests = read_all_source_manifests(root)

    assert set(manifests) == {"confluence:12345", "gdoc:abc123"}


def test_unsupported_version_raises(root: Path) -> None:
    manifest = _make_manifest()
    write_source_manifest(root, manifest)
    path = root / MANIFEST_DIR / "c12345.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UnsupportedManifestVersion):
        read_source_manifest(root, manifest.canonical_id)

"""Integration tests for manifest-authoritative load_state() behavior (v21+)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from brain_sync.commands.init import init_brain
from brain_sync.manifest import (
    MANIFEST_VERSION,
    SourceManifest,
    delete_source_manifest,
    read_all_source_manifests,
    write_source_manifest,
)
from brain_sync.state import (
    SourceState,
    SyncState,
    load_state,
    save_state,
)

pytestmark = pytest.mark.integration

CONFLUENCE_URL = "https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    return root


def _make_manifest(cid: str, url: str, tp: str = "") -> SourceManifest:
    return SourceManifest(
        manifest_version=MANIFEST_VERSION,
        canonical_id=cid,
        source_url=url,
        source_type="confluence",
        materialized_path="",
        fetch_children=False,
        sync_attachments=False,
        target_path=tp,
    )


class TestManifestAuthority:
    def test_no_manifest_dir_returns_empty(self, brain: Path):
        """No .brain-sync/sources/ → load_state returns empty (manifests are required)."""
        manifest_dir = brain / ".brain-sync" / "sources"
        if manifest_dir.is_dir():
            shutil.rmtree(manifest_dir)

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
            last_checked_utc="2026-03-14T10:00:00",
        )
        save_state(brain, state)

        loaded = load_state(brain)
        # No manifests → no sources, regardless of DB cache
        assert len(loaded.sources) == 0

    def test_manifest_authority_with_db_progress(self, brain: Path):
        """Manifests provide intent, DB provides progress — merged correctly."""
        write_source_manifest(brain, _make_manifest(CONFLUENCE_CID, CONFLUENCE_URL, "area"))

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
            last_checked_utc="2026-03-14T10:00:00",
        )
        save_state(brain, state)

        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources
        # Intent from manifest
        assert loaded.sources[CONFLUENCE_CID].source_url == CONFLUENCE_URL
        assert loaded.sources[CONFLUENCE_CID].target_path == "area"
        # Progress from DB
        assert loaded.sources[CONFLUENCE_CID].last_checked_utc == "2026-03-14T10:00:00"

    def test_after_manifest_deletion_source_excluded(self, brain: Path):
        """After manifest deletion, source is excluded from load_state."""
        write_source_manifest(brain, _make_manifest(CONFLUENCE_CID, CONFLUENCE_URL, "area"))
        write_source_manifest(
            brain,
            _make_manifest(
                "confluence:99999",
                "https://example.atlassian.net/wiki/spaces/TEAM/pages/99999",
                "other",
            ),
        )

        state = SyncState()
        for cid in [CONFLUENCE_CID, "confluence:99999"]:
            state.sources[cid] = SourceState(
                canonical_id=cid,
                source_url="",
                source_type="",
                last_checked_utc="2026-01-01T00:00:00",
            )
        save_state(brain, state)

        delete_source_manifest(brain, "confluence:99999")

        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources
        assert "confluence:99999" not in loaded.sources

    def test_empty_manifest_dir_with_sync_cache_only(self, brain: Path):
        """Empty manifest dir + sync_cache rows → no bootstrap (v21 has no intent in DB)."""
        manifest_dir = brain / ".brain-sync" / "sources"
        if manifest_dir.is_dir():
            shutil.rmtree(manifest_dir)
        manifest_dir.mkdir(parents=True)

        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="eng",
            last_checked_utc="2026-03-14T10:00:00",
            content_hash="abc",
        )
        save_state(brain, state)

        # v21: sync_cache has no intent → bootstrap can't create manifests → no sources
        loaded = load_state(brain)
        assert len(loaded.sources) == 0

        manifests = read_all_source_manifests(brain)
        assert len(manifests) == 0

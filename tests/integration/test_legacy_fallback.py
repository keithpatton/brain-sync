"""Integration tests for legacy (pre-Phase-2) fallback behavior."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from brain_sync.commands.init import init_brain
from brain_sync.commands.sources import _bootstrap_manifests_from_db
from brain_sync.manifest import read_all_source_manifests
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


class TestLegacyFallback:
    def test_no_manifest_dir_returns_db_only(self, brain: Path):
        """No .brain-sync/sources/ → load_state returns DB-only state."""
        # Remove manifest dir to simulate pre-Phase-2 brain
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
        assert CONFLUENCE_CID in loaded.sources
        assert loaded.sources[CONFLUENCE_CID].target_path == "area"

    def test_bootstrap_then_manifest_authority(self, brain: Path):
        """After bootstrap, subsequent load_state uses manifest authority."""
        # Create DB source
        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
            last_checked_utc="2026-03-14T10:00:00",
        )
        save_state(brain, state)

        # Bootstrap creates manifests
        _bootstrap_manifests_from_db(brain, state)

        manifests = read_all_source_manifests(brain)
        assert len(manifests) == 1
        assert CONFLUENCE_CID in manifests

        # Subsequent load_state uses manifest authority
        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources

    def test_after_bootstrap_db_only_sources_excluded(self, brain: Path):
        """After bootstrap, DB-only sources (no manifest) are excluded."""
        # Create two DB sources
        state = SyncState()
        state.sources[CONFLUENCE_CID] = SourceState(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
            last_checked_utc="2026-01-01T00:00:00",
        )
        state.sources["confluence:99999"] = SourceState(
            canonical_id="confluence:99999",
            source_url="https://example.atlassian.net/wiki/spaces/TEAM/pages/99999",
            source_type="confluence",
            target_path="other",
            last_checked_utc="2026-01-01T00:00:00",
        )
        save_state(brain, state)

        # Bootstrap only creates manifests for existing DB sources
        _bootstrap_manifests_from_db(brain, state)

        # Delete one manifest to simulate a source that was removed from manifests
        from brain_sync.manifest import delete_source_manifest

        delete_source_manifest(brain, "confluence:99999")

        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources
        assert "confluence:99999" not in loaded.sources

    def test_empty_manifest_dir_with_db_sources_bootstraps(self, brain: Path):
        """Empty .brain-sync/sources/ dir + DB rows → load_state bootstraps manifests."""
        # Remove any existing manifests (init_brain may create the dir)
        manifest_dir = brain / ".brain-sync" / "sources"
        if manifest_dir.is_dir():
            shutil.rmtree(manifest_dir)
        manifest_dir.mkdir(parents=True)

        # Create a DB source with progress
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

        # load_state should bootstrap and return the source
        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources
        assert loaded.sources[CONFLUENCE_CID].target_path == "eng"
        assert loaded.sources[CONFLUENCE_CID].content_hash == "abc"

        # Manifests should now exist
        manifests = read_all_source_manifests(brain)
        assert CONFLUENCE_CID in manifests

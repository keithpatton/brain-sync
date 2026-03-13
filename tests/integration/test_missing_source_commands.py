"""Integration tests for managing missing-status sources."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.commands.init import init_brain
from brain_sync.commands.sources import (
    add_source,
    list_sources,
    remove_source,
    update_source,
)
from brain_sync.manifest import mark_manifest_missing, read_source_manifest
from brain_sync.state import load_state

pytestmark = pytest.mark.integration

CONFLUENCE_URL = "https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    return root


class TestMissingSourceCommands:
    def test_remove_missing_source(self, brain: Path):
        """Explicit remove of a missing-status source works (bypasses grace period)."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        # Source not in load_state (missing excluded)
        state = load_state(brain)
        assert CONFLUENCE_CID not in state.sources

        # But remove still works via manifest fallback
        result = remove_source(root=brain, source=CONFLUENCE_CID)
        assert result.canonical_id == CONFLUENCE_CID
        assert read_source_manifest(brain, CONFLUENCE_CID) is None

    def test_update_missing_source(self, brain: Path):
        """Explicit update of a missing-status source works."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        result = update_source(root=brain, source=CONFLUENCE_CID, sync_attachments=True)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.sync_attachments is True

        # Manifest updated
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        assert m.sync_attachments is True

    def test_missing_source_not_in_list(self, brain: Path):
        """Missing-status source excluded from list_sources."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        sources = list_sources(root=brain)
        assert len(sources) == 0

    def test_missing_source_not_scheduled(self, brain: Path):
        """Missing-status source not in load_state → daemon can't schedule it."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        state = load_state(brain)
        assert CONFLUENCE_CID not in state.sources

"""Integration tests for placement intent preservation via target_path."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.source_state import load_state
from brain_sync.application.sources import add_source
from brain_sync.brain.manifest import (
    read_source_manifest,
    write_source_manifest,
)
from brain_sync.runtime.repository import (
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


class TestPlacementIntent:
    def test_add_preserves_target_path_in_manifest(self, brain: Path):
        """add_source writes target_path to manifest."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="engineering")
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        assert m.target_path == "engineering"

    def test_db_delete_preserves_target_path(self, brain: Path):
        """After DB deletion, load_state returns source with correct target_path."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="engineering")
        (brain / ".sync-state.sqlite").unlink(missing_ok=True)

        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources
        assert loaded.sources[CONFLUENCE_CID].target_path == "engineering"

    def test_manifest_without_target_path_stays_empty(self, brain: Path):
        """Manifest without target_path — no DB backfill in v21+ (target_path is manifest-only)."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="engineering")

        # Write a manifest without target_path (simulates Phase 1 manifest)
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.target_path = ""
        m.materialized_path = ""
        write_source_manifest(brain, m)

        # v21+: sync_cache has no target_path, so load_state cannot backfill from DB.
        # target_path stays empty.
        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.target_path == ""

    def test_phase1_manifest_materialized_derives_target(self, brain: Path):
        """Phase 1 manifest with materialized_path but no target_path → derives from parent."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="")

        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.target_path = ""
        m.materialized_path = "eng/arch/c12345-page.md"
        write_source_manifest(brain, m)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.target_path == "eng/arch"

    def test_root_path_vs_unmaterialized_distinct(self, brain: Path):
        """Root-path source (target="", materialized="c12345.md") vs unmaterialized are distinct."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="")

        # Root-path source: file at knowledge root
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.materialized_path = "c12345-page.md"
        write_source_manifest(brain, m)

        loaded = load_state(brain)
        ss = loaded.sources[CONFLUENCE_CID]
        assert ss.target_path == ""  # root, not "unmaterialized"
        assert ss.source_url == CONFLUENCE_URL

    def test_backfill_does_not_trigger_schedule_change(self, brain: Path):
        """Backfill writes manifest but doesn't change DB progress fields."""
        add_source(root=brain, url=CONFLUENCE_URL, target_path="engineering")

        # Save progress in DB
        state = load_state(brain)
        ss = state.sources[CONFLUENCE_CID]
        ss.last_checked_utc = "2026-03-14T10:00:00"
        ss.next_check_utc = "2026-03-14T10:30:00"
        ss.interval_seconds = 1800
        save_state(brain, state)

        # In v21, target_path is manifest-only. Clearing it in the manifest means
        # it stays empty (no DB backfill possible from sync_cache).
        m = read_source_manifest(brain, CONFLUENCE_CID)
        assert m is not None
        m.target_path = ""
        m.materialized_path = ""
        write_source_manifest(brain, m)

        loaded = load_state(brain)
        ss2 = loaded.sources[CONFLUENCE_CID]
        # v21: no DB backfill, target_path stays empty
        assert ss2.target_path == ""
        # Progress fields unchanged
        assert ss2.last_checked_utc == "2026-03-14T10:00:00"
        assert ss2.next_check_utc == "2026-03-14T10:30:00"
        assert ss2.interval_seconds == 1800

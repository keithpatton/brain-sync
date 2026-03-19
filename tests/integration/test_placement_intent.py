"""Integration tests for provisional knowledge-path anchoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.source_state import load_state, save_state
from brain_sync.application.sources import add_source
from brain_sync.brain.manifest import read_source_manifest

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
    def test_add_anchors_provisional_knowledge_path_in_manifest(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="engineering")
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_path == "engineering/c12345.md"
        assert manifest.target_path == "engineering"
        assert manifest.knowledge_state == "awaiting"

    def test_db_delete_preserves_target_path(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="engineering")
        loaded = load_state(brain)
        loaded.sources[CONFLUENCE_CID].next_check_utc = "2026-03-19T11:00:00+00:00"
        save_state(brain, loaded)

        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources
        assert loaded.sources[CONFLUENCE_CID].target_path == "engineering"

    def test_materialized_source_uses_parent_of_knowledge_path(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="")

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "eng/arch/c12345-page.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        from brain_sync.brain.manifest import write_source_manifest

        write_source_manifest(brain, manifest)

        loaded = load_state(brain)
        assert loaded.sources[CONFLUENCE_CID].target_path == "eng/arch"

    def test_root_materialized_path_round_trips_as_root_target(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="")

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "c12345-page.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        from brain_sync.brain.manifest import write_source_manifest

        write_source_manifest(brain, manifest)

        loaded = load_state(brain)
        assert loaded.sources[CONFLUENCE_CID].target_path == ""
        assert loaded.sources[CONFLUENCE_CID].source_url == CONFLUENCE_URL

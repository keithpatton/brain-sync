"""Integration tests for manifest-authoritative load_state fallback behavior."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.source_state import SourceState, SyncState, load_state, save_state
from brain_sync.brain.manifest import (
    MANIFEST_VERSION,
    SourceManifest,
    delete_source_manifest,
    read_all_source_manifests,
    write_source_manifest,
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


def _make_manifest(cid: str, url: str, knowledge_path: str = "area/c12345.md") -> SourceManifest:
    return SourceManifest(
        version=MANIFEST_VERSION,
        canonical_id=cid,
        source_url=url,
        source_type="confluence",
        sync_attachments=False,
        knowledge_path=knowledge_path,
        knowledge_state="awaiting",
    )


class TestManifestAuthority:
    def test_no_manifest_dir_returns_empty(self, brain: Path) -> None:
        manifest_dir = brain / ".brain-sync" / "sources"
        if manifest_dir.is_dir():
            shutil.rmtree(manifest_dir)

        state = SyncState(
            sources={
                CONFLUENCE_CID: SourceState(
                    canonical_id=CONFLUENCE_CID,
                    source_url=CONFLUENCE_URL,
                    source_type="confluence",
                    next_check_utc="2026-03-19T11:00:00+00:00",
                )
            }
        )
        save_state(brain, state)

        loaded = load_state(brain)
        assert len(loaded.sources) == 0

    def test_manifest_authority_with_runtime_polling(self, brain: Path) -> None:
        write_source_manifest(brain, _make_manifest(CONFLUENCE_CID, CONFLUENCE_URL, "area/c12345.md"))

        state = SyncState(
            sources={
                CONFLUENCE_CID: SourceState(
                    canonical_id=CONFLUENCE_CID,
                    source_url=CONFLUENCE_URL,
                    source_type="confluence",
                    knowledge_path="area/c12345.md",
                    next_check_utc="2026-03-19T11:00:00+00:00",
                )
            }
        )
        save_state(brain, state)

        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources
        assert loaded.sources[CONFLUENCE_CID].source_url == CONFLUENCE_URL
        assert loaded.sources[CONFLUENCE_CID].target_path == "area"
        assert loaded.sources[CONFLUENCE_CID].next_check_utc == "2026-03-19T11:00:00+00:00"

    def test_after_manifest_deletion_source_excluded(self, brain: Path) -> None:
        write_source_manifest(brain, _make_manifest(CONFLUENCE_CID, CONFLUENCE_URL, "area/c12345.md"))
        write_source_manifest(
            brain,
            _make_manifest(
                "confluence:99999",
                "https://example.atlassian.net/wiki/spaces/TEAM/pages/99999",
                "other/c99999.md",
            ),
        )

        state = SyncState(
            sources={
                CONFLUENCE_CID: SourceState(
                    canonical_id=CONFLUENCE_CID,
                    source_url=CONFLUENCE_URL,
                    source_type="confluence",
                    next_check_utc="2026-03-19T11:00:00+00:00",
                ),
                "confluence:99999": SourceState(
                    canonical_id="confluence:99999",
                    source_url="https://example.atlassian.net/wiki/spaces/TEAM/pages/99999",
                    source_type="confluence",
                    next_check_utc="2026-03-19T11:00:00+00:00",
                ),
            }
        )
        save_state(brain, state)

        delete_source_manifest(brain, "confluence:99999")

        loaded = load_state(brain)
        assert CONFLUENCE_CID in loaded.sources
        assert "confluence:99999" not in loaded.sources

    def test_empty_manifest_dir_with_runtime_rows_does_not_bootstrap(self, brain: Path) -> None:
        manifest_dir = brain / ".brain-sync" / "sources"
        if manifest_dir.is_dir():
            shutil.rmtree(manifest_dir)
        manifest_dir.mkdir(parents=True)

        state = SyncState(
            sources={
                CONFLUENCE_CID: SourceState(
                    canonical_id=CONFLUENCE_CID,
                    source_url=CONFLUENCE_URL,
                    source_type="confluence",
                    next_check_utc="2026-03-19T11:00:00+00:00",
                )
            }
        )
        save_state(brain, state)

        loaded = load_state(brain)
        assert len(loaded.sources) == 0
        assert len(read_all_source_manifests(brain)) == 0

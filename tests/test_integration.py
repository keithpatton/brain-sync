"""Integration test: full sync flow with mocked Confluence REST API.

Exercises:
1. Start with empty root
2. Register a source via SourceState
3. Pipeline fetches content (mocked REST API)
4. Markdown file written to knowledge/<target_path>/
5. State updated with correct fields
6. Second run with unchanged content skips write
7. Second run with changed content triggers state reset
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from brain_sync.confluence_rest import ConfluenceAuth
from brain_sync.manifest import discover_manifests
from brain_sync.pipeline import process_source
from brain_sync.scheduler import Scheduler, compute_interval
from brain_sync.state import (
    SourceState,
    SyncState,
    load_state,
    save_state,
    source_key_for_entry,
)

pytestmark = pytest.mark.integration

FAKE_PAGE_ID = "12345"
FAKE_URL = f"https://test.atlassian.net/wiki/spaces/X/pages/{FAKE_PAGE_ID}/TestPage"

FAKE_HTML_V1 = "<h1>Test Page</h1><p>Version one content.</p>"
FAKE_HTML_V2 = "<h1>Test Page</h1><p>Version two content with changes.</p>"
FAKE_COMMENTS_MD = "**Alice** (2026-01-01T00:00:00Z)\nGreat work!\n\n" "**Bob** (2026-01-02T00:00:00Z)\nNeeds review."

FAKE_AUTH = ConfluenceAuth(
    domain="test.atlassian.net",
    email="test@example.com",
    token="fake-token",
)


def _write_manifest(root: Path, rel_dir: str = "project") -> Path:
    manifest_dir = root / rel_dir
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "sync-manifest.yaml"
    manifest_path.write_text(
        f"""
touch_dirty_relative_path: ../.dirty
sources:
  - url: {FAKE_URL}
    file: test-page.md
""",
        encoding="utf-8",
    )
    return manifest_path


def _mock_rest(
    html: str,
    title: str = "TestPage",
    version: int = 1,
    comments: str | None = FAKE_COMMENTS_MD,
):
    """Create patches for REST API functions."""
    return {
        "get_confluence_auth": lambda: FAKE_AUTH,
        "fetch_page_version": AsyncMock(return_value=version),
        "fetch_page_body": AsyncMock(return_value=(html, title, version)),
        "fetch_comments": AsyncMock(return_value=comments),
    }


class TestFullSyncFlow:
    """Integration test: source registration -> fetch -> write -> state."""

    @pytest.fixture
    def root(self, tmp_path):
        return tmp_path / "sync-root"

    def _run_with_mocks(self, source_state, root, html, version=1, comments=FAKE_COMMENTS_MD):
        mocks = _mock_rest(html, version=version, comments=comments)
        with patch.multiple("brain_sync.pipeline", **mocks):
            return asyncio.run(process_source(source_state, httpx.AsyncClient(), root))

    def test_first_sync_creates_output(self, root):
        """Register source, run pipeline, verify file + state."""
        root.mkdir()
        target_path = "project"

        key = source_key_for_entry(FAKE_URL)
        state = SyncState()
        state.sources[key] = SourceState(
            canonical_id=key,
            source_url=FAKE_URL,
            source_type="confluence",
            target_path=target_path,
        )

        changed = self._run_with_mocks(state.sources[key], root, FAKE_HTML_V1)

        # File written to knowledge/<target_path>/
        knowledge_dir = root / "knowledge" / target_path
        assert knowledge_dir.exists()
        md_files = list(knowledge_dir.glob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")
        assert "# Test Page" in content
        assert "Version one content." in content
        assert "## Comments" in content
        assert "Great work!" in content
        assert changed is True

        # State updated
        ss = state.sources[key]
        assert ss.last_checked_utc is not None
        assert ss.last_changed_utc is not None
        assert ss.content_hash is not None
        assert ss.source_type == "confluence"

    def test_unchanged_content_skips_write(self, root):
        """Second run with same content: no file rewrite."""
        root.mkdir()
        target_path = "project"

        key = source_key_for_entry(FAKE_URL)
        state = SyncState()
        state.sources[key] = SourceState(
            canonical_id=key,
            source_url=FAKE_URL,
            source_type="confluence",
            target_path=target_path,
        )

        # First run
        self._run_with_mocks(state.sources[key], root, FAKE_HTML_V1)

        first_changed_utc = state.sources[key].last_changed_utc
        time.sleep(0.05)

        # Second run — same content
        changed = self._run_with_mocks(state.sources[key], root, FAKE_HTML_V1)

        assert changed is False
        # last_changed_utc should NOT have been updated
        assert state.sources[key].last_changed_utc == first_changed_utc

    def test_changed_content_triggers_state_reset(self, root):
        """Content change: file rewritten, state updated."""
        root.mkdir()
        target_path = "project"

        key = source_key_for_entry(FAKE_URL)
        state = SyncState()
        state.sources[key] = SourceState(
            canonical_id=key,
            source_url=FAKE_URL,
            source_type="confluence",
            target_path=target_path,
        )

        # First run with V1
        self._run_with_mocks(state.sources[key], root, FAKE_HTML_V1)

        first_hash = state.sources[key].content_hash
        time.sleep(0.05)

        # Second run with V2
        changed = self._run_with_mocks(state.sources[key], root, FAKE_HTML_V2, version=2)

        assert changed is True

        # File content updated
        knowledge_dir = root / "knowledge" / target_path
        md_files = list(knowledge_dir.glob("*.md"))
        assert len(md_files) == 1
        content = md_files[0].read_text(encoding="utf-8")
        assert "Version two content" in content

        # Hash changed
        assert state.sources[key].content_hash != first_hash


class TestManifestDiscoveryAndScheduling:
    """Test that manifest discovery feeds the scheduler correctly."""

    def test_new_manifest_schedules_sources_immediately(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        _write_manifest(root, "proj-a")
        _write_manifest(root, "proj-b")

        manifests = discover_manifests(root)
        assert len(manifests) == 2

        scheduler = Scheduler()
        for manifest in manifests.values():
            for entry in manifest.sources:
                key = source_key_for_entry(entry.url)
                scheduler.schedule_immediate(key)

        due = scheduler.pop_due()
        # Both manifests reference the same URL, so only 1 canonical key
        assert len(due) == 1

    def test_removed_manifest_source_can_be_pruned(self, tmp_path):
        root = tmp_path / "root"
        _write_manifest(root, "proj")

        manifests = discover_manifests(root)
        state = SyncState()
        for manifest in manifests.values():
            for entry in manifest.sources:
                key = source_key_for_entry(entry.url)
                state.sources[key] = SourceState(
                    canonical_id=key,
                    source_url=entry.url,
                    source_type="confluence",
                )

        # Add a stale entry that no longer exists in any manifest
        state.sources["stale:key"] = SourceState(
            canonical_id="stale:key",
            source_url="gone",
            source_type="confluence",
        )

        from brain_sync.state import prune_state

        active = {source_key_for_entry(e.url) for m in manifests.values() for e in m.sources}
        prune_state(state, active)
        assert "stale:key" not in state.sources


class TestStatePersistenceRoundTrip:
    """Test that state survives save/load cycle after a full pipeline run."""

    def test_state_survives_restart(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        target_path = "project"

        key = source_key_for_entry(FAKE_URL)
        state = SyncState()
        state.sources[key] = SourceState(
            canonical_id=key,
            source_url=FAKE_URL,
            source_type="confluence",
            target_path=target_path,
        )

        mocks = _mock_rest(FAKE_HTML_V1)
        with patch.multiple("brain_sync.pipeline", **mocks):
            asyncio.run(process_source(state.sources[key], httpx.AsyncClient(), root))

        # Save state
        save_state(root, state)

        # Simulate restart — load from disk
        loaded = load_state(root)
        assert key in loaded.sources
        ss = loaded.sources[key]
        assert ss.content_hash == state.sources[key].content_hash
        assert ss.last_changed_utc == state.sources[key].last_changed_utc
        assert ss.source_type == "confluence"

        # Interval should be base (recently changed)
        interval = compute_interval(ss.last_changed_utc)
        assert interval == 1800

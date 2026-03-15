"""Integration test: full sync flow with mocked source adapter.

Exercises:
1. Start with empty root
2. Register a source via SourceState
3. Pipeline fetches content (mocked adapter)
4. Markdown file written to knowledge/<target_path>/
5. State updated with correct fields
6. Second run with unchanged content skips write
7. Second run with changed content triggers state reset
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from brain_sync.converter import html_to_markdown
from brain_sync.pipeline import process_source
from brain_sync.scheduler import compute_interval
from brain_sync.sources import canonical_id, detect_source_type
from brain_sync.sources.base import (
    Comment,
    SourceCapabilities,
    SourceFetchResult,
    UpdateCheckResult,
    UpdateStatus,
)
from brain_sync.state import (
    SourceState,
    SyncState,
    load_state,
    save_state,
)

pytestmark = pytest.mark.integration


def _source_key(url: str) -> str:
    return canonical_id(detect_source_type(url), url)


FAKE_PAGE_ID = "12345"
FAKE_URL = f"https://test.atlassian.net/wiki/spaces/X/pages/{FAKE_PAGE_ID}/TestPage"

FAKE_HTML_V1 = "<h1>Test Page</h1><p>Version one content.</p>"
FAKE_HTML_V2 = "<h1>Test Page</h1><p>Version two content with changes.</p>"

FAKE_AUTH = object()  # opaque auth behind adapter


def _mock_adapter(html, title="TestPage", version=1, comments=None):
    """Create a mock adapter for integration tests."""
    adapter = Mock()
    adapter.capabilities = SourceCapabilities(
        supports_version_check=True,
        supports_comments=True,
        supports_children=True,
        supports_attachments=True,
    )
    adapter.auth_provider = Mock()
    adapter.auth_provider.load_auth.return_value = FAKE_AUTH

    check_result = UpdateCheckResult(
        status=UpdateStatus.CHANGED,
        fingerprint=str(version),
        title=title,
        adapter_state={"version": str(version)},
    )
    adapter.check_for_update = AsyncMock(return_value=check_result)

    comments_list = (
        comments
        if comments is not None
        else [
            Comment(author="Alice", created="2026-01-01T00:00:00Z", content="<p>Great work!</p>"),
            Comment(author="Bob", created="2026-01-02T00:00:00Z", content="<p>Needs review.</p>"),
        ]
    )
    fetch_result = SourceFetchResult(
        body_markdown=html_to_markdown(html),
        comments=comments_list,
        metadata_fingerprint=str(version),
        title=title,
    )
    adapter.fetch = AsyncMock(return_value=fetch_result)
    return adapter


class TestFullSyncFlow:
    """Integration test: source registration -> fetch -> write -> state."""

    @pytest.fixture
    def root(self, tmp_path):
        return tmp_path / "sync-root"

    def _run_with_mocks(self, source_state, root, html, version=1, comments=None):
        adapter = _mock_adapter(html, version=version, comments=comments)
        with patch("brain_sync.pipeline.get_adapter", return_value=adapter):
            changed, _children = asyncio.run(process_source(source_state, httpx.AsyncClient(), root))
            return changed

    def test_first_sync_creates_output(self, root):
        """Register source, run pipeline, verify file + state."""
        root.mkdir()
        target_path = "project"

        key = _source_key(FAKE_URL)
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

        key = _source_key(FAKE_URL)
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

        key = _source_key(FAKE_URL)
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


class TestStatePersistenceRoundTrip:
    """Test that state survives save/load cycle after a full pipeline run."""

    def test_state_survives_restart(self, tmp_path):
        from brain_sync.manifest import MANIFEST_VERSION, SourceManifest, ensure_manifest_dir, write_source_manifest

        root = tmp_path / "root"
        root.mkdir()
        target_path = "project"

        key = _source_key(FAKE_URL)

        # Create manifest (v21+: intent fields come from manifests, not DB)
        ensure_manifest_dir(root)
        write_source_manifest(
            root,
            SourceManifest(
                version=MANIFEST_VERSION,
                canonical_id=key,
                source_url=FAKE_URL,
                source_type="confluence",
                materialized_path="",
                fetch_children=False,
                sync_attachments=False,
                target_path=target_path,
            ),
        )

        state = SyncState()
        state.sources[key] = SourceState(
            canonical_id=key,
            source_url=FAKE_URL,
            source_type="confluence",
            target_path=target_path,
        )

        adapter = _mock_adapter(FAKE_HTML_V1)
        with patch("brain_sync.pipeline.get_adapter", return_value=adapter):
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

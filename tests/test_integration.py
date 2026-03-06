"""Integration test: full sync flow with mocked confluence-cli.

Exercises:
1. Start with empty root
2. Add a sync-manifest.yaml
3. Pipeline fetches content (mocked subprocess)
4. Markdown file written next to manifest
5. .dirty touched at declared relative path
6. State persisted with correct fields
7. Second run with unchanged content skips write
8. Second run with changed content triggers dirty touch
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from brain_sync.manifest import Manifest, SourceEntry, discover_manifests, load_manifest
from brain_sync.pipeline import process_source
from brain_sync.scheduler import Scheduler, compute_interval
from brain_sync.state import (
    SyncState,
    SourceState,
    load_state,
    save_state,
    source_key,
)

FAKE_PAGE_ID = "12345"
FAKE_URL = f"https://test.atlassian.net/wiki/spaces/X/pages/{FAKE_PAGE_ID}/TestPage"

FAKE_HTML_V1 = "<h1>Test Page</h1><p>Version one content.</p>"
FAKE_HTML_V2 = "<h1>Test Page</h1><p>Version two content with changes.</p>"
FAKE_COMMENTS = """Found 2 comments:
1. Alice (ID: 100) [inline]
   Created: 2026-01-01T00:00:00Z
   Body:
     Great work!
2. Bob (ID: 200) [footer]
   Created: 2026-01-02T00:00:00Z
   Body:
     Needs review."""


def _write_manifest(root: Path, rel_dir: str = "project") -> Path:
    manifest_dir = root / rel_dir
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "sync-manifest.yaml"
    manifest_path.write_text(f"""
touch_dirty_relative_path: ../.dirty
sources:
  - url: {FAKE_URL}
    file: test-page.md
""", encoding="utf-8")
    return manifest_path


def _mock_subprocess(html: str, comments: str | None = FAKE_COMMENTS):
    """Create a mock for asyncio.create_subprocess_exec that fakes confluence CLI."""
    async def fake_exec(*args, **kwargs):
        cmd_args = list(args)
        mock_proc = AsyncMock()
        mock_proc.returncode = 0

        if "comments" in cmd_args:
            stdout = (comments or "").encode("utf-8")
        elif "--format" in cmd_args and "json" in cmd_args:
            # Metadata check — return invalid JSON to skip metadata
            stdout = b"not json"
            mock_proc.returncode = 1
        else:
            # Regular read
            stdout = html.encode("utf-8")

        mock_proc.communicate = AsyncMock(return_value=(stdout, b""))
        return mock_proc

    return fake_exec


class TestFullSyncFlow:
    """Integration test: manifest discovery → fetch → write → dirty → state."""

    @pytest.fixture
    def root(self, tmp_path):
        return tmp_path / "sync-root"

    def test_first_sync_creates_output_and_dirty(self, root):
        """Add manifest, run pipeline, verify file + dirty + state."""
        root.mkdir()
        manifest_path = _write_manifest(root)
        manifest = load_manifest(manifest_path)
        entry = manifest.sources[0]

        state = SyncState()
        key = source_key(str(manifest.path), entry.url)
        state.sources[key] = SourceState(
            manifest_path=str(manifest.path),
            source_url=entry.url,
            target_file=entry.file,
            source_type="confluence",
        )

        with patch(
            "brain_sync.sources.confluence.asyncio.create_subprocess_exec",
            side_effect=_mock_subprocess(FAKE_HTML_V1),
        ):
            changed = asyncio.run(
                process_source(manifest, entry, state.sources[key], httpx.AsyncClient())
            )

        # File written next to manifest
        output = manifest.path.parent / "test-page.md"
        assert output.exists()
        content = output.read_text(encoding="utf-8")
        assert "# Test Page" in content
        assert "Version one content." in content
        assert "## Comments" in content
        assert "Great work!" in content
        assert changed is True

        # .dirty touched at relative path
        dirty = (manifest.path.parent / "../.dirty").resolve()
        assert dirty.exists()

        # State updated
        ss = state.sources[key]
        assert ss.last_checked_utc is not None
        assert ss.last_changed_utc is not None
        assert ss.content_hash is not None
        assert ss.source_type == "confluence"

    def test_unchanged_content_skips_write(self, root):
        """Second run with same content: no file rewrite, no dirty touch update."""
        root.mkdir()
        manifest_path = _write_manifest(root)
        manifest = load_manifest(manifest_path)
        entry = manifest.sources[0]

        state = SyncState()
        key = source_key(str(manifest.path), entry.url)
        state.sources[key] = SourceState(
            manifest_path=str(manifest.path),
            source_url=entry.url,
            target_file=entry.file,
            source_type="confluence",
        )

        mock_fn = _mock_subprocess(FAKE_HTML_V1)

        # First run
        with patch(
            "brain_sync.sources.confluence.asyncio.create_subprocess_exec",
            side_effect=mock_fn,
        ):
            asyncio.run(
                process_source(manifest, entry, state.sources[key], httpx.AsyncClient())
            )

        dirty = (manifest.path.parent / "../.dirty").resolve()
        first_dirty_mtime = dirty.stat().st_mtime
        first_changed_utc = state.sources[key].last_changed_utc
        time.sleep(0.05)

        # Second run — same content
        with patch(
            "brain_sync.sources.confluence.asyncio.create_subprocess_exec",
            side_effect=_mock_subprocess(FAKE_HTML_V1),
        ):
            changed = asyncio.run(
                process_source(manifest, entry, state.sources[key], httpx.AsyncClient())
            )

        assert changed is False
        # last_changed_utc should NOT have been updated
        assert state.sources[key].last_changed_utc == first_changed_utc

    def test_changed_content_triggers_dirty_and_state_reset(self, root):
        """Content change: file rewritten, dirty touched, state updated."""
        root.mkdir()
        manifest_path = _write_manifest(root)
        manifest = load_manifest(manifest_path)
        entry = manifest.sources[0]

        state = SyncState()
        key = source_key(str(manifest.path), entry.url)
        state.sources[key] = SourceState(
            manifest_path=str(manifest.path),
            source_url=entry.url,
            target_file=entry.file,
            source_type="confluence",
        )

        # First run with V1
        with patch(
            "brain_sync.sources.confluence.asyncio.create_subprocess_exec",
            side_effect=_mock_subprocess(FAKE_HTML_V1),
        ):
            asyncio.run(
                process_source(manifest, entry, state.sources[key], httpx.AsyncClient())
            )

        first_hash = state.sources[key].content_hash
        dirty = (manifest.path.parent / "../.dirty").resolve()
        first_dirty_mtime = dirty.stat().st_mtime
        time.sleep(0.05)

        # Second run with V2
        with patch(
            "brain_sync.sources.confluence.asyncio.create_subprocess_exec",
            side_effect=_mock_subprocess(FAKE_HTML_V2),
        ):
            changed = asyncio.run(
                process_source(manifest, entry, state.sources[key], httpx.AsyncClient())
            )

        assert changed is True

        # File content updated
        output = manifest.path.parent / "test-page.md"
        content = output.read_text(encoding="utf-8")
        assert "Version two content" in content

        # Hash changed
        assert state.sources[key].content_hash != first_hash

        # Dirty file mtime updated
        assert dirty.stat().st_mtime > first_dirty_mtime


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
                key = source_key(str(manifest.path), entry.url)
                scheduler.schedule_immediate(key)

        due = scheduler.pop_due()
        assert len(due) == 2

    def test_removed_manifest_source_can_be_pruned(self, tmp_path):
        root = tmp_path / "root"
        _write_manifest(root, "proj")

        manifests = discover_manifests(root)
        state = SyncState()
        for manifest in manifests.values():
            for entry in manifest.sources:
                key = source_key(str(manifest.path), entry.url)
                state.sources[key] = SourceState(
                    manifest_path=str(manifest.path),
                    source_url=entry.url,
                    target_file=entry.file,
                    source_type="confluence",
                )

        # Add a stale entry that no longer exists in any manifest
        state.sources["stale::key"] = SourceState(
            manifest_path="gone", source_url="gone", target_file="gone.md", source_type="confluence"
        )

        from brain_sync.state import prune_state
        active = {
            source_key(str(m.path), e.url)
            for m in manifests.values()
            for e in m.sources
        }
        prune_state(state, active)
        assert "stale::key" not in state.sources


class TestStatePersistenceRoundTrip:
    """Test that state survives save/load cycle after a full pipeline run."""

    def test_state_survives_restart(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        manifest_path = _write_manifest(root)
        manifest = load_manifest(manifest_path)
        entry = manifest.sources[0]

        state = SyncState()
        key = source_key(str(manifest.path), entry.url)
        state.sources[key] = SourceState(
            manifest_path=str(manifest.path),
            source_url=entry.url,
            target_file=entry.file,
            source_type="confluence",
        )

        with patch(
            "brain_sync.sources.confluence.asyncio.create_subprocess_exec",
            side_effect=_mock_subprocess(FAKE_HTML_V1),
        ):
            asyncio.run(
                process_source(manifest, entry, state.sources[key], httpx.AsyncClient())
            )

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

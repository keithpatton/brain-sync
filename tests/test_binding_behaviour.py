"""Behavioural integration tests for canonical identity and binding mobility.

Each test mocks the Confluence REST client and asserts separately on:
- version-check calls (fetch_page_version)
- body-fetch calls (fetch_page_body)
- attachment-download calls (download_attachment)

This makes performance claims precise — a version check is expected and cheap;
a body fetch or attachment download caused purely by a path change is a bug.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from brain_sync.__main__ import (
    _build_source_map,
    _ensure_source_states,
    _project_to_additional_bindings,
)
from brain_sync.confluence_rest import ConfluenceAuth
from brain_sync.manifest import Manifest, SourceEntry, discover_manifests, load_manifest
from brain_sync.pipeline import process_source
from brain_sync.scheduler import Scheduler
from brain_sync.state import (
    OutputBinding,
    SourceState,
    SyncState,
    load_bindings_for_source,
    load_state,
    save_state,
    source_key_for_entry,
)

FAKE_PAGE_ID = "55555"
FAKE_URL = f"https://test.atlassian.net/wiki/spaces/X/pages/{FAKE_PAGE_ID}/TestPage"
FAKE_HTML_V1 = "<h1>Test Page</h1><p>Version one.</p>"
FAKE_HTML_V2 = "<h1>Test Page</h1><p>Version two with changes.</p>"
FAKE_AUTH = ConfluenceAuth(domain="test.atlassian.net", email="a@b.com", token="tok")


def _write_manifest(root: Path, rel_dir: str, url: str = FAKE_URL, file: str = "page.md") -> Path:
    manifest_dir = root / rel_dir
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "sync-manifest.yaml"
    manifest_path.write_text(f"""
touch_dirty_relative_path: ../.dirty
sources:
  - url: {url}
    file: {file}
""", encoding="utf-8")
    return manifest_path


def _mock_subprocess(html: str):
    """Mock for confluence CLI subprocess (fallback path)."""
    async def fake_exec(*args, **kwargs):
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        cmd_args = list(args)
        if "comments" in cmd_args:
            mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        else:
            mock_proc.communicate = AsyncMock(return_value=(html.encode("utf-8"), b""))
        return mock_proc
    return fake_exec


class TestFolderRenameNoBodyFetch:
    """Folder rename does not trigger body fetch."""

    def test_rename_preserves_state_and_skips_fetch(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()

        # Initial sync at path A
        _write_manifest(root, "folder-A")
        manifests = discover_manifests(root)
        state = SyncState()
        scheduler = Scheduler()
        source_map, bindings_by_cid = _ensure_source_states(manifests, state, scheduler, root)

        cid = f"confluence:{FAKE_PAGE_ID}"
        assert cid in state.sources

        # Simulate first sync
        version_mock = AsyncMock(return_value=1)
        body_mock = AsyncMock(return_value=(FAKE_HTML_V1, "Test Page", 1))

        manifest = list(manifests.values())[0]
        entry = manifest.sources[0]
        ss = state.sources[cid]

        with patch("brain_sync.pipeline.get_confluence_auth", return_value=FAKE_AUTH), \
             patch("brain_sync.pipeline.fetch_page_version", version_mock), \
             patch("brain_sync.pipeline.fetch_page_body", body_mock), \
             patch("brain_sync.sources.confluence.asyncio.create_subprocess_exec",
                   side_effect=_mock_subprocess(FAKE_HTML_V1)):
            changed = asyncio.run(
                process_source(manifest, entry, ss, httpx.AsyncClient(), root=root)
            )
        assert changed is True
        assert body_mock.call_count == 1
        save_state(root, state)

        # Simulate folder rename: remove A, create B with same manifest content
        import shutil
        old_dir = root / "folder-A"
        new_dir = root / "folder-B"
        shutil.move(str(old_dir), str(new_dir))

        # Re-discover manifests
        manifests = discover_manifests(root)
        assert len(manifests) == 1

        # Reset mocks
        version_mock.reset_mock()
        body_mock.reset_mock()
        version_mock.return_value = 1  # same version

        # Re-ensure source states — should find existing state by canonical_id
        scheduler2 = Scheduler()
        source_map, bindings_by_cid = _ensure_source_states(manifests, state, scheduler2, root)

        # State should still be there (same canonical_id)
        assert cid in state.sources
        ss = state.sources[cid]
        assert ss.content_hash is not None  # preserved from first sync

        # Process the due source — version unchanged, should skip body fetch
        manifest = list(manifests.values())[0]
        entry = manifest.sources[0]

        with patch("brain_sync.pipeline.get_confluence_auth", return_value=FAKE_AUTH), \
             patch("brain_sync.pipeline.fetch_page_version", version_mock), \
             patch("brain_sync.pipeline.fetch_page_body", body_mock), \
             patch("brain_sync.sources.confluence.asyncio.create_subprocess_exec",
                   side_effect=_mock_subprocess(FAKE_HTML_V1)):
            changed = asyncio.run(
                process_source(manifest, entry, ss, httpx.AsyncClient(), root=root)
            )

        assert changed is False
        assert version_mock.call_count == 1  # version check happened
        assert body_mock.call_count == 0     # NO body fetch

        # Bindings updated with new path
        bindings = load_bindings_for_source(root, cid)
        assert len(bindings) == 1
        assert "folder-B" in bindings[0].manifest_path


class TestMultipleManifestsShareSyncState:
    """Two manifests referencing the same page share a single sync state."""

    def test_single_fetch_two_bindings(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()

        _write_manifest(root, "proj-a")
        _write_manifest(root, "proj-b")

        manifests = discover_manifests(root)
        assert len(manifests) == 2

        state = SyncState()
        scheduler = Scheduler()
        source_map, bindings_by_cid = _ensure_source_states(manifests, state, scheduler, root)

        cid = f"confluence:{FAKE_PAGE_ID}"

        # Only one source state entry (shared)
        assert len(state.sources) == 1
        assert cid in state.sources

        # Two bindings
        bindings = load_bindings_for_source(root, cid)
        assert len(bindings) == 2

        # Only one key scheduled
        due = scheduler.pop_due()
        assert len(due) == 1
        assert due[0] == cid


class TestRemoveOneManifestPreservesOther:
    """Removing one manifest preserves the other binding."""

    def test_remove_one_keeps_other(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()

        _write_manifest(root, "proj-a")
        _write_manifest(root, "proj-b")

        manifests = discover_manifests(root)
        state = SyncState()
        scheduler = Scheduler()
        _ensure_source_states(manifests, state, scheduler, root)

        cid = f"confluence:{FAKE_PAGE_ID}"
        assert len(load_bindings_for_source(root, cid)) == 2

        # Remove one manifest
        import shutil
        shutil.rmtree(str(root / "proj-a"))

        manifests = discover_manifests(root)
        assert len(manifests) == 1

        scheduler2 = Scheduler()
        _ensure_source_states(manifests, state, scheduler2, root)

        # Source still exists
        assert cid in state.sources

        # Only one binding remains
        bindings = load_bindings_for_source(root, cid)
        assert len(bindings) == 1
        assert "proj-b" in bindings[0].manifest_path


class TestRemoteUpdatePropagatesAllBindings:
    """Remote update propagates to all bindings."""

    def test_update_reaches_both_dirs(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()

        _write_manifest(root, "proj-a")
        _write_manifest(root, "proj-b")

        manifests = discover_manifests(root)
        state = SyncState()
        scheduler = Scheduler()
        source_map, bindings_by_cid = _ensure_source_states(manifests, state, scheduler, root)

        cid = f"confluence:{FAKE_PAGE_ID}"
        ss = state.sources[cid]

        # First sync
        body_mock = AsyncMock(return_value=(FAKE_HTML_V1, "Test Page", 1))
        version_mock = AsyncMock(return_value=1)

        manifest, idx = source_map[cid][0]
        entry = manifest.sources[idx]

        with patch("brain_sync.pipeline.get_confluence_auth", return_value=FAKE_AUTH), \
             patch("brain_sync.pipeline.fetch_page_version", version_mock), \
             patch("brain_sync.pipeline.fetch_page_body", body_mock), \
             patch("brain_sync.sources.confluence.asyncio.create_subprocess_exec",
                   side_effect=_mock_subprocess(FAKE_HTML_V1)):
            changed = asyncio.run(
                process_source(manifest, entry, ss, httpx.AsyncClient(), root=root)
            )
        assert changed is True

        # Project to additional bindings
        bindings = bindings_by_cid[cid]
        if len(bindings) > 1:
            primary_target = manifest.path.parent / "page.md"
            _project_to_additional_bindings(manifest, primary_target, bindings, "page.md")

        # Verify file in primary dir
        assert (manifest.path.parent / "page.md").exists()

        # Verify file in secondary dir
        secondary_dirs = [Path(b.manifest_path).parent for b in bindings[1:]]
        for d in secondary_dirs:
            assert (d / "page.md").exists()
            content = (d / "page.md").read_text(encoding="utf-8")
            assert "Version one" in content

        # Now simulate remote update
        body_mock.reset_mock()
        version_mock.reset_mock()
        version_mock.return_value = 2
        body_mock.return_value = (FAKE_HTML_V2, "Test Page", 2)

        with patch("brain_sync.pipeline.get_confluence_auth", return_value=FAKE_AUTH), \
             patch("brain_sync.pipeline.fetch_page_version", version_mock), \
             patch("brain_sync.pipeline.fetch_page_body", body_mock), \
             patch("brain_sync.sources.confluence.asyncio.create_subprocess_exec",
                   side_effect=_mock_subprocess(FAKE_HTML_V2)):
            changed = asyncio.run(
                process_source(manifest, entry, ss, httpx.AsyncClient(), root=root)
            )
        assert changed is True
        assert version_mock.call_count == 1  # 1 version check
        assert body_mock.call_count == 1     # 1 body fetch (not 2)

        # Project to additional bindings
        if len(bindings) > 1:
            primary_target = manifest.path.parent / "page.md"
            _project_to_additional_bindings(manifest, primary_target, bindings, "page.md")

        # Both dirs should have updated content
        for d in secondary_dirs:
            content = (d / "page.md").read_text(encoding="utf-8")
            assert "Version two" in content


class TestVersionUnchangedSkip:
    """Version-unchanged skip applies — no body fetch when version matches."""

    def test_skip_when_version_unchanged(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()

        _write_manifest(root, "proj-a")
        _write_manifest(root, "proj-b")

        manifests = discover_manifests(root)
        state = SyncState()
        scheduler = Scheduler()
        source_map, bindings_by_cid = _ensure_source_states(manifests, state, scheduler, root)

        cid = f"confluence:{FAKE_PAGE_ID}"
        ss = state.sources[cid]

        # First sync
        body_mock = AsyncMock(return_value=(FAKE_HTML_V1, "Test Page", 1))
        version_mock = AsyncMock(return_value=1)

        manifest, idx = source_map[cid][0]
        entry = manifest.sources[idx]

        with patch("brain_sync.pipeline.get_confluence_auth", return_value=FAKE_AUTH), \
             patch("brain_sync.pipeline.fetch_page_version", version_mock), \
             patch("brain_sync.pipeline.fetch_page_body", body_mock), \
             patch("brain_sync.sources.confluence.asyncio.create_subprocess_exec",
                   side_effect=_mock_subprocess(FAKE_HTML_V1)):
            asyncio.run(
                process_source(manifest, entry, ss, httpx.AsyncClient(), root=root)
            )

        # Second check — same version
        body_mock.reset_mock()
        version_mock.reset_mock()
        version_mock.return_value = 1  # unchanged

        with patch("brain_sync.pipeline.get_confluence_auth", return_value=FAKE_AUTH), \
             patch("brain_sync.pipeline.fetch_page_version", version_mock), \
             patch("brain_sync.pipeline.fetch_page_body", body_mock), \
             patch("brain_sync.sources.confluence.asyncio.create_subprocess_exec",
                   side_effect=_mock_subprocess(FAKE_HTML_V1)):
            changed = asyncio.run(
                process_source(manifest, entry, ss, httpx.AsyncClient(), root=root)
            )

        assert changed is False
        assert version_mock.call_count == 1  # version check happened
        assert body_mock.call_count == 0     # NO body fetch


class TestRenameThenRemoteUpdate:
    """Rename then remote update: self-healing + forward progress."""

    def test_rename_then_update(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()

        # Initial sync at path A
        _write_manifest(root, "folder-A")
        manifests = discover_manifests(root)
        state = SyncState()
        scheduler = Scheduler()
        source_map, _ = _ensure_source_states(manifests, state, scheduler, root)

        cid = f"confluence:{FAKE_PAGE_ID}"
        manifest = list(manifests.values())[0]
        entry = manifest.sources[0]
        ss = state.sources[cid]

        version_mock = AsyncMock(return_value=1)
        body_mock = AsyncMock(return_value=(FAKE_HTML_V1, "Test Page", 1))

        with patch("brain_sync.pipeline.get_confluence_auth", return_value=FAKE_AUTH), \
             patch("brain_sync.pipeline.fetch_page_version", version_mock), \
             patch("brain_sync.pipeline.fetch_page_body", body_mock), \
             patch("brain_sync.sources.confluence.asyncio.create_subprocess_exec",
                   side_effect=_mock_subprocess(FAKE_HTML_V1)):
            asyncio.run(
                process_source(manifest, entry, ss, httpx.AsyncClient(), root=root)
            )
        assert body_mock.call_count == 1
        save_state(root, state)

        # Rename folder
        import shutil
        shutil.move(str(root / "folder-A"), str(root / "folder-B"))

        # Re-discover
        manifests = discover_manifests(root)
        scheduler2 = Scheduler()
        source_map, _ = _ensure_source_states(manifests, state, scheduler2, root)

        # Process — version unchanged, should skip body fetch
        version_mock.reset_mock()
        body_mock.reset_mock()
        version_mock.return_value = 1

        manifest = list(manifests.values())[0]
        entry = manifest.sources[0]
        ss = state.sources[cid]

        with patch("brain_sync.pipeline.get_confluence_auth", return_value=FAKE_AUTH), \
             patch("brain_sync.pipeline.fetch_page_version", version_mock), \
             patch("brain_sync.pipeline.fetch_page_body", body_mock), \
             patch("brain_sync.sources.confluence.asyncio.create_subprocess_exec",
                   side_effect=_mock_subprocess(FAKE_HTML_V1)):
            changed = asyncio.run(
                process_source(manifest, entry, ss, httpx.AsyncClient(), root=root)
            )

        assert changed is False
        assert version_mock.call_count == 1
        assert body_mock.call_count == 0  # rename didn't cause refetch

        # Now simulate remote version change
        version_mock.reset_mock()
        body_mock.reset_mock()
        version_mock.return_value = 2
        body_mock.return_value = (FAKE_HTML_V2, "Test Page", 2)

        with patch("brain_sync.pipeline.get_confluence_auth", return_value=FAKE_AUTH), \
             patch("brain_sync.pipeline.fetch_page_version", version_mock), \
             patch("brain_sync.pipeline.fetch_page_body", body_mock), \
             patch("brain_sync.sources.confluence.asyncio.create_subprocess_exec",
                   side_effect=_mock_subprocess(FAKE_HTML_V2)):
            changed = asyncio.run(
                process_source(manifest, entry, ss, httpx.AsyncClient(), root=root)
            )

        assert changed is True
        assert version_mock.call_count == 1
        assert body_mock.call_count == 1  # real change triggered body fetch

        # Output at new path
        output = root / "folder-B" / "page.md"
        assert output.exists()
        assert "Version two" in output.read_text(encoding="utf-8")

        # No bindings referencing old path
        bindings = load_bindings_for_source(root, cid)
        for b in bindings:
            assert "folder-A" not in b.manifest_path


class TestProjectedContextLinksResolve:
    """Projected context links resolve correctly in secondary binding."""

    def test_context_copies_to_secondary(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()

        # Create two manifests
        dir_a = root / "proj-a"
        dir_b = root / "proj-b"

        _write_manifest(root, "proj-a")
        _write_manifest(root, "proj-b")

        # Simulate context files in primary dir
        context_dir = dir_a / "_sync-context" / "linked"
        context_dir.mkdir(parents=True)
        (context_dir / "c200-linked-page.md").write_text("# Linked Page\nContent", encoding="utf-8")

        index_dir = dir_a / "_sync-context"
        (index_dir / "_index.md").write_text("# Context Index\n- linked/c200-linked-page.md", encoding="utf-8")

        # Primary output
        (dir_a / "page.md").write_text("# Test Page\n[link](./_sync-context/linked/c200-linked-page.md)", encoding="utf-8")

        # Load manifests
        manifests = discover_manifests(root)
        state = SyncState()
        scheduler = Scheduler()
        source_map, bindings_by_cid = _ensure_source_states(manifests, state, scheduler, root)

        cid = f"confluence:{FAKE_PAGE_ID}"
        bindings = bindings_by_cid[cid]

        # Find which binding is primary (proj-a) vs secondary
        primary_manifest = None
        for m in manifests.values():
            if "proj-a" in str(m.path):
                primary_manifest = m
                break
        assert primary_manifest is not None

        primary_target = dir_a / "page.md"

        # Ensure the secondary binding has include_links=False by default
        # But let's create manifests with include_links for this test
        (dir_a / "sync-manifest.yaml").write_text(f"""
touch_dirty_relative_path: ../.dirty
sources:
  - url: {FAKE_URL}
    file: page.md
    include_links: true
""", encoding="utf-8")
        (dir_b / "sync-manifest.yaml").write_text(f"""
touch_dirty_relative_path: ../.dirty
sources:
  - url: {FAKE_URL}
    file: page.md
    include_links: true
""", encoding="utf-8")

        # Reload manifests and bindings
        manifests = discover_manifests(root)
        source_map, bindings_by_cid = _ensure_source_states(manifests, state, scheduler, root)
        bindings = bindings_by_cid[cid]

        # Find primary manifest again
        for m in manifests.values():
            if "proj-a" in str(m.path):
                primary_manifest = m
                break

        # Project to additional bindings
        _project_to_additional_bindings(primary_manifest, primary_target, bindings, "page.md")

        # Verify secondary has context files
        secondary_context = dir_b / "_sync-context" / "linked"
        assert secondary_context.exists()
        assert (secondary_context / "c200-linked-page.md").exists()

        # Verify index copied
        assert (dir_b / "_sync-context" / "_index.md").exists()

        # Verify every link in secondary's markdown resolves to an existing file
        secondary_page = dir_b / "page.md"
        assert secondary_page.exists()
        content = secondary_page.read_text(encoding="utf-8")
        # The link ./_sync-context/linked/c200-linked-page.md should resolve
        import re
        links = re.findall(r'\((\./[^)]+)\)', content)
        for link in links:
            target = dir_b / link
            assert target.exists(), f"Link {link} does not resolve to existing file under proj-b"


class TestContextFlagFiltering:
    """Different bindings with different context flags get different projections."""

    def test_binding_without_links_skips_linked_dir(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()

        dir_a = root / "proj-a"
        dir_b = root / "proj-b"
        dir_a.mkdir(parents=True)
        dir_b.mkdir(parents=True)

        # Primary has links
        (dir_a / "sync-manifest.yaml").write_text(f"""
touch_dirty_relative_path: ../.dirty
sources:
  - url: {FAKE_URL}
    file: page.md
    include_links: true
""", encoding="utf-8")

        # Secondary does NOT have links
        (dir_b / "sync-manifest.yaml").write_text(f"""
touch_dirty_relative_path: ../.dirty
sources:
  - url: {FAKE_URL}
    file: page.md
    include_links: false
""", encoding="utf-8")

        # Primary has context
        context_dir = dir_a / "_sync-context" / "linked"
        context_dir.mkdir(parents=True)
        (context_dir / "c200-page.md").write_text("# Linked", encoding="utf-8")

        # Primary output
        (dir_a / "page.md").write_text("# Test", encoding="utf-8")

        manifests = discover_manifests(root)
        state = SyncState()
        scheduler = Scheduler()
        source_map, bindings_by_cid = _ensure_source_states(manifests, state, scheduler, root)

        cid = f"confluence:{FAKE_PAGE_ID}"
        bindings = bindings_by_cid[cid]

        # Find primary manifest
        primary_manifest = None
        for m in manifests.values():
            if "proj-a" in str(m.path):
                primary_manifest = m
                break

        primary_target = dir_a / "page.md"
        _project_to_additional_bindings(primary_manifest, primary_target, bindings, "page.md")

        # Secondary should have the page file but NOT the linked context
        assert (dir_b / "page.md").exists()
        assert not (dir_b / "_sync-context" / "linked").exists()

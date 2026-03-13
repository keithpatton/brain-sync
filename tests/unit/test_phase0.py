"""Phase 0 tests: .brain-sync/ init structure, managed-file headers, resurrection guards."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_sync.commands.init import init_brain
from brain_sync.pipeline import (
    MANAGED_HEADER_SOURCE,
    MANAGED_HEADER_WARNING,
    prepend_managed_header,
    strip_managed_header,
)
from brain_sync.sources.base import SourceFetchResult, UpdateCheckResult, UpdateStatus
from brain_sync.state import SourceState

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Init creates .brain-sync/ structure
# ---------------------------------------------------------------------------


class TestInitBrainSync:
    def test_creates_brain_sync_dir(self, tmp_path: Path):
        root = tmp_path / "brain"
        root.mkdir()
        init_brain(root)
        assert (root / ".brain-sync").is_dir()
        assert (root / ".brain-sync" / "sources").is_dir()

    def test_creates_version_json(self, tmp_path: Path):
        root = tmp_path / "brain"
        root.mkdir()
        init_brain(root)
        version_file = root / ".brain-sync" / "version.json"
        assert version_file.exists()
        data = json.loads(version_file.read_text())
        assert data == {"manifest_version": 1}

    def test_idempotent_version_json(self, tmp_path: Path):
        root = tmp_path / "brain"
        root.mkdir()
        init_brain(root)
        init_brain(root)  # second call
        data = json.loads((root / ".brain-sync" / "version.json").read_text())
        assert data == {"manifest_version": 1}

    def test_gitignore_entry_added(self, tmp_path: Path):
        root = tmp_path / "brain"
        root.mkdir()
        init_brain(root)
        gitignore = root / ".gitignore"
        assert gitignore.exists()
        assert ".sync-state.sqlite*" in gitignore.read_text()

    def test_gitignore_entry_not_duplicated(self, tmp_path: Path):
        root = tmp_path / "brain"
        root.mkdir()
        init_brain(root)
        init_brain(root)
        content = (root / ".gitignore").read_text()
        assert content.count(".sync-state.sqlite*") == 1

    def test_gitignore_appends_to_existing(self, tmp_path: Path):
        root = tmp_path / "brain"
        root.mkdir()
        (root / ".gitignore").write_text("*.pyc\n")
        init_brain(root)
        content = (root / ".gitignore").read_text()
        assert "*.pyc" in content
        assert ".sync-state.sqlite*" in content

    def test_dry_run_does_not_create_version_json(self, tmp_path: Path):
        root = tmp_path / "brain"
        root.mkdir()
        init_brain(root, dry_run=True)
        assert not (root / ".brain-sync" / "version.json").exists()


# ---------------------------------------------------------------------------
# Managed-file identity headers
# ---------------------------------------------------------------------------


class TestManagedHeaders:
    def test_prepend_header(self):
        body = "# My Document\n\nSome content."
        result = prepend_managed_header("confluence:12345", body)
        lines = result.split("\n")
        assert lines[0] == "<!-- brain-sync-source: confluence:12345 -->"
        assert lines[1] == "<!-- brain-sync-managed: local edits may be overwritten -->"
        assert "# My Document" in result

    def test_idempotent_prepend(self):
        body = "# My Document\n\nSome content."
        once = prepend_managed_header("confluence:12345", body)
        twice = prepend_managed_header("confluence:12345", once)
        assert once == twice

    def test_strip_removes_headers(self):
        text = (
            "<!-- brain-sync-source: confluence:12345 -->\n"
            "<!-- brain-sync-managed: local edits may be overwritten -->\n"
            "\n"
            "# My Document\n"
        )
        stripped = strip_managed_header(text)
        assert "brain-sync-source" not in stripped
        assert "brain-sync-managed" not in stripped
        assert "# My Document" in stripped

    def test_strip_on_clean_text(self):
        body = "# No headers here\n\nJust content."
        assert strip_managed_header(body) == body

    def test_header_format_source(self):
        expected = "<!-- brain-sync-source: gdoc:abc123 -->"
        assert MANAGED_HEADER_SOURCE.format("gdoc:abc123") == expected

    def test_header_format_warning(self):
        assert "local edits may be overwritten" in MANAGED_HEADER_WARNING


# ---------------------------------------------------------------------------
# Pipeline writes managed header
# ---------------------------------------------------------------------------


_CONFLUENCE_URL = "https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Test"
_CANONICAL_ID = "confluence:12345"
_TITLE = "Test Page"
_FINGERPRINT = "rev-1"


def _make_adapter(check_result, fetch_result):
    adapter = MagicMock()
    adapter.capabilities.supports_version_check = True
    adapter.capabilities.supports_children = False
    adapter.capabilities.supports_attachments = False
    adapter.capabilities.supports_comments = False
    adapter.auth_provider.load_auth.return_value = MagicMock()
    adapter.check_for_update = AsyncMock(return_value=check_result)
    adapter.fetch = AsyncMock(return_value=fetch_result)
    return adapter


class TestPipelineWritesHeader:
    async def test_written_file_contains_header(self, tmp_path: Path):
        """process_source writes managed-file identity header into synced files."""
        from brain_sync.pipeline import process_source

        root = tmp_path / "brain"
        (root / "knowledge" / "area").mkdir(parents=True)
        (root / ".brain-sync" / "sources").mkdir(parents=True)

        ss = SourceState(
            canonical_id=_CANONICAL_ID,
            source_url=_CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
        )
        check = UpdateCheckResult(
            status=UpdateStatus.CHANGED,
            fingerprint=_FINGERPRINT,
            title=_TITLE,
        )
        fetch = SourceFetchResult(
            body_markdown="# Test Page\n\nContent here.",
            title=_TITLE,
            metadata_fingerprint=_FINGERPRINT,
        )
        adapter = _make_adapter(check, fetch)

        with patch("brain_sync.pipeline.get_adapter", return_value=adapter):
            changed, _ = await process_source(ss, AsyncMock(), root=root)

        assert changed is True
        # Find the written file
        area_dir = root / "knowledge" / "area"
        files = list(area_dir.glob("c12345-*.md"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "<!-- brain-sync-source: confluence:12345 -->" in content
        assert "<!-- brain-sync-managed: local edits may be overwritten -->" in content
        assert "# Test Page" in content


# ---------------------------------------------------------------------------
# UNCHANGED + missing file → skip (resurrection guard)
# ---------------------------------------------------------------------------


class TestResurrectionGuard:
    async def test_unchanged_missing_file_skips_fetch(self, tmp_path: Path):
        """When adapter says UNCHANGED and file doesn't exist, no fetch should occur."""
        from brain_sync.pipeline import process_source

        ss = SourceState(
            canonical_id=_CANONICAL_ID,
            source_url=_CONFLUENCE_URL,
            source_type="confluence",
            metadata_fingerprint=_FINGERPRINT,
        )
        check = UpdateCheckResult(
            status=UpdateStatus.UNCHANGED,
            fingerprint=_FINGERPRINT,
            title=_TITLE,
        )
        fetch = SourceFetchResult(
            body_markdown="# Test\n",
            title=_TITLE,
            metadata_fingerprint=_FINGERPRINT,
        )
        adapter = _make_adapter(check, fetch)

        with (
            patch("brain_sync.pipeline.get_adapter", return_value=adapter),
            patch("brain_sync.pipeline.rediscover_local_path", return_value=None),
        ):
            changed, children = await process_source(ss, AsyncMock(), root=tmp_path)

        assert changed is False
        assert children == []
        adapter.fetch.assert_not_called()

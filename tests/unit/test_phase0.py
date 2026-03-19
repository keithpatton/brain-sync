"""Phase 0 tests for the Brain Format 1.0 / runtime v23 baseline."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.source_state import SourceState
from brain_sync.sources.base import SourceFetchResult, UpdateCheckResult, UpdateStatus
from brain_sync.sync.pipeline import extract_source_id, prepend_managed_header, strip_managed_header

pytestmark = pytest.mark.unit


class TestInitBrainFormatV1:
    def test_creates_brain_manifest_and_sources_dir(self, tmp_path: Path) -> None:
        root = tmp_path / "brain"
        root.mkdir()

        init_brain(root)

        assert (root / ".brain-sync").is_dir()
        assert (root / ".brain-sync" / "sources").is_dir()
        assert (root / ".brain-sync" / "brain.json").is_file()
        assert (root / "knowledge").is_dir()
        assert (root / "knowledge" / "_core").is_dir()

    def test_writes_brain_json(self, tmp_path: Path) -> None:
        root = tmp_path / "brain"
        root.mkdir()

        init_brain(root)

        data = json.loads((root / ".brain-sync" / "brain.json").read_text(encoding="utf-8"))
        assert data == {"version": 1}

    def test_does_not_create_legacy_root_artifacts(self, tmp_path: Path) -> None:
        root = tmp_path / "brain"
        root.mkdir()

        init_brain(root)

        assert not (root / "insights").exists()
        assert not (root / "schemas").exists()
        assert not (root / ".gitignore").exists()
        assert not (root / ".sync-state.sqlite").exists()
        assert not (root / "knowledge" / ".brain-sync").exists()

    def test_dry_run_does_not_write_brain_json(self, tmp_path: Path) -> None:
        root = tmp_path / "brain"
        root.mkdir()

        init_brain(root, dry_run=True)

        assert not (root / ".brain-sync" / "brain.json").exists()


class TestManagedFrontmatter:
    def test_writes_yaml_frontmatter(self) -> None:
        result = prepend_managed_header(
            "confluence:12345",
            "# My Document\n\nBody",
            source_type="confluence",
            source_url="https://example.com/page",
        )

        assert result.startswith("---\n")
        assert "brain_sync_source: confluence" in result
        assert "brain_sync_canonical_id: confluence:12345" in result
        assert "brain_sync_source_url: https://example.com/page" in result

    def test_merges_existing_frontmatter(self) -> None:
        text = "---\ntitle: My Doc\ntags:\n- team\n---\n\n# Body\n"

        result = prepend_managed_header(
            "gdoc:abc123",
            text,
            source_type="googledocs",
            source_url="https://docs.google.com/document/d/abc123/edit",
        )

        assert "title: My Doc" in result
        assert "- team" in result
        assert "brain_sync_source: google_doc" in result
        assert "brain_sync_canonical_id: gdoc:abc123" in result

    def test_strip_removes_only_managed_keys(self) -> None:
        text = (
            "---\n"
            "title: Keep Me\n"
            "brain_sync_source: confluence\n"
            "brain_sync_canonical_id: confluence:12345\n"
            "brain_sync_source_url: https://example.com\n"
            "---\n\n"
            "# Body\n"
        )

        stripped = strip_managed_header(text)

        assert "title: Keep Me" in stripped
        assert "brain_sync_source" not in stripped
        assert "brain_sync_canonical_id" not in stripped
        assert "brain_sync_source_url" not in stripped

    def test_extract_source_id_supports_frontmatter_and_legacy_comments(self, tmp_path: Path) -> None:
        frontmatter_file = tmp_path / "frontmatter.md"
        frontmatter_file.write_text(
            "---\nbrain_sync_canonical_id: confluence:12345\n---\n\n# Doc\n",
            encoding="utf-8",
        )
        legacy_file = tmp_path / "legacy.md"
        legacy_file.write_text(
            "<!-- brain-sync-source: gdoc:abc123 -->\n<!-- brain-sync-managed: local edits may be overwritten -->\n",
            encoding="utf-8",
        )

        assert extract_source_id(frontmatter_file) == "confluence:12345"
        assert extract_source_id(legacy_file) == "gdoc:abc123"


_CONFLUENCE_URL = "https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Test"
_CANONICAL_ID = "confluence:12345"
_TITLE = "Test Page"
_FINGERPRINT = "rev-1"


def _make_adapter(check_result: UpdateCheckResult, fetch_result: SourceFetchResult) -> MagicMock:
    adapter = MagicMock()
    adapter.capabilities.supports_version_check = True
    adapter.capabilities.supports_children = False
    adapter.capabilities.supports_attachments = False
    adapter.capabilities.supports_comments = False
    adapter.auth_provider.load_auth.return_value = MagicMock()
    adapter.check_for_update = AsyncMock(return_value=check_result)
    adapter.fetch = AsyncMock(return_value=fetch_result)
    return adapter


class TestPipelineWritesFrontmatter:
    async def test_written_file_contains_spec_identity_frontmatter(self, tmp_path: Path) -> None:
        from brain_sync.sync.pipeline import process_source

        root = tmp_path / "brain"
        (root / "knowledge" / "area").mkdir(parents=True)
        (root / ".brain-sync" / "sources").mkdir(parents=True)

        ss = SourceState(
            canonical_id=_CANONICAL_ID,
            source_url=_CONFLUENCE_URL,
            source_type="confluence",
            knowledge_path="area/c12345.md",
            knowledge_state="awaiting",
        )
        check = UpdateCheckResult(status=UpdateStatus.CHANGED, fingerprint=_FINGERPRINT, title=_TITLE)
        fetch = SourceFetchResult(
            body_markdown="# Test Page\n\nContent here.",
            title=_TITLE,
            remote_fingerprint=_FINGERPRINT,
        )

        with patch("brain_sync.sync.pipeline.get_adapter", return_value=_make_adapter(check, fetch)):
            changed, _ = await process_source(ss, AsyncMock(), root=root)

        assert changed is True
        written = next((root / "knowledge" / "area").glob("c12345-*.md"))
        content = written.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "brain_sync_source: confluence" in content
        assert "brain_sync_canonical_id: confluence:12345" in content
        assert f"brain_sync_source_url: {_CONFLUENCE_URL}" in content

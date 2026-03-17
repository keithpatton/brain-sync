"""Unit tests for pipeline.py skip-guard logic and filename healing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_sync.pipeline import process_source
from brain_sync.sources import canonical_filename, detect_source_type, extract_id
from brain_sync.sources.base import DiscoveredImage, SourceFetchResult, UpdateCheckResult, UpdateStatus
from brain_sync.state import SourceState

pytestmark = pytest.mark.unit

_GDOC_URL = "https://docs.google.com/document/d/abc123/edit"
_CANONICAL_ID = "gdoc:abc123"
_DOC_ID = "abc123"
_TITLE = "My Doc"
_FINGERPRINT = "rev-42"


@pytest.fixture
def source_state() -> SourceState:
    return SourceState(
        canonical_id=_CANONICAL_ID,
        source_url=_GDOC_URL,
        source_type="googledocs",
        metadata_fingerprint=_FINGERPRINT,
    )


@pytest.fixture
def unchanged_check() -> UpdateCheckResult:
    return UpdateCheckResult(
        status=UpdateStatus.UNCHANGED,
        fingerprint=_FINGERPRINT,
        title=_TITLE,
        adapter_state={"revisionId": _FINGERPRINT},
    )


@pytest.fixture
def fetch_result() -> SourceFetchResult:
    return SourceFetchResult(
        body_markdown="# My Doc\n\nContent.",
        title=_TITLE,
        metadata_fingerprint=_FINGERPRINT,
        comments=[],
    )


def _make_adapter(check_result: UpdateCheckResult, fetch_result: SourceFetchResult | None = None) -> MagicMock:
    adapter = MagicMock()
    adapter.capabilities.supports_version_check = True
    adapter.capabilities.supports_children = False
    adapter.capabilities.supports_attachments = False
    adapter.capabilities.supports_comments = False
    adapter.auth_provider.load_auth.return_value = MagicMock()
    adapter.check_for_update = AsyncMock(return_value=check_result)
    adapter.fetch = AsyncMock(return_value=fetch_result)
    return adapter


class TestSkipGuardWithRoot:
    async def test_skip_when_file_found_via_rediscover(
        self, source_state: SourceState, unchanged_check: UpdateCheckResult, tmp_path: Path
    ) -> None:
        """When rediscover_local_path finds the file, skip guard fires and fetch is not called."""
        discovered = tmp_path / "knowledge" / f"g{_DOC_ID}-my-doc.md"
        adapter = _make_adapter(unchanged_check)

        with (
            patch("brain_sync.pipeline.get_adapter", return_value=adapter),
            patch("brain_sync.pipeline.rediscover_local_path", return_value=discovered),
        ):
            changed, children = await process_source(source_state, AsyncMock(), root=tmp_path)

        assert changed is False
        assert children == []
        adapter.fetch.assert_not_called()

    async def test_skip_when_file_not_found_via_rediscover(
        self,
        source_state: SourceState,
        unchanged_check: UpdateCheckResult,
        fetch_result: SourceFetchResult,
        tmp_path: Path,
    ) -> None:
        """When rediscover_local_path returns None and status is UNCHANGED, skip fetch."""
        adapter = _make_adapter(unchanged_check, fetch_result)

        with (
            patch("brain_sync.pipeline.get_adapter", return_value=adapter),
            patch("brain_sync.pipeline.rediscover_local_path", return_value=None),
        ):
            changed, children = await process_source(source_state, AsyncMock(), root=tmp_path)

        assert changed is False
        assert children == []
        adapter.fetch.assert_not_called()

    async def test_skip_guard_does_not_fire_when_status_changed(
        self,
        source_state: SourceState,
        fetch_result: SourceFetchResult,
        tmp_path: Path,
    ) -> None:
        """When check returns CHANGED, fetch is called even if the file exists on disk."""
        changed_check = UpdateCheckResult(
            status=UpdateStatus.CHANGED,
            fingerprint="rev-43",
            title=_TITLE,
            adapter_state={"revisionId": "rev-43"},
        )
        discovered = tmp_path / "knowledge" / f"g{_DOC_ID}-my-doc.md"
        adapter = _make_adapter(changed_check, fetch_result)

        with (
            patch("brain_sync.pipeline.get_adapter", return_value=adapter),
            patch("brain_sync.pipeline.rediscover_local_path", return_value=discovered),
        ):
            changed, _children = await process_source(source_state, AsyncMock(), root=tmp_path)

        assert changed is True
        adapter.fetch.assert_called_once()


class TestSkipGuardWithoutRoot:
    def _target_filename(self) -> str:
        stype = detect_source_type(_GDOC_URL)
        doc_id = extract_id(stype, _GDOC_URL)
        return canonical_filename(stype, doc_id, _TITLE)

    async def test_skip_when_root_none_and_file_exists(
        self,
        source_state: SourceState,
        unchanged_check: UpdateCheckResult,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With root=None, falls back to target.exists(); skip fires when file is present."""
        monkeypatch.chdir(tmp_path)
        fname = self._target_filename()
        (tmp_path / fname).write_text("# My Doc\n")
        adapter = _make_adapter(unchanged_check)

        with patch("brain_sync.pipeline.get_adapter", return_value=adapter):
            changed, children = await process_source(source_state, AsyncMock(), root=None)

        assert changed is False
        assert children == []
        adapter.fetch.assert_not_called()


class TestGoogleAttachmentHandling:
    async def test_google_docs_does_not_use_confluence_attachment_flow(self, tmp_path: Path) -> None:
        root = tmp_path / "brain"
        (root / "knowledge" / "area").mkdir(parents=True)

        source_state = SourceState(
            canonical_id=_CANONICAL_ID,
            source_url=_GDOC_URL,
            source_type="googledocs",
            target_path="area",
            sync_attachments=True,
        )
        adapter = MagicMock()
        adapter.capabilities.supports_version_check = True
        adapter.capabilities.supports_children = False
        adapter.capabilities.supports_attachments = True
        adapter.capabilities.supports_comments = False
        adapter.auth_provider.load_auth.return_value = MagicMock()
        adapter.check_for_update = AsyncMock(
            return_value=UpdateCheckResult(
                status=UpdateStatus.CHANGED,
                fingerprint="rev-43",
                title=_TITLE,
                adapter_state={"revisionId": "rev-43"},
            )
        )
        adapter.fetch = AsyncMock(
            return_value=SourceFetchResult(
                body_markdown="# My Doc\n\nContent.",
                title=_TITLE,
                metadata_fingerprint="rev-43",
                comments=[],
                inline_images=[
                    DiscoveredImage(
                        canonical_id="gdoc-image:abc123:kix.obj1",
                        download_url="https://example.com/image.png",
                        title="image.png",
                        mime_type="image/png",
                    )
                ],
                download_headers={"Authorization": "Bearer token"},
                attachment_parent_id="gdoc:abc123",
            )
        )

        with (
            patch("brain_sync.pipeline.get_adapter", return_value=adapter),
            patch(
                "brain_sync.sources.confluence.attachments.process_attachments",
                new_callable=AsyncMock,
            ) as mock_attachments,
            patch("brain_sync.sync.attachments.process_inline_images", new_callable=AsyncMock) as mock_inline,
        ):
            mock_inline.return_value = {}
            changed, children = await process_source(source_state, AsyncMock(), root=root)

        assert changed is True
        assert children == []
        mock_inline.assert_awaited_once()
        mock_attachments.assert_not_called()

    async def test_skip_when_root_none_and_file_absent(
        self,
        source_state: SourceState,
        unchanged_check: UpdateCheckResult,
        fetch_result: SourceFetchResult,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With root=None and no file on disk and status UNCHANGED, skip fetch."""
        monkeypatch.chdir(tmp_path)
        adapter = _make_adapter(unchanged_check, fetch_result)

        with patch("brain_sync.pipeline.get_adapter", return_value=adapter):
            changed, children = await process_source(source_state, AsyncMock(), root=None)

        assert changed is False
        assert children == []
        adapter.fetch.assert_not_called()


class TestFilenameHealing:
    async def test_title_rename_rewrites_single_managed_file(
        self,
        tmp_path: Path,
    ) -> None:
        root = tmp_path / "brain"
        area = root / "knowledge" / "area"
        area.mkdir(parents=True)
        (root / ".brain-sync" / "sources").mkdir(parents=True)

        source_state = SourceState(
            canonical_id="confluence:12345",
            source_url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Test",
            source_type="confluence",
            target_path="area",
            metadata_fingerprint="rev-1",
        )

        old_path = area / "c12345-old-title.md"
        old_path.write_text(
            "---\n"
            "brain_sync_source: confluence\n"
            "brain_sync_canonical_id: confluence:12345\n"
            "brain_sync_source_url: https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Test\n"
            "---\n\n"
            "# Old Title\n\n"
            "Body.\n",
            encoding="utf-8",
        )

        adapter = MagicMock()
        adapter.capabilities.supports_version_check = True
        adapter.capabilities.supports_children = False
        adapter.capabilities.supports_attachments = False
        adapter.capabilities.supports_comments = False
        adapter.auth_provider.load_auth.return_value = MagicMock()
        adapter.check_for_update = AsyncMock(
            return_value=UpdateCheckResult(
                status=UpdateStatus.CHANGED,
                fingerprint="rev-2",
                title="New Title",
                adapter_state={"revisionId": "rev-2"},
            )
        )
        adapter.fetch = AsyncMock(
            return_value=SourceFetchResult(
                body_markdown="# New Title\n\nBody.",
                title="New Title",
                metadata_fingerprint="rev-2",
                comments=[],
            )
        )

        with patch("brain_sync.pipeline.get_adapter", return_value=adapter):
            changed, children = await process_source(source_state, AsyncMock(), root=root)

        assert changed is True
        assert children == []

        files = sorted(area.glob("c12345-*.md"))
        assert [path.name for path in files] == ["c12345-new-title.md"]

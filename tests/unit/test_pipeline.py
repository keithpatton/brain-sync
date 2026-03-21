"""Unit tests for source sync pipeline lifecycle semantics."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_sync.application.source_state import SourceState
from brain_sync.runtime.repository import SourceLifecycleRuntime
from brain_sync.sources.base import DiscoveredImage, SourceFetchResult, UpdateCheckResult, UpdateStatus
from brain_sync.sync.pipeline import SourceLifecycleLeaseConflictError, process_source

pytestmark = pytest.mark.unit

_GDOC_URL = "https://docs.google.com/document/d/abc123/edit"
_CANONICAL_ID = "gdoc:abc123"
_TITLE = "My Doc"
_FINGERPRINT = "rev-42"


def _source_state(
    *,
    knowledge_path: str = "area/gabc123-my-doc.md",
    knowledge_state: str = "materialized",
    remote_fingerprint: str | None = _FINGERPRINT,
) -> SourceState:
    return SourceState(
        canonical_id=_CANONICAL_ID,
        source_url=_GDOC_URL,
        source_type="googledocs",
        knowledge_path=knowledge_path,
        knowledge_state=knowledge_state,
        remote_fingerprint=remote_fingerprint,
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
        remote_fingerprint=_FINGERPRINT,
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


class TestSkipGuard:
    async def test_skips_unchanged_materialized_source_with_existing_file(
        self, unchanged_check: UpdateCheckResult, tmp_path: Path
    ) -> None:
        source_state = _source_state()
        discovered = tmp_path / "knowledge" / "area" / "gabc123-my-doc.md"
        adapter = _make_adapter(unchanged_check)

        with (
            patch("brain_sync.sync.pipeline.get_adapter", return_value=adapter),
            patch("brain_sync.sync.pipeline.rediscover_local_path", return_value=discovered),
        ):
            changed, children = await process_source(source_state, AsyncMock(), root=tmp_path)

        assert changed is False
        assert children == []
        adapter.fetch.assert_not_called()

    async def test_stale_source_forces_full_fetch_even_when_fingerprint_matches(
        self, unchanged_check: UpdateCheckResult, fetch_result: SourceFetchResult, tmp_path: Path
    ) -> None:
        source_state = _source_state(knowledge_state="stale")
        stale_path = tmp_path / "knowledge" / "area" / "renamed.md"
        stale_path.parent.mkdir(parents=True)
        stale_path.write_text("# stale", encoding="utf-8")
        adapter = _make_adapter(unchanged_check, fetch_result)

        with patch("brain_sync.sync.pipeline.get_adapter", return_value=adapter):
            changed, children = await process_source(source_state, AsyncMock(), root=tmp_path)

        assert changed is True
        assert children == []
        adapter.fetch.assert_awaited_once()
        assert source_state.knowledge_state == "materialized"
        assert source_state.knowledge_path == "area/gabc123-my-doc.md"
        assert source_state.remote_fingerprint == _FINGERPRINT

    async def test_awaiting_source_skips_when_adapter_reports_unchanged_without_local_file(
        self, unchanged_check: UpdateCheckResult, fetch_result: SourceFetchResult, tmp_path: Path
    ) -> None:
        source_state = _source_state(
            knowledge_path="area/gabc123.md",
            knowledge_state="awaiting",
            remote_fingerprint=None,
        )
        adapter = _make_adapter(unchanged_check, fetch_result)

        with patch("brain_sync.sync.pipeline.get_adapter", return_value=adapter):
            changed, children = await process_source(source_state, AsyncMock(), root=tmp_path)

        assert changed is False
        assert children == []
        adapter.fetch.assert_not_awaited()
        assert source_state.knowledge_state == "awaiting"
        assert source_state.materialized_utc is None

    async def test_root_backed_processing_fails_closed_when_lease_changes_before_materialization(
        self, fetch_result: SourceFetchResult, tmp_path: Path
    ) -> None:
        source_state = _source_state()
        adapter = _make_adapter(
            UpdateCheckResult(
                status=UpdateStatus.CHANGED,
                fingerprint="rev-43",
                title=_TITLE,
                adapter_state={"revisionId": "rev-43"},
            ),
            fetch_result,
        )
        refreshed_state = _source_state()

        with (
            patch("brain_sync.sync.pipeline.get_adapter", return_value=adapter),
            patch(
                "brain_sync.runtime.repository.acquire_source_lifecycle_lease",
                return_value=(True, None),
            ),
            patch("brain_sync.runtime.repository.clear_source_lifecycle_lease"),
            patch(
                "brain_sync.sync.source_state.load_active_sync_state",
                return_value=MagicMock(sources={_CANONICAL_ID: refreshed_state}),
            ),
            patch(
                "brain_sync.runtime.repository.SourceLifecycleCommitFence.renew_owned_lease",
                new=lambda self, _owner_id, *, lease_expires_utc: (
                    setattr(
                        self,
                        "runtime_state",
                        SourceLifecycleRuntime(
                            canonical_id=_CANONICAL_ID,
                            lease_owner="move-owner",
                            lease_expires_utc="2099-01-01T00:00:00+00:00",
                        ),
                    )
                    or False
                ),
            ),
        ):
            with pytest.raises(SourceLifecycleLeaseConflictError) as excinfo:
                await process_source(
                    source_state,
                    AsyncMock(),
                    root=tmp_path,
                    lifecycle_owner_id="daemon-owner",
                )

        assert excinfo.value.canonical_id == _CANONICAL_ID
        assert excinfo.value.lease_owner == "move-owner"
        assert not (tmp_path / "knowledge" / "area" / "gabc123-my-doc.md").exists()


class TestGoogleAttachmentHandling:
    async def test_google_docs_does_not_use_confluence_attachment_flow(self, tmp_path: Path) -> None:
        root = tmp_path / "brain"
        (root / "knowledge" / "area").mkdir(parents=True)

        source_state = SourceState(
            canonical_id=_CANONICAL_ID,
            source_url=_GDOC_URL,
            source_type="googledocs",
            knowledge_path="area/gabc123.md",
            knowledge_state="awaiting",
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
                remote_fingerprint="rev-43",
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
            patch("brain_sync.sync.pipeline.get_adapter", return_value=adapter),
            patch(
                "brain_sync.sources.confluence.attachments.process_attachments",
                new_callable=AsyncMock,
            ) as mock_attachments,
            patch("brain_sync.sync.attachments.process_inline_images", new_callable=AsyncMock) as mock_inline,
        ):
            mock_inline.return_value = ({}, [])
            changed, children = await process_source(source_state, AsyncMock(), root=root)

        assert changed is True
        assert children == []
        mock_inline.assert_awaited_once()
        mock_attachments.assert_not_called()


class TestFilenameHealing:
    async def test_title_rename_rewrites_single_managed_file(self, tmp_path: Path) -> None:
        root = tmp_path / "brain"
        area = root / "knowledge" / "area"
        area.mkdir(parents=True)

        source_state = SourceState(
            canonical_id="confluence:12345",
            source_url="https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Test",
            source_type="confluence",
            knowledge_path="area/c12345-old-title.md",
            knowledge_state="materialized",
            remote_fingerprint="rev-1",
            content_hash="sha256:old",
            materialized_utc="2026-03-19T08:00:00+00:00",
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
                remote_fingerprint="rev-2",
                comments=[],
            )
        )

        with patch("brain_sync.sync.pipeline.get_adapter", return_value=adapter):
            changed, children = await process_source(source_state, AsyncMock(), root=root)

        assert changed is True
        assert children == []

        files = sorted(area.glob("c12345-*.md"))
        assert [path.name for path in files] == ["c12345-new-title.md"]
        assert source_state.knowledge_path == "area/c12345-new-title.md"

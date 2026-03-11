"""Tests for source-aware title resolution."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from brain_sync.sources.title_resolution import (
    _is_opaque_gdocs_title,
    resolve_source_title,
    resolve_source_title_sync,
)

pytestmark = pytest.mark.unit

GDOCS_URL = "https://docs.google.com/document/d/1GOzAEmzLOd9ITiprvsZA23IPXVaXOdlpclPzIP5QMMA/edit"
GDOCS_URL_NO_EDIT = "https://docs.google.com/document/d/1GOzAEmzLOd9ITiprvsZA23IPXVaXOdlpclPzIP5QMMA/"
CONFLUENCE_URL = "https://acme.atlassian.net/wiki/spaces/TEAM/pages/12345/My+Design+Doc"


class TestIsOpaqueGdocsTitle:
    def test_edit_slug_is_opaque(self):
        assert _is_opaque_gdocs_title(GDOCS_URL, "Edit") is True

    def test_doc_id_is_opaque(self):
        assert (
            _is_opaque_gdocs_title(
                GDOCS_URL_NO_EDIT,
                "1Gozaemzlod9Itiprvsza23Ipxvaxodlpclpzip5Qmma",
            )
            is True
        )

    def test_doc_id_with_hyphens_munged_by_extract_is_opaque(self):
        """Real case: doc ID contains hyphens, extract_title_from_url replaces with spaces + title-cases."""
        url = "https://docs.google.com/document/d/10Lmqq6OYBw2bn6GCUllYwJ5d-q4gQh1h4S1SZEf63pY/"
        # extract_title_from_url would produce this:
        title = "10Lmqq6Oybw2Bn6Gcullywj5D Q4Gqh1H4S1Szef63Py"
        assert _is_opaque_gdocs_title(url, title) is True

    def test_meaningful_title_is_not_opaque(self):
        assert _is_opaque_gdocs_title(GDOCS_URL, "Product Requirements") is False

    def test_non_google_url_returns_false(self):
        assert _is_opaque_gdocs_title(CONFLUENCE_URL, "Edit") is False

    def test_preview_slug_is_opaque(self):
        assert _is_opaque_gdocs_title(GDOCS_URL, "Preview") is True


class TestResolveSourceTitle:
    async def test_confluence_returns_url_slug_no_network(self):
        """Confluence URLs use the cheap heuristic — no Drive API call."""
        title = await resolve_source_title(CONFLUENCE_URL)
        assert title == "My Design Doc"

    async def test_gdocs_opaque_title_fetches_via_api(self):
        """Google Docs with opaque title calls Drive API and returns fetched title."""
        with patch(
            "brain_sync.sources.title_resolution._resolve_gdocs_title",
            new_callable=AsyncMock,
            return_value="TPS Report",
        ) as mock_resolve:
            title = await resolve_source_title(GDOCS_URL)

        assert title == "TPS Report"
        mock_resolve.assert_called_once_with(GDOCS_URL)

    async def test_gdocs_api_failure_returns_none(self):
        """When Drive API fails for Google Docs, returns None (opaque title discarded)."""
        with patch(
            "brain_sync.sources.title_resolution._resolve_gdocs_title",
            new_callable=AsyncMock,
            return_value=None,
        ):
            title = await resolve_source_title(GDOCS_URL)

        # "Edit" is opaque, API returned None → None
        assert title is None

    async def test_gdocs_no_auth_returns_none(self):
        """When no auth is configured, _resolve_gdocs_title returns None."""
        mock_provider = MagicMock()
        mock_provider.load_auth.return_value = None

        with patch(
            "brain_sync.sources.googledocs.auth.GoogleDocsAuthProvider",
            return_value=mock_provider,
        ):
            from brain_sync.sources.title_resolution import _resolve_gdocs_title

            result = await _resolve_gdocs_title(GDOCS_URL)

        assert result is None

    async def test_unknown_url_returns_slug(self):
        """Non-Confluence, non-Google URL returns URL slug heuristic."""
        title = await resolve_source_title("https://example.com/some-document-title")
        assert title == "Some Document Title"

    async def test_empty_path_returns_none(self):
        """URL with no useful path returns None."""
        title = await resolve_source_title("https://example.com/")
        assert title is None


class TestResolveSourceTitleSync:
    def test_wraps_async_correctly(self):
        """Sync wrapper returns the same result as the async version."""
        # Confluence URL — no network needed
        title = resolve_source_title_sync(CONFLUENCE_URL)
        assert title == "My Design Doc"

    def test_returns_none_on_failure(self):
        """Returns None when resolution fails entirely."""
        with patch(
            "brain_sync.sources.title_resolution.resolve_source_title",
            new_callable=AsyncMock,
            side_effect=Exception("boom"),
        ):
            result = resolve_source_title_sync("https://example.com/test")
        assert result is None

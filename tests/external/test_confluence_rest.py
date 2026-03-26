from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from brain_sync.sources.base import RemoteSourceMissingError
from brain_sync.sources.confluence.rest import (
    ConfluenceAuth,
    PageVersionInfo,
    download_attachment,
    fetch_attachments,
    fetch_child_pages,
    fetch_comments,
    fetch_page_body,
    fetch_page_version,
    fetch_users_by_account_ids,
    get_confluence_auth,
    reset_auth_cache,
)

pytestmark = pytest.mark.external

AUTH = ConfluenceAuth(domain="test.atlassian.net", email="a@b.com", token="tok")


def _mock_response(data: dict, status_code: int = 200, headers: dict | None = None) -> httpx.Response:
    resp = httpx.Response(
        status_code=status_code,
        json=data,
        headers=headers or {},
        request=httpx.Request("GET", "https://test.atlassian.net/wiki/api/v2/test"),
    )
    return resp


def _mock_client(*responses: httpx.Response) -> httpx.AsyncClient:
    """Create a mock async client that returns responses in order."""
    client = AsyncMock(spec=httpx.AsyncClient)
    client.request = AsyncMock(side_effect=list(responses))
    client.get = AsyncMock(side_effect=list(responses))
    return client


class TestFetchPageVersion:
    @pytest.mark.asyncio
    async def test_returns_version(self):
        resp = _mock_response({"version": {"number": 42, "createdAt": "2026-03-01T00:00:00Z"}})
        client = _mock_client(resp)
        result = await fetch_page_version("123", AUTH, client)
        assert result == PageVersionInfo(version=42, last_changed_utc="2026-03-01T00:00:00Z")

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        resp = _mock_response({}, status_code=500)
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("boom", request=resp.request, response=resp),
        )
        client = _mock_client(resp)
        result = await fetch_page_version("123", AUTH, client)
        assert result is None

    @pytest.mark.asyncio
    async def test_raises_missing_on_404(self):
        resp = _mock_response({}, status_code=404)
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("not found", request=resp.request, response=resp),
        )
        client = _mock_client(resp)
        with pytest.raises(RemoteSourceMissingError):
            await fetch_page_version("123", AUTH, client)


class TestFetchPageBody:
    @pytest.mark.asyncio
    async def test_returns_html_title_version_and_last_changed(self):
        resp = _mock_response(
            {
                "body": {"storage": {"value": "<p>Hello</p>"}},
                "title": "My Page",
                "version": {"number": 5, "createdAt": "2026-03-02T00:00:00Z"},
            }
        )
        client = _mock_client(resp)
        html, title, version, last_changed_utc = await fetch_page_body("123", AUTH, client)
        assert html == "<p>Hello</p>"
        assert title == "My Page"
        assert version == 5
        assert last_changed_utc == "2026-03-02T00:00:00Z"

    @pytest.mark.asyncio
    async def test_raises_missing_on_404(self):
        resp = _mock_response({}, status_code=404)
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("not found", request=resp.request, response=resp),
        )
        client = _mock_client(resp)
        with pytest.raises(RemoteSourceMissingError):
            await fetch_page_body("123", AUTH, client)


class TestFetchChildPages:
    @pytest.mark.asyncio
    async def test_returns_children(self):
        resp = _mock_response(
            {
                "results": [
                    {"id": "10", "title": "Child 1"},
                    {"id": "20", "title": "Child 2"},
                ],
                "_links": {"base": "https://test.atlassian.net/wiki"},
            }
        )
        client = _mock_client(resp)
        children = await fetch_child_pages("123", AUTH, client)
        assert len(children) == 2
        assert children[0]["id"] == "10"
        assert children[1]["title"] == "Child 2"

    @pytest.mark.asyncio
    async def test_pagination(self):
        page1 = _mock_response(
            {
                "results": [{"id": str(i), "title": f"C{i}"} for i in range(25)],
                "_links": {"next": "/pages/123/children?cursor=abc", "base": "https://test.atlassian.net/wiki"},
            }
        )
        page2 = _mock_response(
            {
                "results": [{"id": "99", "title": "Last"}],
                "_links": {"base": "https://test.atlassian.net/wiki"},
            }
        )
        client = _mock_client(page1, page2)
        children = await fetch_child_pages("123", AUTH, client)
        assert len(children) == 26


class TestFetchAttachments:
    @pytest.mark.asyncio
    async def test_returns_attachments(self):
        resp = _mock_response(
            {
                "results": [
                    {
                        "id": "att1",
                        "title": "diagram.png",
                        "version": {"number": 2},
                        "downloadLink": "/download/attachments/123/diagram.png",
                        "mediaType": "image/png",
                    }
                ]
            }
        )
        client = _mock_client(resp)
        atts = await fetch_attachments("123", AUTH, client)
        assert len(atts) == 1
        assert atts[0]["id"] == "att1"
        assert "diagram.png" in atts[0]["download_url"]
        assert atts[0]["media_type"] == "image/png"


class TestFetchUsers:
    @pytest.mark.asyncio
    async def test_resolves_display_names(self):
        resp = _mock_response(
            {
                "results": [
                    {"accountId": "acc-1", "displayName": "Alice"},
                    {"accountId": "acc-2", "publicName": "Bob Public"},
                ]
            }
        )
        client = _mock_client(resp)
        users = await fetch_users_by_account_ids(["acc-2", "acc-1", "acc-1"], AUTH, client)
        assert users == {"acc-1": "Alice", "acc-2": "Bob Public"}


class TestFetchComments:
    @pytest.mark.asyncio
    async def test_returns_rendered_threaded_comments(self):
        inline = _mock_response(
            {
                "results": [
                    {
                        "id": "i1",
                        "status": "current",
                        "pageId": "123",
                        "version": {"createdAt": "2026-01-01T00:00:00Z", "authorId": "acc-1"},
                        "body": {"storage": {"value": "<p>Inline note</p>"}},
                        "resolutionStatus": "resolved",
                        "properties": {
                            "inlineMarkerRef": "marker-1",
                            "inlineOriginalSelection": "Selected text",
                        },
                        "_links": {"webui": "/pages/123?focusedCommentId=i1"},
                    }
                ]
            }
        )
        footer = _mock_response({"results": []})
        inline_children = _mock_response(
            {
                "results": [
                    {
                        "id": "i2",
                        "status": "current",
                        "parentCommentId": "i1",
                        "version": {"createdAt": "2026-01-01T00:01:00Z", "authorId": "acc-2"},
                        "body": {"storage": {"value": "<p>Reply</p>"}},
                        "resolutionStatus": "open",
                        "properties": {},
                        "_links": {"webui": "/pages/123?focusedCommentId=i2"},
                    }
                ]
            }
        )
        users = _mock_response(
            {
                "results": [
                    {"accountId": "acc-1", "displayName": "Alice"},
                    {"accountId": "acc-2", "displayName": "Bob"},
                ]
            }
        )
        client = _mock_client(inline, footer, inline_children, users)
        rendered = await fetch_comments("123", AUTH, client)
        assert rendered is not None
        assert "### Comment Thread `i1` [inline] [resolved]" in rendered
        assert 'Anchor Text: "Selected text"' in rendered
        assert "Replies:" in rendered
        assert "1. Reply `i2`" in rendered
        assert "Author: Bob" in rendered
        assert "[open]" not in rendered

    @pytest.mark.asyncio
    async def test_orders_threads_newest_first_and_replies_oldest_first(self):
        inline = _mock_response(
            {
                "results": [
                    {
                        "id": "older-thread",
                        "status": "current",
                        "pageId": "123",
                        "version": {"createdAt": "2026-01-01T00:00:00Z", "authorId": "acc-1"},
                        "body": {"storage": {"value": "<p>Older thread</p>"}},
                        "resolutionStatus": "open",
                        "properties": {},
                        "_links": {"webui": "/pages/123?focusedCommentId=older-thread"},
                    }
                ]
            }
        )
        footer = _mock_response(
            {
                "results": [
                    {
                        "id": "newer-thread",
                        "status": "current",
                        "pageId": "123",
                        "version": {"createdAt": "2026-01-02T00:00:00Z", "authorId": "acc-2"},
                        "body": {"storage": {"value": "<p>Newer thread</p>"}},
                        "resolutionStatus": "resolved",
                        "_links": {"webui": "/pages/123?focusedCommentId=newer-thread"},
                    }
                ]
            }
        )
        inline_children = _mock_response(
            {
                "results": [
                    {
                        "id": "reply-older",
                        "status": "current",
                        "parentCommentId": "older-thread",
                        "version": {"createdAt": "2026-01-01T00:01:00Z", "authorId": "acc-2"},
                        "body": {"storage": {"value": "<p>First reply</p>"}},
                        "_links": {"webui": "/pages/123?focusedCommentId=reply-older"},
                    },
                    {
                        "id": "reply-newer",
                        "status": "current",
                        "parentCommentId": "older-thread",
                        "version": {"createdAt": "2026-01-01T00:02:00Z", "authorId": "acc-1"},
                        "body": {"storage": {"value": "<p>Second reply</p>"}},
                        "_links": {"webui": "/pages/123?focusedCommentId=reply-newer"},
                    },
                ]
            }
        )
        footer_children = _mock_response({"results": []})
        users = _mock_response(
            {
                "results": [
                    {"accountId": "acc-1", "displayName": "Alice"},
                    {"accountId": "acc-2", "displayName": "Bob"},
                ]
            }
        )
        client = _mock_client(inline, footer, inline_children, footer_children, users)
        rendered = await fetch_comments("123", AUTH, client)
        assert rendered is not None
        assert rendered.index("### Comment Thread `newer-thread`") < rendered.index("### Comment Thread `older-thread`")
        assert rendered.index("1. Reply `reply-older`") < rendered.index("2. Reply `reply-newer`")


class TestDownloadAttachment:
    @pytest.mark.asyncio
    async def test_returns_bytes(self):
        resp = httpx.Response(
            200,
            content=b"binary-data",
            request=httpx.Request("GET", "https://test.atlassian.net/dl"),
        )
        client = _mock_client(resp)
        data = await download_attachment("https://test.atlassian.net/dl", AUTH, client)
        assert data == b"binary-data"


class TestRetryOn429:
    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        rate_limited = httpx.Response(
            429,
            json={},
            headers={"Retry-After": "0"},
            request=httpx.Request("GET", "https://test.atlassian.net/wiki/api/v2/pages/1"),
        )
        success = _mock_response({"version": {"number": 7, "createdAt": "2026-03-03T00:00:00Z"}})
        client = _mock_client(rate_limited, success)
        result = await fetch_page_version("1", AUTH, client)
        assert result == PageVersionInfo(version=7, last_changed_utc="2026-03-03T00:00:00Z")
        assert client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self):
        rate_limited = httpx.Response(
            429,
            json={},
            headers={"Retry-After": "0"},
            request=httpx.Request("GET", "https://test.atlassian.net/wiki/api/v2/pages/1"),
        )
        client = _mock_client(rate_limited, rate_limited, rate_limited, rate_limited)
        # After MAX_RETRIES (3) + 1 attempts, should return None (caught by fetch_page_version)
        result = await fetch_page_version("1", AUTH, client)
        assert result is None


class TestGetConfluenceAuth:
    def setup_method(self):
        reset_auth_cache()

    def teardown_method(self):
        reset_auth_cache()

    def test_reads_config_file(self, tmp_path):
        config = tmp_path / "config.json"
        config.write_text(
            json.dumps(
                {
                    "confluence": {
                        "domain": "test.atlassian.net",
                        "email": "a@b.com",
                        "token": "secret",
                    },
                }
            )
        )
        with patch("brain_sync.runtime.config.CONFIG_FILE", config):
            auth = get_confluence_auth()
        assert auth is not None
        assert auth.domain == "test.atlassian.net"
        assert auth.email == "a@b.com"

    def test_falls_back_to_env(self, tmp_path, monkeypatch):
        nonexistent = tmp_path / "nonexistent.json"
        monkeypatch.setenv("CONFLUENCE_DOMAIN", "env.atlassian.net")
        monkeypatch.setenv("CONFLUENCE_EMAIL", "env@b.com")
        monkeypatch.setenv("CONFLUENCE_TOKEN", "envtok")
        with patch("brain_sync.runtime.config.CONFIG_FILE", nonexistent):
            auth = get_confluence_auth()
        assert auth is not None
        assert auth.domain == "env.atlassian.net"

    def test_returns_none_when_no_auth(self, tmp_path, monkeypatch):
        nonexistent = tmp_path / "nonexistent.json"
        monkeypatch.delenv("CONFLUENCE_DOMAIN", raising=False)
        monkeypatch.delenv("CONFLUENCE_EMAIL", raising=False)
        monkeypatch.delenv("CONFLUENCE_TOKEN", raising=False)
        with patch("brain_sync.runtime.config.CONFIG_FILE", nonexistent):
            auth = get_confluence_auth()
        assert auth is None

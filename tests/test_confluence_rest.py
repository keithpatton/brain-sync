from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from brain_sync.confluence_rest import (
    ConfluenceAuth,
    download_attachment,
    fetch_attachments,
    fetch_child_pages,
    fetch_page_body,
    fetch_page_version,
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
        request=httpx.Request("GET", "https://test.atlassian.net/wiki/rest/api/test"),
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
        resp = _mock_response({"version": {"number": 42}})
        client = _mock_client(resp)
        result = await fetch_page_version("123", AUTH, client)
        assert result == 42

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        resp = _mock_response({}, status_code=404)
        resp.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError("not found", request=resp.request, response=resp),
        )
        client = _mock_client(resp)
        result = await fetch_page_version("123", AUTH, client)
        assert result is None


class TestFetchPageBody:
    @pytest.mark.asyncio
    async def test_returns_html_title_version(self):
        resp = _mock_response(
            {
                "body": {"storage": {"value": "<p>Hello</p>"}},
                "title": "My Page",
                "version": {"number": 5},
            }
        )
        client = _mock_client(resp)
        html, title, version = await fetch_page_body("123", AUTH, client)
        assert html == "<p>Hello</p>"
        assert title == "My Page"
        assert version == 5


class TestFetchChildPages:
    @pytest.mark.asyncio
    async def test_returns_children(self):
        resp = _mock_response(
            {
                "results": [
                    {"id": "10", "title": "Child 1", "version": {"number": 1}},
                    {"id": "20", "title": "Child 2", "version": {"number": 3}},
                ],
                "size": 2,
            }
        )
        client = _mock_client(resp)
        children = await fetch_child_pages("123", AUTH, client)
        assert len(children) == 2
        assert children[0]["id"] == "10"
        assert children[1]["version"] == 3

    @pytest.mark.asyncio
    async def test_pagination(self):
        page1 = _mock_response(
            {
                "results": [{"id": str(i), "title": f"C{i}", "version": {"number": 1}} for i in range(25)],
                "size": 25,
            }
        )
        page2 = _mock_response(
            {
                "results": [{"id": "99", "title": "Last", "version": {"number": 1}}],
                "size": 1,
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
                        "_links": {"download": "/download/attachments/123/diagram.png"},
                        "metadata": {"mediaType": "image/png"},
                    }
                ],
                "size": 1,
            }
        )
        client = _mock_client(resp)
        atts = await fetch_attachments("123", AUTH, client)
        assert len(atts) == 1
        assert atts[0]["id"] == "att1"
        assert "diagram.png" in atts[0]["download_url"]
        assert atts[0]["media_type"] == "image/png"


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
            request=httpx.Request("GET", "https://test.atlassian.net/wiki/rest/api/content/1"),
        )
        success = _mock_response({"version": {"number": 7}})
        client = _mock_client(rate_limited, success)
        result = await fetch_page_version("1", AUTH, client)
        assert result == 7
        assert client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_gives_up_after_max_retries(self):
        rate_limited = httpx.Response(
            429,
            json={},
            headers={"Retry-After": "0"},
            request=httpx.Request("GET", "https://test.atlassian.net/wiki/rest/api/content/1"),
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
        with patch("brain_sync.confluence_rest.CONFIG_FILE", config):
            auth = get_confluence_auth()
        assert auth is not None
        assert auth.domain == "test.atlassian.net"
        assert auth.email == "a@b.com"

    def test_falls_back_to_env(self, tmp_path, monkeypatch):
        nonexistent = tmp_path / "nonexistent.json"
        monkeypatch.setenv("CONFLUENCE_DOMAIN", "env.atlassian.net")
        monkeypatch.setenv("CONFLUENCE_EMAIL", "env@b.com")
        monkeypatch.setenv("CONFLUENCE_TOKEN", "envtok")
        with patch("brain_sync.confluence_rest.CONFIG_FILE", nonexistent):
            auth = get_confluence_auth()
        assert auth is not None
        assert auth.domain == "env.atlassian.net"

    def test_returns_none_when_no_auth(self, tmp_path, monkeypatch):
        nonexistent = tmp_path / "nonexistent.json"
        monkeypatch.delenv("CONFLUENCE_DOMAIN", raising=False)
        monkeypatch.delenv("CONFLUENCE_EMAIL", raising=False)
        monkeypatch.delenv("CONFLUENCE_TOKEN", raising=False)
        with patch("brain_sync.confluence_rest.CONFIG_FILE", nonexistent):
            auth = get_confluence_auth()
        assert auth is None

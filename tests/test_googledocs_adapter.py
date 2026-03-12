"""Unit tests for Google Docs source adapter and OAuth2 authentication."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

pytest.importorskip("google.auth", reason="google-auth not installed (install brain-sync[google])")

from brain_sync.sources.base import (
    AuthProvider,
    SourceAdapter,
    SourceFetchResult,
    UpdateStatus,
)
from brain_sync.sources.googledocs import GoogleDocsAdapter
from brain_sync.sources.googledocs.auth import (
    GoogleDocsAuthProvider,
    GoogleOAuthCredentials,
    _load_cached_token,
    _save_token,
    run_oauth_flow,
)
from brain_sync.sources.googledocs.rest import (
    FetchError,
    compute_semantic_fingerprint,
    extract_canonical_text,
    extract_title_from_html,
    fetch_doc_body,
)

pytestmark = pytest.mark.unit


class TestProtocolCompliance:
    def test_adapter_satisfies_protocol(self):
        assert isinstance(GoogleDocsAdapter(), SourceAdapter)

    def test_auth_satisfies_protocol(self):
        adapter = GoogleDocsAdapter()
        assert isinstance(adapter.auth_provider, AuthProvider)


class TestCapabilities:
    def test_all_capabilities_correct(self):
        caps = GoogleDocsAdapter().capabilities
        assert caps.supports_version_check is True
        assert caps.supports_children is False
        assert caps.supports_links is False
        assert caps.supports_attachments is False
        assert caps.supports_comments is False
        assert caps.supports_context_sync is False


class TestCheckForUpdate:
    @pytest.fixture
    def adapter(self):
        return GoogleDocsAdapter()

    @pytest.fixture
    def source_state(self):
        from brain_sync.state import SourceState

        return SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )

    async def test_returns_unchanged_when_semantic_hash_matches(self, adapter, source_state):
        text = "Hello world"
        fingerprint = compute_semantic_fingerprint(text)
        source_state.metadata_fingerprint = fingerprint
        with patch(
            "brain_sync.sources.googledocs.fetch_doc_body", new_callable=AsyncMock, return_value=("My Doc", text)
        ):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.status == UpdateStatus.UNCHANGED
        assert result.fingerprint == fingerprint
        assert result.title == "My Doc"

    async def test_returns_changed_when_semantic_hash_differs(self, adapter, source_state):
        source_state.metadata_fingerprint = compute_semantic_fingerprint("old content")
        with patch(
            "brain_sync.sources.googledocs.fetch_doc_body",
            new_callable=AsyncMock,
            return_value=("My Doc", "new content"),
        ):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.status == UpdateStatus.CHANGED
        assert result.fingerprint == compute_semantic_fingerprint("new content")

    async def test_returns_changed_when_no_prior_fingerprint(self, adapter, source_state):
        source_state.metadata_fingerprint = None
        with patch(
            "brain_sync.sources.googledocs.fetch_doc_body",
            new_callable=AsyncMock,
            return_value=("My Doc", "some content"),
        ):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.status == UpdateStatus.CHANGED

    async def test_returns_unknown_when_body_unavailable(self, adapter, source_state):
        with patch("brain_sync.sources.googledocs.fetch_doc_body", new_callable=AsyncMock, return_value=(None, None)):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.status == UpdateStatus.UNKNOWN

    async def test_adapter_state_contains_semantic_fingerprint(self, adapter, source_state):
        source_state.metadata_fingerprint = None
        with patch(
            "brain_sync.sources.googledocs.fetch_doc_body",
            new_callable=AsyncMock,
            return_value=("My Doc", "content"),
        ):
            result = await adapter.check_for_update(source_state, Mock(), AsyncMock())
        assert result.adapter_state is not None
        assert "semanticFingerprint" in result.adapter_state
        assert result.adapter_state["semanticFingerprint"].startswith("gdocs:v1:")


class TestFetch:
    @pytest.fixture
    def adapter(self):
        return GoogleDocsAdapter()

    async def test_fetch_returns_correct_result(self, adapter):
        from brain_sync.state import SourceState

        ss = SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )
        fake_html = "<html><head><title>My Doc</title></head><body><h1>Hello</h1><p>World</p></body></html>"
        with patch("brain_sync.sources.googledocs.fetch_doc_html", new_callable=AsyncMock, return_value=fake_html):
            result = await adapter.fetch(ss, Mock(), AsyncMock())

        assert isinstance(result, SourceFetchResult)
        assert "Hello" in result.body_markdown
        assert "World" in result.body_markdown
        assert result.title == "My Doc"
        assert result.comments == []
        assert result.metadata_fingerprint is None  # no prior_adapter_state
        assert result.source_html is None

    async def test_fetch_returns_semantic_fingerprint(self, adapter):
        from brain_sync.state import SourceState

        ss = SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )
        fake_html = "<html><head><title>My Doc</title></head><body><p>Content</p></body></html>"
        with patch("brain_sync.sources.googledocs.fetch_doc_html", new_callable=AsyncMock, return_value=fake_html):
            result = await adapter.fetch(
                ss, Mock(), AsyncMock(), prior_adapter_state={"semanticFingerprint": "gdocs:v1:abc123"}
            )

        assert result.metadata_fingerprint == "gdocs:v1:abc123"

    async def test_fetch_uses_title_from_adapter_state(self, adapter):
        from brain_sync.state import SourceState

        ss = SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )
        # HTML with no <title> tag — title should come from prior_adapter_state
        fake_html = "<html><head></head><body><p>Content</p></body></html>"
        with patch("brain_sync.sources.googledocs.fetch_doc_html", new_callable=AsyncMock, return_value=fake_html):
            result = await adapter.fetch(
                ss,
                Mock(),
                AsyncMock(),
                prior_adapter_state={"semanticFingerprint": "gdocs:v1:abc123", "title": "Adapter Title"},
            )

        assert result.title == "Adapter Title"

    async def test_fetch_falls_back_to_api_title_when_no_adapter_state(self, adapter):
        from brain_sync.state import SourceState

        ss = SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )
        # HTML with no <title> tag
        fake_html = "<html><head></head><body><p>Content</p></body></html>"
        with (
            patch("brain_sync.sources.googledocs.fetch_doc_html", new_callable=AsyncMock, return_value=fake_html),
            patch("brain_sync.sources.googledocs.fetch_doc_title", new_callable=AsyncMock, return_value="API Title"),
        ):
            result = await adapter.fetch(ss, Mock(), AsyncMock())

        assert result.title == "API Title"

    async def test_fetch_title_none_when_both_sources_fail(self, adapter):
        from brain_sync.state import SourceState

        ss = SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )
        fake_html = "<html><head></head><body><p>Content</p></body></html>"
        with (
            patch("brain_sync.sources.googledocs.fetch_doc_html", new_callable=AsyncMock, return_value=fake_html),
            patch("brain_sync.sources.googledocs.fetch_doc_title", new_callable=AsyncMock, return_value=None),
        ):
            result = await adapter.fetch(ss, Mock(), AsyncMock())

        assert result.title is None

    async def test_fetch_propagates_error(self, adapter):
        from brain_sync.state import SourceState

        ss = SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )
        mock_fetch = patch(
            "brain_sync.sources.googledocs.fetch_doc_html",
            new_callable=AsyncMock,
            side_effect=FetchError("fail"),
        )
        with mock_fetch, pytest.raises(FetchError):
            await adapter.fetch(ss, Mock(), AsyncMock())


class TestExtractCanonicalText:
    def _make_doc(self, content: list[dict]) -> dict:
        return {"body": {"content": content}}

    def _para(self, text: str, style: str | None = None, bullet: bool = False) -> dict:
        para: dict = {
            "paragraph": {
                "elements": [{"textRun": {"content": text}}],
            }
        }
        if style:
            para["paragraph"]["paragraphStyle"] = {"namedStyleType": style}
        if bullet:
            para["paragraph"]["bullet"] = {}
        return para

    def test_empty_body(self):
        assert extract_canonical_text({}) == ""

    def test_plain_paragraph(self):
        doc = self._make_doc([self._para("Hello world")])
        assert extract_canonical_text(doc) == "Hello world"

    def test_heading_prefixed(self):
        doc = self._make_doc([self._para("My Heading", style="HEADING_1")])
        assert extract_canonical_text(doc) == "H:My Heading"

    def test_list_item_prefixed(self):
        doc = self._make_doc([self._para("List item", bullet=True)])
        assert extract_canonical_text(doc) == "LI:List item"

    def test_empty_paragraphs_skipped(self):
        doc = self._make_doc([self._para("   "), self._para("Real content")])
        assert extract_canonical_text(doc) == "Real content"

    def test_table_row_prefixed(self):
        doc = self._make_doc([
            {
                "table": {
                    "tableRows": [
                        {
                            "tableCells": [
                                {"content": [self._para("Cell A")]},
                                {"content": [self._para("Cell B")]},
                            ]
                        }
                    ]
                }
            }
        ])
        assert extract_canonical_text(doc) == "T:Cell A|Cell B"

    def test_whitespace_normalised(self):
        doc = self._make_doc([self._para("Hello\n"), self._para("World\n")])
        result = extract_canonical_text(doc)
        assert "\n" not in result
        assert "Hello" in result
        assert "World" in result

    def test_multiple_elements_in_paragraph(self):
        para = {
            "paragraph": {
                "elements": [
                    {"textRun": {"content": "Hello "}},
                    {"textRun": {"content": "world"}},
                ]
            }
        }
        doc = self._make_doc([para])
        assert extract_canonical_text(doc) == "Hello world"


class TestComputeSemanticFingerprint:
    def test_starts_with_version_prefix(self):
        fp = compute_semantic_fingerprint("hello")
        assert fp.startswith("gdocs:v1:")

    def test_same_text_same_fingerprint(self):
        assert compute_semantic_fingerprint("abc") == compute_semantic_fingerprint("abc")

    def test_different_text_different_fingerprint(self):
        assert compute_semantic_fingerprint("abc") != compute_semantic_fingerprint("xyz")

    def test_fingerprint_is_deterministic(self):
        import hashlib
        text = "test content"
        expected = "gdocs:v1:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        assert compute_semantic_fingerprint(text) == expected


class TestFetchDocBody:
    async def test_success_returns_title_and_text(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"

        doc = {
            "title": "My Doc",
            "body": {
                "content": [
                    {
                        "paragraph": {
                            "elements": [{"textRun": {"content": "Hello world"}}]
                        }
                    }
                ]
            },
        }
        mock_response = MagicMock()
        mock_response.json.return_value = doc
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        title, text = await fetch_doc_body("abc123", auth, client)
        assert title == "My Doc"
        assert text is not None
        assert "Hello world" in text
        call_kwargs = client.get.call_args
        assert "docs.googleapis.com/v1/documents/abc123" in call_kwargs.args[0]

    async def test_404_returns_none_none(self):
        import httpx

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response
        )

        client = AsyncMock()
        client.get.return_value = mock_response

        title, text = await fetch_doc_body("missing123", auth, client)
        assert title is None
        assert text is None

    async def test_network_error_returns_none_none(self):
        import httpx

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"

        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("connection refused")

        title, text = await fetch_doc_body("abc123", auth, client)
        assert title is None
        assert text is None

    async def test_field_mask_includes_body_content(self):
        auth = AsyncMock()
        auth.get_token.return_value = "test-token"

        mock_response = MagicMock()
        mock_response.json.return_value = {"title": "Doc", "body": {"content": []}}
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        await fetch_doc_body("abc123", auth, client)
        call_kwargs = client.get.call_args
        params = call_kwargs.kwargs.get("params", {})
        assert "body.content" in params.get("fields", "")


class TestExtractTitleFromHtml:
    def test_with_title(self):
        html = "<html><head><title>My Document</title></head><body></body></html>"
        assert extract_title_from_html(html) == "My Document"

    def test_without_title(self):
        html = "<html><head></head><body></body></html>"
        assert extract_title_from_html(html) is None

    def test_empty_title(self):
        html = "<html><head><title></title></head><body></body></html>"
        assert extract_title_from_html(html) is None

    def test_whitespace_title(self):
        html = "<html><head><title>  </title></head><body></body></html>"
        assert extract_title_from_html(html) is None


# --- OAuth2 auth tests ---


class TestLoadCachedToken:
    def test_valid_token_in_config_returns_credentials(self, monkeypatch):
        token_data = {
            "token": "access-token-123",
            "refresh_token": "refresh-token-456",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        result = _load_cached_token()
        assert result is not None
        assert result.token == "access-token-123"

    def test_missing_config_returns_none(self, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        assert _load_cached_token() is None

    def test_corrupt_token_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": {"bad": "data"}}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        # google-auth may accept partial data — at minimum it should not crash
        result = _load_cached_token()
        # Result may be None or a Credentials with no token; either is acceptable
        assert result is None or result.token is None

    def test_migrates_legacy_token_file(self, tmp_path, monkeypatch):
        legacy_file = tmp_path / "google_token.json"
        token_data = {
            "token": "legacy-tok",
            "refresh_token": "legacy-ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        legacy_file.write_text(json.dumps(token_data), encoding="utf-8")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE", legacy_file)

        saved_configs: list[dict] = []
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"googledocs": {"client_secrets_file": "/old/path"}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.save_config",
            lambda c: saved_configs.append(c),
        )

        result = _load_cached_token()
        assert result is not None
        assert result.token == "legacy-tok"
        # Legacy file should be deleted
        assert not legacy_file.exists()
        # Config should have google.token and no googledocs key
        assert len(saved_configs) == 1
        assert saved_configs[0]["google"]["token"] == token_data
        assert "googledocs" not in saved_configs[0]


class TestSaveToken:
    def test_saves_token_to_config(self, monkeypatch):
        saved_configs: list[dict] = []
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.save_config",
            lambda c: saved_configs.append(c),
        )

        creds = MagicMock()
        creds.to_json.return_value = '{"token": "abc", "refresh_token": "ref"}'

        _save_token(creds)

        assert len(saved_configs) == 1
        assert saved_configs[0]["google"]["token"] == {"token": "abc", "refresh_token": "ref"}

    def test_preserves_existing_config(self, monkeypatch):
        saved_configs: list[dict] = []
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"brains": ["/some/path"], "confluence": {"domain": "x"}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.save_config",
            lambda c: saved_configs.append(c),
        )

        creds = MagicMock()
        creds.to_json.return_value = '{"token": "new"}'

        _save_token(creds)

        assert saved_configs[0]["brains"] == ["/some/path"]
        assert saved_configs[0]["confluence"] == {"domain": "x"}
        assert saved_configs[0]["google"]["token"] == {"token": "new"}


class TestValidateConfig:
    def test_returns_true_with_cached_token(self, monkeypatch):
        """validate_config returns True when cached token exists — no OAuth triggered."""
        token_data = {
            "token": "tok",
            "refresh_token": "ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        provider = GoogleDocsAuthProvider()
        assert provider.validate_config() is True

    def test_returns_false_when_no_token(self, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        provider = GoogleDocsAuthProvider()
        assert provider.validate_config() is False


class TestLoadAuth:
    def test_cached_token_returns_oauth_credentials(self, monkeypatch):
        token_data = {
            "token": "tok",
            "refresh_token": "ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        provider = GoogleDocsAuthProvider()
        auth = provider.load_auth()
        assert isinstance(auth, GoogleOAuthCredentials)

    def test_no_token_returns_none(self, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        provider = GoogleDocsAuthProvider()
        assert provider.load_auth() is None


class TestGoogleOAuthCredentials:
    async def test_fresh_token_returns_directly(self):
        creds = MagicMock()
        creds.expired = False
        creds.token = "fresh-token"

        oauth = GoogleOAuthCredentials(creds)
        token = await oauth.get_token()
        assert token == "fresh-token"

    async def test_expired_token_triggers_refresh(self):
        creds = MagicMock()
        creds.expired = True
        creds.refresh_token = "ref-tok"
        creds.token = "refreshed-token"
        creds.to_json.return_value = '{"token": "refreshed-token"}'

        with patch("brain_sync.sources.googledocs.auth._save_token") as mock_save:
            oauth = GoogleOAuthCredentials(creds)
            token = await oauth.get_token()

        assert token == "refreshed-token"
        creds.refresh.assert_called_once()
        mock_save.assert_called_once_with(creds)

    async def test_refresh_error_raises_fetch_error(self):
        from google.auth.exceptions import RefreshError

        creds = MagicMock()
        creds.expired = True
        creds.refresh_token = "ref-tok"
        creds.refresh.side_effect = RefreshError("bad")

        oauth = GoogleOAuthCredentials(creds)
        with pytest.raises(FetchError, match=r"OAuth refresh failed.*--reauth"):
            await oauth.get_token()

    async def test_none_token_raises_fetch_error(self):
        creds = MagicMock()
        creds.expired = False
        creds.token = None

        oauth = GoogleOAuthCredentials(creds)
        with pytest.raises(FetchError, match=r"token missing.*--reauth"):
            await oauth.get_token()


class TestRunOAuthFlow:
    def test_runs_flow_and_saves_token(self, monkeypatch):
        saved_configs: list[dict] = []
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.save_config",
            lambda c: saved_configs.append(c),
        )

        from google.oauth2.credentials import Credentials

        fake_creds = MagicMock(spec=Credentials)
        fake_creds.to_json.return_value = '{"token": "new"}'
        fake_flow = MagicMock()
        fake_flow.run_local_server.return_value = fake_creds

        with patch(
            "google_auth_oauthlib.flow.InstalledAppFlow.from_client_config",
            return_value=fake_flow,
        ) as mock_from:
            result = run_oauth_flow()

        mock_from.assert_called_once()
        fake_flow.run_local_server.assert_called_once_with(port=0)
        assert result is fake_creds
        # Token should have been saved to config
        assert len(saved_configs) == 1
        assert saved_configs[0]["google"]["token"] == {"token": "new"}


class TestConfigureGoogle:
    def test_runs_oauth_when_not_authenticated(self, monkeypatch):
        from brain_sync.commands.config import configure_google

        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        with patch("brain_sync.sources.googledocs.auth.run_oauth_flow") as mock_flow:
            result = configure_google()

        assert result is True
        mock_flow.assert_called_once()

    def test_skips_oauth_when_already_authenticated(self, monkeypatch):
        from brain_sync.commands.config import configure_google

        token_data = {"token": "tok", "refresh_token": "ref", "client_id": "cid", "client_secret": "csec"}
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        with patch("brain_sync.sources.googledocs.auth.run_oauth_flow") as mock_flow:
            result = configure_google()

        assert result is True
        mock_flow.assert_not_called()

    def test_reauth_forces_oauth_even_when_authenticated(self, monkeypatch):
        from brain_sync.commands.config import configure_google

        token_data = {"token": "tok", "refresh_token": "ref", "client_id": "cid", "client_secret": "csec"}
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"google": {"token": token_data}},
        )
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._LEGACY_TOKEN_FILE",
            MagicMock(exists=lambda: False),
        )

        with patch("brain_sync.sources.googledocs.auth.run_oauth_flow") as mock_flow:
            result = configure_google(reauth=True)

        assert result is True
        mock_flow.assert_called_once()

    def test_configure_raises(self):
        provider = GoogleDocsAuthProvider()
        with pytest.raises(NotImplementedError):
            provider.configure()


class TestFetchDocTitle:
    async def test_success_returns_title(self):
        from brain_sync.sources.googledocs.rest import fetch_doc_title

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"
        mock_response = MagicMock()
        mock_response.json.return_value = {"title": "My Doc"}
        mock_response.raise_for_status = MagicMock()

        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_doc_title("abc123", auth, client)
        assert result == "My Doc"
        client.get.assert_called_once()
        call_kwargs = client.get.call_args
        assert "docs.googleapis.com/v1/documents/abc123" in call_kwargs.args[0]

    async def test_404_returns_none(self):
        import httpx

        from brain_sync.sources.googledocs.rest import fetch_doc_title

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"

        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_response
        )

        client = AsyncMock()
        client.get.return_value = mock_response

        result = await fetch_doc_title("missing123", auth, client)
        assert result is None

    async def test_network_error_returns_none(self):
        import httpx

        from brain_sync.sources.googledocs.rest import fetch_doc_title

        auth = AsyncMock()
        auth.get_token.return_value = "test-token"

        client = AsyncMock()
        client.get.side_effect = httpx.ConnectError("connection refused")

        result = await fetch_doc_title("abc123", auth, client)
        assert result is None

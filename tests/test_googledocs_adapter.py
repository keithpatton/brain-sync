"""Unit tests for Google Docs source adapter and OAuth2 authentication."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

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
    _GcloudFallbackCredentials,
    _get_client_secrets_path,
    _load_cached_token,
    _save_token,
    run_oauth_flow,
)
from brain_sync.sources.googledocs.rest import FetchError, extract_title_from_html

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
        assert caps.supports_version_check is False
        assert caps.supports_children is False
        assert caps.supports_links is False
        assert caps.supports_attachments is False
        assert caps.supports_comments is False
        assert caps.supports_context_sync is False


class TestCheckForUpdate:
    @pytest.fixture
    def adapter(self):
        return GoogleDocsAdapter()

    async def test_always_returns_unknown(self, adapter):
        from brain_sync.state import SourceState

        ss = SourceState(
            canonical_id="gdoc:abc123",
            source_url="https://docs.google.com/document/d/abc123/edit",
            source_type="googledocs",
        )
        result = await adapter.check_for_update(ss, Mock(), AsyncMock())
        assert result.status == UpdateStatus.UNKNOWN


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
        assert result.metadata_fingerprint is None
        assert result.source_html is None

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


class TestGcloudCmd:
    def test_resolves_when_on_path(self):
        with patch("brain_sync.sources.googledocs.rest.shutil.which", return_value="/usr/bin/gcloud"):
            from brain_sync.sources.googledocs.rest import _gcloud_cmd

            assert _gcloud_cmd() == "/usr/bin/gcloud"

    def test_raises_when_not_found(self):
        with (
            patch("brain_sync.sources.googledocs.rest.shutil.which", return_value=None),
            patch("os.path.isfile", return_value=False),
        ):
            from brain_sync.sources.googledocs.rest import _gcloud_cmd

            with pytest.raises(FileNotFoundError, match="gcloud not found"):
                _gcloud_cmd()


# --- OAuth2 auth tests ---


class TestLoadCachedToken:
    def test_valid_file_returns_credentials(self, tmp_path, monkeypatch):
        token_file = tmp_path / "google_token.json"
        token_data = {
            "token": "access-token-123",
            "refresh_token": "refresh-token-456",
            "client_id": "client-id",
            "client_secret": "client-secret",
        }
        token_file.write_text(json.dumps(token_data), encoding="utf-8")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", token_file)

        result = _load_cached_token()
        assert result is not None
        assert result.token == "access-token-123"

    def test_missing_file_returns_none(self, tmp_path, monkeypatch):
        token_file = tmp_path / "nonexistent.json"
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", token_file)

        assert _load_cached_token() is None

    def test_corrupt_file_returns_none(self, tmp_path, monkeypatch):
        token_file = tmp_path / "google_token.json"
        token_file.write_text("not valid json{{{", encoding="utf-8")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", token_file)

        assert _load_cached_token() is None


class TestSaveToken:
    def test_writes_json_atomically(self, tmp_path, monkeypatch):
        token_file = tmp_path / "google_token.json"
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", token_file)
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.CONFIG_DIR", tmp_path)

        creds = MagicMock()
        creds.to_json.return_value = '{"token": "abc"}'

        _save_token(creds)

        assert token_file.exists()
        assert json.loads(token_file.read_text(encoding="utf-8")) == {"token": "abc"}
        # .tmp should not remain after atomic replace
        assert not (tmp_path / "google_token.tmp").exists()

    def test_creates_config_dir_if_missing(self, tmp_path, monkeypatch):
        config_dir = tmp_path / "subdir"
        token_file = config_dir / "google_token.json"
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", token_file)
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.CONFIG_DIR", config_dir)

        creds = MagicMock()
        creds.to_json.return_value = '{"token": "xyz"}'

        _save_token(creds)

        assert config_dir.is_dir()
        assert token_file.exists()


class TestGetClientSecretsPath:
    def test_returns_path_when_configured_and_exists(self, tmp_path, monkeypatch):
        secrets_file = tmp_path / "client_secrets.json"
        secrets_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"googledocs": {"client_secrets_file": str(secrets_file)}},
        )

        result = _get_client_secrets_path()
        assert result == secrets_file

    def test_returns_none_when_not_configured(self, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})
        assert _get_client_secrets_path() is None

    def test_returns_none_when_file_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"googledocs": {"client_secrets_file": str(tmp_path / "missing.json")}},
        )
        assert _get_client_secrets_path() is None


class TestValidateConfig:
    def test_returns_true_with_cached_token(self, tmp_path, monkeypatch):
        """validate_config returns True when cached token exists — no OAuth triggered."""
        token_file = tmp_path / "google_token.json"
        token_data = {
            "token": "tok",
            "refresh_token": "ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        token_file.write_text(json.dumps(token_data), encoding="utf-8")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", token_file)

        provider = GoogleDocsAuthProvider()
        assert provider.validate_config() is True

    def test_returns_true_with_client_secrets_configured(self, tmp_path, monkeypatch):
        """validate_config returns True when client_secrets_file is in config — no OAuth triggered."""
        secrets_file = tmp_path / "secrets.json"
        secrets_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", tmp_path / "nope.json")
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"googledocs": {"client_secrets_file": str(secrets_file)}},
        )

        provider = GoogleDocsAuthProvider()
        assert provider.validate_config() is True

    def test_returns_true_with_gcloud_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", tmp_path / "nope.json")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})

        with patch("brain_sync.sources.googledocs.auth._gcloud_cmd", return_value="/usr/bin/gcloud"):
            provider = GoogleDocsAuthProvider()
            assert provider.validate_config() is True

    def test_returns_false_when_nothing_available(self, tmp_path, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", tmp_path / "nope.json")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})

        with patch("brain_sync.sources.googledocs.auth._gcloud_cmd", side_effect=FileNotFoundError):
            provider = GoogleDocsAuthProvider()
            assert provider.validate_config() is False


class TestLoadAuth:
    def test_cached_token_returns_oauth_credentials(self, tmp_path, monkeypatch):
        token_file = tmp_path / "google_token.json"
        token_data = {
            "token": "tok",
            "refresh_token": "ref",
            "client_id": "cid",
            "client_secret": "csec",
        }
        token_file.write_text(json.dumps(token_data), encoding="utf-8")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", token_file)

        provider = GoogleDocsAuthProvider()
        auth = provider.load_auth()
        assert isinstance(auth, GoogleOAuthCredentials)

    def test_no_token_with_client_secrets_runs_oauth(self, tmp_path, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", tmp_path / "nope.json")

        secrets_file = tmp_path / "secrets.json"
        secrets_file.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth.load_config",
            lambda: {"googledocs": {"client_secrets_file": str(secrets_file)}},
        )

        fake_creds = MagicMock()
        fake_creds.token = "new-token"
        with patch("brain_sync.sources.googledocs.auth.run_oauth_flow", return_value=fake_creds) as mock_flow:
            provider = GoogleDocsAuthProvider()
            auth = provider.load_auth()

        mock_flow.assert_called_once_with(secrets_file)
        assert isinstance(auth, GoogleOAuthCredentials)

    def test_no_token_no_secrets_with_gcloud_returns_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", tmp_path / "nope.json")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})

        with patch("brain_sync.sources.googledocs.auth._gcloud_cmd", return_value="/usr/bin/gcloud"):
            provider = GoogleDocsAuthProvider()
            auth = provider.load_auth()

        assert isinstance(auth, _GcloudFallbackCredentials)

    def test_nothing_available_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", tmp_path / "nope.json")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.load_config", lambda: {})

        with patch("brain_sync.sources.googledocs.auth._gcloud_cmd", side_effect=FileNotFoundError):
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
    def test_runs_flow_and_saves_token(self, tmp_path, monkeypatch):
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.GOOGLE_TOKEN_FILE", tmp_path / "token.json")
        monkeypatch.setattr("brain_sync.sources.googledocs.auth.CONFIG_DIR", tmp_path)

        from google.oauth2.credentials import Credentials

        fake_creds = MagicMock(spec=Credentials)
        fake_creds.to_json.return_value = '{"token": "new"}'
        fake_flow = MagicMock()
        fake_flow.run_local_server.return_value = fake_creds

        with patch(
            "brain_sync.sources.googledocs.auth.InstalledAppFlow.from_client_secrets_file",
            return_value=fake_flow,
        ) as mock_from:
            secrets_path = tmp_path / "client_secrets.json"
            result = run_oauth_flow(secrets_path)

        mock_from.assert_called_once()
        fake_flow.run_local_server.assert_called_once_with(port=0)
        assert result is fake_creds
        # Token should have been saved
        token_file = tmp_path / "token.json"
        assert token_file.exists()


class TestGcloudFallbackCredentials:
    async def test_delegates_to_get_access_token(self):
        with patch(
            "brain_sync.sources.googledocs.auth._get_access_token",
            new_callable=AsyncMock,
            return_value="gcloud-token",
        ):
            fallback = _GcloudFallbackCredentials()
            token = await fallback.get_token()
            assert token == "gcloud-token"


class TestConfigureGoogledocs:
    def test_client_secrets_saves_config_and_runs_flow(self, tmp_path, monkeypatch):
        from brain_sync.commands.config import configure_googledocs

        secrets = tmp_path / "client.json"
        secrets.write_text("{}", encoding="utf-8")

        saved_configs: list[dict] = []
        monkeypatch.setattr("brain_sync.commands.config.load_config", lambda: {})
        monkeypatch.setattr("brain_sync.commands.config.save_config", lambda c: saved_configs.append(c))

        fake_creds = MagicMock()
        with patch("brain_sync.sources.googledocs.auth.run_oauth_flow", return_value=fake_creds) as mock_flow:
            result = configure_googledocs(client_secrets=str(secrets))

        assert result is True
        assert len(saved_configs) == 1
        assert saved_configs[0]["googledocs"]["client_secrets_file"] == str(secrets.resolve())
        mock_flow.assert_called_once()

    def test_client_secrets_file_not_found(self, tmp_path):
        from brain_sync.commands.config import configure_googledocs

        result = configure_googledocs(client_secrets=str(tmp_path / "missing.json"))
        assert result is False

    def test_reauth_runs_flow(self, tmp_path, monkeypatch):
        from brain_sync.commands.config import configure_googledocs

        secrets = tmp_path / "client.json"
        secrets.write_text("{}", encoding="utf-8")

        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._get_client_secrets_path",
            lambda: secrets,
        )

        fake_creds = MagicMock()
        with patch("brain_sync.sources.googledocs.auth.run_oauth_flow", return_value=fake_creds) as mock_flow:
            result = configure_googledocs(reauth=True)

        assert result is True
        mock_flow.assert_called_once_with(secrets)

    def test_reauth_fails_without_secrets(self, monkeypatch):
        from brain_sync.commands.config import configure_googledocs

        monkeypatch.setattr(
            "brain_sync.sources.googledocs.auth._get_client_secrets_path",
            lambda: None,
        )

        result = configure_googledocs(reauth=True)
        assert result is False

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

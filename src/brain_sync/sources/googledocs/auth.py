"""Google Docs authentication — native OAuth2 with gcloud CLI fallback."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from brain_sync.config import CONFIG_DIR, load_config, save_config
from brain_sync.sources.googledocs.rest import FetchError, _gcloud_cmd, _get_access_token

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
]

_GOOGLE_CLIENT_CONFIG = {
    "installed": {
        "client_id": "959083310575-0765qfu9j0r64sn8ree3s857sd0pvrsu.apps.googleusercontent.com",
        "project_id": "brain-sync",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "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",
        "redirect_uris": ["http://localhost"],
    }
}

_LEGACY_TOKEN_FILE = CONFIG_DIR / "google_token.json"


@dataclass
class GoogleOAuthCredentials:
    """Wraps google.oauth2.credentials.Credentials with async token access."""

    _credentials: Credentials

    async def get_token(self) -> str:
        if self._credentials.expired and self._credentials.refresh_token:
            log.debug("Refreshing Google OAuth token")
            try:
                await asyncio.to_thread(self._credentials.refresh, Request())
            except RefreshError as e:
                raise FetchError("Google OAuth refresh failed. Run: brain-sync config google --reauth") from e
            _save_token(self._credentials)
        if not self._credentials.token:
            raise FetchError("Google OAuth token missing. Run: brain-sync config google --reauth")
        return self._credentials.token


class _GcloudFallbackCredentials:
    """Fallback: shells out to gcloud auth print-access-token."""

    async def get_token(self) -> str:
        return await _get_access_token()


class GoogleDocsAuthProvider:
    def load_auth(self) -> GoogleOAuthCredentials | _GcloudFallbackCredentials | None:
        """Load auth credentials, trying native OAuth2 first, then gcloud fallback."""
        # 1. Cached token (valid or refreshable)
        creds = _load_cached_token()
        if creds is not None:
            return GoogleOAuthCredentials(creds)

        # 2. Fallback to gcloud
        try:
            _gcloud_cmd()
            return _GcloudFallbackCredentials()
        except FileNotFoundError:
            return None

    def validate_config(self) -> bool:
        """Check if auth COULD work. Does NOT trigger OAuth or open a browser."""
        if _load_cached_token() is not None:
            return True
        try:
            _gcloud_cmd()
            return True
        except FileNotFoundError:
            return False

    def configure(self, **kwargs: str) -> None:
        raise NotImplementedError("Use: brain-sync config google")


# --- Helpers (module-level, not on provider) ---


def run_oauth_flow() -> Credentials:
    """Run browser-based OAuth consent. Saves token to config.json."""
    log.info("Opening browser for Google OAuth consent...")
    flow = InstalledAppFlow.from_client_config(_GOOGLE_CLIENT_CONFIG, scopes=SCOPES)
    creds = flow.run_local_server(port=0)
    if not isinstance(creds, Credentials):
        msg = f"Unexpected credential type from OAuth flow: {type(creds).__name__}"
        raise TypeError(msg)
    _save_token(creds)
    log.info("Google OAuth token saved to config")
    return creds


def _load_cached_token() -> Credentials | None:
    """Load token from config.json. Migrates legacy google_token.json if needed."""
    config = load_config()
    token_dict = config.get("google", {}).get("token")

    # Migration: legacy google_token.json → config.json
    if token_dict is None and _LEGACY_TOKEN_FILE.exists():
        token_dict = _migrate_legacy_token(config)

    if token_dict is None:
        return None

    try:
        creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
    except Exception:
        log.debug("Failed to load cached Google token from config", exc_info=True)
        return None
    if not isinstance(creds, Credentials):
        log.debug("Unexpected credential type from cached token: %s", type(creds).__name__)
        return None
    return creds


def _migrate_legacy_token(config: dict) -> dict | None:
    """Migrate token from legacy google_token.json into config.json."""
    try:
        token_dict = json.loads(_LEGACY_TOKEN_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.debug("Failed to read legacy google_token.json for migration", exc_info=True)
        return None

    config.setdefault("google", {})["token"] = token_dict
    # Clean up legacy googledocs.client_secrets_file if present
    config.pop("googledocs", None)
    save_config(config)

    _LEGACY_TOKEN_FILE.unlink(missing_ok=True)
    log.info("Migrated Google token from google_token.json into config.json")
    return token_dict


def _save_token(creds: Credentials) -> None:
    """Save token into config.json under google.token."""
    token_dict = json.loads(creds.to_json())
    config = load_config()
    config.setdefault("google", {})["token"] = token_dict
    save_config(config)

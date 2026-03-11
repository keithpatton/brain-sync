"""Google Docs authentication — native OAuth2 with gcloud CLI fallback."""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from brain_sync.config import CONFIG_DIR, load_config
from brain_sync.sources.googledocs.rest import FetchError, _gcloud_cmd, _get_access_token

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
]
GOOGLE_TOKEN_FILE = CONFIG_DIR / "google_token.json"


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
                raise FetchError("Google OAuth refresh failed. Run: brain-sync config googledocs --reauth") from e
            _save_token(self._credentials)
        if not self._credentials.token:
            raise FetchError("Google OAuth token missing. Run: brain-sync config googledocs --reauth")
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

        # 2. Auto-run OAuth if client secrets path configured
        client_secrets = _get_client_secrets_path()
        if client_secrets is not None and client_secrets.exists():
            creds = run_oauth_flow(client_secrets)
            return GoogleOAuthCredentials(creds)

        # 3. Fallback to gcloud
        try:
            _gcloud_cmd()
            return _GcloudFallbackCredentials()
        except FileNotFoundError:
            return None

    def validate_config(self) -> bool:
        """Check if auth COULD work. Does NOT trigger OAuth or open a browser."""
        if _load_cached_token() is not None:
            return True
        if _get_client_secrets_path() is not None:
            return True
        try:
            _gcloud_cmd()
            return True
        except FileNotFoundError:
            return False

    def configure(self, **kwargs: str) -> None:
        raise NotImplementedError("Use: brain-sync config googledocs --client-secrets <path>")


# --- Helpers (module-level, not on provider) ---


def run_oauth_flow(client_secrets_path: Path) -> Credentials:
    """Run browser-based OAuth consent. Saves token to GOOGLE_TOKEN_FILE."""
    log.info("Opening browser for Google OAuth consent...")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), scopes=SCOPES)
    creds = flow.run_local_server(port=0)
    if not isinstance(creds, Credentials):
        msg = f"Unexpected credential type from OAuth flow: {type(creds).__name__}"
        raise TypeError(msg)
    _save_token(creds)
    log.info("Google OAuth token saved to %s", GOOGLE_TOKEN_FILE)
    return creds


def _load_cached_token() -> Credentials | None:
    """Load token from disk. Returns Credentials if file exists (even if expired)."""
    if not GOOGLE_TOKEN_FILE.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_FILE), SCOPES)
    except Exception:
        log.debug("Failed to load cached Google token", exc_info=True)
        return None
    if not isinstance(creds, Credentials):
        log.debug("Unexpected credential type from cached token: %s", type(creds).__name__)
        return None
    return creds


def _save_token(creds: Credentials) -> None:
    """Atomic write of token JSON with restricted permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = GOOGLE_TOKEN_FILE.with_suffix(".tmp")
    tmp.write_text(creds.to_json(), encoding="utf-8")
    tmp.replace(GOOGLE_TOKEN_FILE)
    if sys.platform != "win32":
        GOOGLE_TOKEN_FILE.chmod(0o600)


def _get_client_secrets_path() -> Path | None:
    """Read googledocs.client_secrets_file from config.json."""
    config = load_config()
    path_str = config.get("googledocs", {}).get("client_secrets_file")
    if path_str:
        p = Path(path_str)
        if p.exists():
            return p
    return None

"""Confluence source adapter."""

from __future__ import annotations

import html
import logging
import re
from typing import Any

import httpx

from brain_sync.sources import extract_confluence_page_id
from brain_sync.sources.base import (
    AuthProvider,
    SourceCapabilities,
    SourceFetchResult,
    SourceStateLike,
    UpdateCheckResult,
    UpdateStatus,
)
from brain_sync.sources.confluence.auth import ConfluenceAuthProvider
from brain_sync.sources.confluence.comments import fetch_structured_comments
from brain_sync.sources.confluence.rest import fetch_page_body, fetch_page_version, fetch_users_by_account_ids
from brain_sync.sources.conversion import html_to_markdown

log = logging.getLogger(__name__)

_AC_IMAGE_RE = re.compile(
    r'<ac:image[^>]*>\s*<ri:attachment\s+ri:filename="([^"]+)"[^/]*/?\s*>\s*</ac:image>',
    re.DOTALL,
)
_USER_RE = re.compile(r'<ac:link>\s*<ri:user\b[^>]*ri:account-id="([^"]+)"[^>]*/>\s*</ac:link>', re.DOTALL)
_USER_STANDALONE_RE = re.compile(r'<ri:user\b[^>]*ri:account-id="([^"]+)"[^>]*/>', re.DOTALL)
_STATUS_RE = re.compile(
    r'<ac:structured-macro\b[^>]*ac:name="status"[^>]*>.*?'
    r'<ac:parameter\b[^>]*ac:name="title"[^>]*>(.*?)</ac:parameter>.*?'
    r"</ac:structured-macro>",
    re.DOTALL,
)
_EMOTICON_RE = re.compile(r'<ac:emoticon\b[^>]*ac:name="([^"]+)"[^>]*/>', re.DOTALL)
_EMOTICON_TEXT_OVERRIDES = {
    "tick": "Yes",
    "cross": "No",
}


def _extract_user_account_ids(html_text: str) -> list[str]:
    account_ids: list[str] = []
    seen: set[str] = set()
    for account_id in _USER_STANDALONE_RE.findall(html_text):
        if account_id not in seen:
            seen.add(account_id)
            account_ids.append(account_id)
    return account_ids


def _preprocess_html(html_text: str, *, user_names: dict[str, str] | None = None) -> str:
    """Convert Confluence-specific image tags to standard <img> before markdownify."""
    processed = _AC_IMAGE_RE.sub(
        lambda m: f'<img src="attachment-ref:{m.group(1)}" alt="{m.group(1)}">',
        html_text,
    )
    processed = _STATUS_RE.sub(lambda m: html.escape(m.group(1).strip()), processed)
    processed = _EMOTICON_RE.sub(
        lambda m: html.escape(_EMOTICON_TEXT_OVERRIDES.get(m.group(1), m.group(1))),
        processed,
    )
    if user_names:
        processed = _USER_RE.sub(
            lambda m: html.escape(user_names.get(m.group(1), m.group(1))),
            processed,
        )
        processed = _USER_STANDALONE_RE.sub(
            lambda m: html.escape(user_names.get(m.group(1), m.group(1))),
            processed,
        )
    return processed


_auth_provider = ConfluenceAuthProvider()


class ConfluenceAdapter:
    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            supports_version_check=True,
            supports_children=True,
            supports_attachments=True,
            supports_comments=True,
        )

    @property
    def auth_provider(self) -> AuthProvider:
        return _auth_provider

    async def check_for_update(
        self,
        source_state: SourceStateLike,
        auth: object,
        client: httpx.AsyncClient,
    ) -> UpdateCheckResult:
        page_id = extract_confluence_page_id(source_state.source_url)
        version_info = await fetch_page_version(page_id, auth, client)  # pyright: ignore[reportArgumentType]
        if version_info is None or version_info.version is None:
            return UpdateCheckResult(status=UpdateStatus.UNKNOWN)
        version_str = str(version_info.version)
        status = UpdateStatus.UNCHANGED if version_str == source_state.remote_fingerprint else UpdateStatus.CHANGED
        return UpdateCheckResult(
            status=status,
            fingerprint=version_str,
            title=None,
            remote_last_changed_utc=version_info.last_changed_utc,
            adapter_state={"version": version_str},
        )

    async def fetch(
        self,
        source_state: SourceStateLike,
        auth: object,
        client: httpx.AsyncClient,
        root: None = None,
        prior_adapter_state: dict[str, Any] | None = None,
    ) -> SourceFetchResult:
        page_id = extract_confluence_page_id(source_state.source_url)
        html, title, version, last_changed_utc = await fetch_page_body(page_id, auth, client)  # pyright: ignore[reportArgumentType]
        comments = await fetch_structured_comments(page_id, auth, client)  # pyright: ignore[reportArgumentType]
        user_names: dict[str, str] = {}
        account_ids = _extract_user_account_ids(html)
        if account_ids:
            try:
                user_names = await fetch_users_by_account_ids(account_ids, auth, client)  # pyright: ignore[reportArgumentType]
            except Exception as exc:
                log.debug("Confluence user lookup failed for page %s: %s", page_id, exc)
        html = _preprocess_html(html, user_names=user_names)
        markdown = html_to_markdown(html)

        if version is not None:
            fingerprint = str(version)
        elif prior_adapter_state:
            fingerprint = prior_adapter_state.get("version")
        else:
            fingerprint = None

        return SourceFetchResult(
            body_markdown=markdown,
            comments=comments,
            remote_fingerprint=fingerprint,
            remote_last_changed_utc=last_changed_utc,
            title=title,
            source_html=html,
        )

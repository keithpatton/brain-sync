"""Google Docs source adapter."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from brain_sync.converter import html_to_markdown
from brain_sync.sources import extract_google_doc_id
from brain_sync.sources.base import (
    AuthProvider,
    SourceCapabilities,
    SourceFetchResult,
    UpdateCheckResult,
    UpdateStatus,
)
from brain_sync.sources.googledocs.auth import GoogleDocsAuthProvider
from brain_sync.sources.googledocs.rest import extract_title_from_html, fetch_doc_html
from brain_sync.state import SourceState

log = logging.getLogger(__name__)

_auth_provider = GoogleDocsAuthProvider()


class GoogleDocsAdapter:
    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            supports_version_check=False,
            supports_children=False,
            supports_links=False,
            supports_attachments=False,
            supports_comments=False,
            supports_context_sync=False,
        )

    @property
    def auth_provider(self) -> AuthProvider:
        return _auth_provider

    async def check_for_update(
        self,
        source_state: SourceState,
        auth: object,
        client: httpx.AsyncClient,
    ) -> UpdateCheckResult:
        return UpdateCheckResult(status=UpdateStatus.UNKNOWN)

    async def fetch(
        self,
        source_state: SourceState,
        auth: object,
        client: httpx.AsyncClient,
        root: None = None,
        prior_adapter_state: dict[str, Any] | None = None,
    ) -> SourceFetchResult:
        doc_id = extract_google_doc_id(source_state.source_url)
        html = await fetch_doc_html(doc_id, auth, client)  # pyright: ignore[reportArgumentType]
        title = extract_title_from_html(html)
        markdown = html_to_markdown(html)
        return SourceFetchResult(
            body_markdown=markdown,
            comments=[],
            metadata_fingerprint=None,
            title=title,
        )

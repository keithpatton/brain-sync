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
from brain_sync.sources.googledocs.rest import (
    compute_semantic_fingerprint,
    extract_title_from_html,
    fetch_doc_body,
    fetch_doc_html,
    fetch_doc_title,
)
from brain_sync.state import SourceState

log = logging.getLogger(__name__)


class GoogleDocsAdapter:
    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            supports_version_check=True,
            supports_children=False,
            supports_links=False,
            supports_attachments=False,
            supports_comments=False,
            supports_context_sync=False,
        )

    @property
    def auth_provider(self) -> AuthProvider:
        from brain_sync.sources.googledocs.auth import GoogleDocsAuthProvider

        if not hasattr(self, "_auth_provider"):
            self._auth_provider = GoogleDocsAuthProvider()
        return self._auth_provider

    async def check_for_update(
        self,
        source_state: SourceState,
        auth: object,
        client: httpx.AsyncClient,
    ) -> UpdateCheckResult:
        doc_id = extract_google_doc_id(source_state.source_url)
        title, text = await fetch_doc_body(doc_id, auth, client)  # pyright: ignore[reportArgumentType]
        if text is None:
            return UpdateCheckResult(status=UpdateStatus.UNKNOWN, title=title)
        fingerprint = compute_semantic_fingerprint(text)
        if fingerprint == source_state.metadata_fingerprint:
            return UpdateCheckResult(
                status=UpdateStatus.UNCHANGED,
                fingerprint=fingerprint,
                title=title,
            )
        return UpdateCheckResult(
            status=UpdateStatus.CHANGED,
            fingerprint=fingerprint,
            title=title,
            adapter_state={"semanticFingerprint": fingerprint, "title": title},
        )

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
        if not title:
            title = (prior_adapter_state or {}).get("title") or await fetch_doc_title(doc_id, auth, client)  # pyright: ignore[reportArgumentType]
        markdown = html_to_markdown(html)
        fingerprint = (prior_adapter_state or {}).get("semanticFingerprint")
        return SourceFetchResult(
            body_markdown=markdown,
            comments=[],
            metadata_fingerprint=fingerprint,
            title=title,
        )

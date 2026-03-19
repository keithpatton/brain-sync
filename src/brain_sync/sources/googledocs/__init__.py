"""Google Docs source adapter."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from brain_sync.sources import extract_google_doc_id
from brain_sync.sources.base import (
    AuthProvider,
    DiscoveredImage,
    SourceCapabilities,
    SourceFetchResult,
    SourceStateLike,
    UpdateCheckResult,
    UpdateStatus,
)
from brain_sync.sources.googledocs.rest import (
    FetchError,
    compute_semantic_fingerprint,
    extract_canonical_text,
    fetch_all_tabs,
    fetch_doc_title,
    generate_tabs_markdown,
)

log = logging.getLogger(__name__)


class GoogleDocsAdapter:
    @property
    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            supports_version_check=True,
            supports_children=False,
            supports_attachments=True,
            supports_comments=False,
        )

    @property
    def auth_provider(self) -> AuthProvider:
        from brain_sync.sources.googledocs.auth import GoogleDocsAuthProvider

        if not hasattr(self, "_auth_provider"):
            self._auth_provider = GoogleDocsAuthProvider()
        return self._auth_provider

    async def check_for_update(
        self,
        source_state: SourceStateLike,
        auth: object,
        client: httpx.AsyncClient,
    ) -> UpdateCheckResult:
        doc_id = extract_google_doc_id(source_state.source_url)
        tabs_doc = await fetch_all_tabs(doc_id, auth, client)  # pyright: ignore[reportArgumentType]
        if tabs_doc is None:
            return UpdateCheckResult(status=UpdateStatus.UNKNOWN, title=None)
        fingerprint = compute_semantic_fingerprint(extract_canonical_text(tabs_doc))
        title = tabs_doc.title
        if fingerprint == source_state.remote_fingerprint:
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
        source_state: SourceStateLike,
        auth: object,
        client: httpx.AsyncClient,
        root: None = None,
        prior_adapter_state: dict[str, Any] | None = None,
    ) -> SourceFetchResult:
        doc_id = extract_google_doc_id(source_state.source_url)
        tabs_doc = await fetch_all_tabs(doc_id, auth, client)  # pyright: ignore[reportArgumentType]
        if tabs_doc is None:
            raise FetchError(f"Failed to fetch tabs for {doc_id}")
        title = (
            tabs_doc.title or (prior_adapter_state or {}).get("title") or await fetch_doc_title(doc_id, auth, client)  # pyright: ignore[reportArgumentType]
        )
        body_markdown = generate_tabs_markdown(tabs_doc, doc_id=doc_id)
        fingerprint = (prior_adapter_state or {}).get("semanticFingerprint")

        # Build deduplicated inline image list from all tabs
        images_by_cid: dict[str, DiscoveredImage] = {}
        for tab in tabs_doc.tabs:
            for obj_id, img in tab.inline_objects.items():
                cid = f"gdoc-image:{doc_id}:{obj_id}"
                if cid not in images_by_cid:
                    images_by_cid[cid] = DiscoveredImage(
                        canonical_id=cid,
                        download_url=img.content_uri,
                        title=img.title,
                        mime_type=img.mime_type,
                    )

        # Auth headers for image download
        download_headers: dict[str, str] = {}
        if images_by_cid:
            token = await auth.get_token()  # pyright: ignore[reportAttributeAccessIssue]
            download_headers = {"Authorization": f"Bearer {token}"}

        return SourceFetchResult(
            body_markdown=body_markdown,
            comments=[],
            remote_fingerprint=fingerprint,
            title=title,
            inline_images=list(images_by_cid.values()),
            download_headers=download_headers,
            attachment_parent_id=f"gdoc:{doc_id}",
        )

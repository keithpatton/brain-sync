"""Google Docs source adapter."""

from __future__ import annotations

import hashlib
import logging
import re
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
    fetch_drive_metadata,
    generate_tabs_markdown,
)

log = logging.getLogger(__name__)
_MANAGED_ATTACHMENTS_PREFIX = ".brain-sync/attachments"


def _normalize_materialized_google_markdown(
    markdown: str,
    *,
    doc_id: str,
    image_canonical_ids: tuple[str, ...],
) -> str:
    """Normalize prior materialized markdown back to Google body semantics.

    Google runtime upstream freshness is defined around synchronized document
    body semantics, not around machine-local attachment paths. For docs with
    inline images, previously materialized markdown may contain local managed
    attachment paths instead of the stable ``attachment-ref:`` links emitted by
    the adapter fetch path. This helper rewrites those paths back to stable
    refs so the adapter can compare body semantics without changing attachment
    fetching/materialization behavior.
    """

    normalized = markdown
    source_dir = f"g{doc_id}"
    for canonical_id in image_canonical_ids:
        object_id = canonical_id.rsplit(":", 1)[1]
        pattern = re.compile(
            rf"\]\((?:\./)?{re.escape(_MANAGED_ATTACHMENTS_PREFIX)}/"
            rf"{re.escape(source_dir)}/a{re.escape(object_id)}-[^)]*\)"
        )
        normalized = pattern.sub(f"](attachment-ref:{canonical_id})", normalized)
    return normalized


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
        metadata = await fetch_drive_metadata(doc_id, auth, client)  # pyright: ignore[reportArgumentType]
        if metadata is None or metadata.version is None:
            return UpdateCheckResult(status=UpdateStatus.UNKNOWN, title=None)
        fingerprint = metadata.version
        title = metadata.title
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
            adapter_state={"version": fingerprint, "title": title, "modified_time": metadata.modified_time},
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
        cached_title = (prior_adapter_state or {}).get("title")
        cached_version = (prior_adapter_state or {}).get("version")
        cached_modified_time = (prior_adapter_state or {}).get("modified_time")
        cached_existing_markdown = (prior_adapter_state or {}).get("existing_materialized_markdown")
        metadata = None
        if cached_version is None or (tabs_doc.title is None and cached_title is None):
            metadata = await fetch_drive_metadata(doc_id, auth, client)  # pyright: ignore[reportArgumentType]
        title = (
            tabs_doc.title
            or cached_title
            or (metadata.title if metadata else None)
            or await fetch_doc_title(doc_id, auth, client)  # pyright: ignore[reportArgumentType]
        )
        body_markdown = generate_tabs_markdown(tabs_doc, doc_id=doc_id)
        body_hash = hashlib.sha256(body_markdown.encode("utf-8")).hexdigest()
        fingerprint = cached_version or (metadata.version if metadata else None)
        if fingerprint is None:
            fingerprint = compute_semantic_fingerprint(extract_canonical_text(tabs_doc))

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

        remote_last_changed_utc: str | None = None
        remote_modified_time = metadata.modified_time if metadata is not None else cached_modified_time
        if remote_modified_time:
            if source_state.content_hash is None:
                remote_last_changed_utc = remote_modified_time
            elif source_state.sync_attachments and images_by_cid and isinstance(cached_existing_markdown, str):
                existing_markdown = _normalize_materialized_google_markdown(
                    cached_existing_markdown,
                    doc_id=doc_id,
                    image_canonical_ids=tuple(sorted(images_by_cid)),
                )
                if existing_markdown != body_markdown:
                    remote_last_changed_utc = remote_modified_time
            elif body_hash != source_state.content_hash:
                remote_last_changed_utc = remote_modified_time

        return SourceFetchResult(
            body_markdown=body_markdown,
            comments=[],
            remote_fingerprint=fingerprint,
            remote_last_changed_utc=remote_last_changed_utc,
            title=title,
            inline_images=list(images_by_cid.values()),
            download_headers=download_headers,
            attachment_parent_id=f"gdoc:{doc_id}",
        )

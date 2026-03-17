"""Confluence source adapter."""

from __future__ import annotations

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
from brain_sync.sources.confluence.rest import fetch_page_body, fetch_page_version
from brain_sync.sources.conversion import html_to_markdown

log = logging.getLogger(__name__)

_AC_IMAGE_RE = re.compile(
    r'<ac:image[^>]*>\s*<ri:attachment\s+ri:filename="([^"]+)"[^/]*/?\s*>\s*</ac:image>',
    re.DOTALL,
)


def _preprocess_html(html: str) -> str:
    """Convert Confluence-specific image tags to standard <img> before markdownify."""
    return _AC_IMAGE_RE.sub(
        lambda m: f'<img src="attachment-ref:{m.group(1)}" alt="{m.group(1)}">',
        html,
    )


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
        v = await fetch_page_version(page_id, auth, client)  # pyright: ignore[reportArgumentType]
        if v is None:
            return UpdateCheckResult(status=UpdateStatus.UNKNOWN)
        version_str = str(v)
        status = UpdateStatus.UNCHANGED if version_str == source_state.metadata_fingerprint else UpdateStatus.CHANGED
        return UpdateCheckResult(
            status=status,
            fingerprint=version_str,
            title=None,
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
        html, title, version = await fetch_page_body(page_id, auth, client)  # pyright: ignore[reportArgumentType]
        comments = await fetch_structured_comments(page_id, auth, client)  # pyright: ignore[reportArgumentType]
        html = _preprocess_html(html)
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
            metadata_fingerprint=fingerprint,
            title=title,
            source_html=html,
        )

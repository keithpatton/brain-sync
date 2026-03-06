from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx

from brain_sync.confluence_rest import (
    ConfluenceAuth,
    fetch_page_body,
    fetch_page_version,
    get_confluence_auth,
)
from brain_sync.converter import html_to_markdown
from brain_sync.fileops import content_hash, resolve_dirty_path, touch_dirty, write_if_changed
from brain_sync.manifest import Manifest, SourceEntry
from brain_sync.sources import (
    SourceType,
    canonical_filename,
    canonical_id,
    detect_source_type,
    extract_confluence_page_id,
    extract_google_doc_id,
)
from brain_sync.sources.confluence import (
    confluence_comments,
    confluence_fetch,
    confluence_title,
)
from brain_sync.sources.googledocs import googledocs_fetch
from brain_sync.state import SourceState, load_relationships_for_primary

log = logging.getLogger(__name__)


async def _resolve_auto_filename(
    url: str, source_type: SourceType, auth: ConfluenceAuth | None, http_client: httpx.AsyncClient,
) -> str:
    """Derive an ID-anchored filename from the source URL/title."""
    if source_type == SourceType.CONFLUENCE:
        page_id = extract_confluence_page_id(url)
        title = None
        # Try REST API first for title
        if auth:
            try:
                _, title, _ = await fetch_page_body(page_id, auth, http_client)
            except Exception:
                pass
        # Fall back to confluence-cli
        if title is None:
            title = await confluence_title(page_id)
        return canonical_filename(source_type, page_id, title)

    if source_type == SourceType.GOOGLE_DOCS:
        doc_id = extract_google_doc_id(url)
        return canonical_filename(source_type, doc_id, None)

    return "untitled.md"


def _has_context_flags(entry: SourceEntry) -> bool:
    return entry.include_links or entry.include_children or entry.include_attachments


async def process_source(
    manifest: Manifest,
    entry: SourceEntry,
    source_state: SourceState,
    http_client: httpx.AsyncClient,
    root: Path | None = None,
) -> bool:
    """Process a single source. Returns True if content changed."""
    source_type = detect_source_type(entry.url)
    now = datetime.now(timezone.utc).isoformat()
    auth = get_confluence_auth()

    # Resolve output filename
    filename = entry.file
    if filename == "auto":
        filename = await _resolve_auto_filename(entry.url, source_type, auth, http_client)
        source_state.target_file = filename

    target = manifest.path.parent / filename

    if source_type == SourceType.CONFLUENCE:
        page_id = extract_confluence_page_id(entry.url)

        # Cheap version check via REST API (preferred) or CLI fallback
        version: str | None = None
        if auth:
            v = await fetch_page_version(page_id, auth, http_client)
            if v is not None:
                version = str(v)
        if version is not None and version == source_state.metadata_fingerprint:
            log.debug("Confluence page %s unchanged (version %s)", page_id, version)
            source_state.last_checked_utc = now
            return False

        # Full fetch via REST API (preferred) or CLI fallback
        html: str | None = None
        title: str | None = None
        if auth:
            try:
                html, title, v = await fetch_page_body(page_id, auth, http_client)
                if v is not None:
                    version = str(v)
            except Exception as e:
                log.debug("REST body fetch failed, falling back to CLI: %s", e)
                html = None

        if html is None:
            html = await confluence_fetch(page_id)

        comments_md = await confluence_comments(page_id)
        if version is not None:
            source_state.metadata_fingerprint = version

        # Context discovery & sync (only when primary content changed)
        if _has_context_flags(entry) and root is not None:
            primary_cid = canonical_id(source_type, entry.url)
            if auth:
                try:
                    from brain_sync.context import process_context
                    await process_context(
                        manifest_dir=manifest.path.parent,
                        entry_url=entry.url,
                        primary_html=html,
                        primary_canonical_id=primary_cid,
                        auth=auth,
                        client=http_client,
                        root=root,
                        include_links=entry.include_links,
                        include_children=entry.include_children,
                        include_attachments=entry.include_attachments,
                    )
                except Exception as e:
                    log.warning("Context processing failed for %s: %s", entry.url, e)
            else:
                log.warning("Context flags enabled but no REST auth available, skipping context for %s", entry.url)

            # Link rewriting (only if context relationships exist)
            if root is not None:
                try:
                    rels = load_relationships_for_primary(root, primary_cid)
                    if rels:
                        from brain_sync.link_rewriter import rewrite_links
                        cid_to_path = {
                            r.canonical_id: f"./{r.local_path}" for r in rels
                        }
                        # Will be applied to markdown after conversion below
                except Exception as e:
                    log.debug("Link map build failed: %s", e)
                    rels = []
            else:
                rels = []
        else:
            rels = []
            primary_cid = None

    elif source_type == SourceType.GOOGLE_DOCS:
        doc_id = extract_google_doc_id(entry.url)
        html = await googledocs_fetch(doc_id, http_client)
        comments_md = None
        rels = []
    else:
        log.warning("Unsupported source type for %s", entry.url)
        return False

    markdown = html_to_markdown(html)

    # Rewrite links if we have context relationships
    if rels:
        from brain_sync.link_rewriter import rewrite_links
        cid_to_path = {r.canonical_id: f"./{r.local_path}" for r in rels}
        markdown = rewrite_links(markdown, cid_to_path)

    # Append comments section if available
    if source_type == SourceType.CONFLUENCE and comments_md:
        markdown = markdown.rstrip("\n") + "\n\n---\n\n## Comments\n\n" + comments_md + "\n"

    changed = write_if_changed(target, markdown)

    source_state.last_checked_utc = now
    source_state.content_hash = content_hash(markdown.encode("utf-8"))
    source_state.source_type = source_type.value

    if changed:
        source_state.last_changed_utc = now
        dirty_path = resolve_dirty_path(manifest)
        touch_dirty(dirty_path)
        log.info("Updated %s (content changed)", filename)
    else:
        log.debug("Checked %s (no change)", filename)

    return changed

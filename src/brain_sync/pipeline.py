from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import httpx

from brain_sync.confluence_rest import (
    ConfluenceAuth,
    fetch_comments,
    fetch_page_body,
    fetch_page_version,
    get_confluence_auth,
)
from brain_sync.converter import html_to_markdown
from brain_sync.fileops import content_hash, write_if_changed
from brain_sync.sources import (
    SourceType,
    canonical_filename,
    canonical_id,
    detect_source_type,
    extract_confluence_page_id,
    extract_google_doc_id,
)
from brain_sync.sources.googledocs import googledocs_fetch
from brain_sync.state import SourceState, load_relationships_for_primary

log = logging.getLogger(__name__)


async def _resolve_auto_filename(
    url: str,
    source_type: SourceType,
    auth: ConfluenceAuth | None,
    http_client: httpx.AsyncClient,
) -> str:
    """Derive an ID-anchored filename from the source URL/title."""
    if source_type == SourceType.CONFLUENCE:
        page_id = extract_confluence_page_id(url)
        title = None
        if auth:
            try:
                _, title, _ = await fetch_page_body(page_id, auth, http_client)
            except Exception:
                pass
        return canonical_filename(source_type, page_id, title)

    if source_type == SourceType.GOOGLE_DOCS:
        doc_id = extract_google_doc_id(url)
        return canonical_filename(source_type, doc_id, None)

    return "untitled.md"


def _has_context_flags(ss: SourceState) -> bool:
    return ss.include_links or ss.include_children or ss.include_attachments


async def process_source(
    source_state: SourceState,
    http_client: httpx.AsyncClient,
    root: Path | None = None,
) -> bool:
    """Process a single source. Returns True if content changed."""
    source_type = detect_source_type(source_state.source_url)
    now = datetime.now(UTC).isoformat()
    auth = get_confluence_auth()

    # Determine target directory
    if root is not None and source_state.target_path:
        target_dir = root / "knowledge" / source_state.target_path
    elif root is not None:
        target_dir = root / "knowledge"
    else:
        target_dir = Path(".")
    target_dir.mkdir(parents=True, exist_ok=True)

    # Resolve output filename
    filename = await _resolve_auto_filename(
        source_state.source_url,
        source_type,
        auth,
        http_client,
    )
    target = target_dir / filename

    if source_type == SourceType.CONFLUENCE:
        page_id = extract_confluence_page_id(source_state.source_url)

        # Cheap version check via REST API
        version: str | None = None
        if auth:
            v = await fetch_page_version(page_id, auth, http_client)
            if v is not None:
                version = str(v)
        context_dir = target_dir / "_sync-context"
        context_missing = _has_context_flags(source_state) and not context_dir.exists()
        unchanged = version is not None and version == source_state.metadata_fingerprint
        if unchanged and target.exists() and not context_missing:
            log.debug("Confluence page %s unchanged (version %s)", page_id, version)
            source_state.last_checked_utc = now
            return False

        # Full fetch via REST API
        if not auth:
            log.warning("No Confluence auth configured, skipping %s", source_state.source_url)
            return False

        html, title, v = await fetch_page_body(page_id, auth, http_client)
        if v is not None:
            version = str(v)

        comments_md = await fetch_comments(page_id, auth, http_client)
        if version is not None:
            source_state.metadata_fingerprint = version

        # Context discovery & sync
        if _has_context_flags(source_state) and root is not None:
            primary_cid = canonical_id(source_type, source_state.source_url)
            if auth:
                try:
                    from brain_sync.context import process_context

                    await process_context(
                        manifest_dir=target_dir,
                        entry_url=source_state.source_url,
                        primary_html=html,
                        primary_canonical_id=primary_cid,
                        auth=auth,
                        client=http_client,
                        root=root,
                        include_links=source_state.include_links,
                        include_children=source_state.include_children,
                        include_attachments=source_state.include_attachments,
                    )
                except Exception as e:
                    log.warning("Context processing failed for %s: %s", source_state.source_url, e)
            else:
                log.warning("Context flags enabled but no REST auth, skipping context for %s", source_state.source_url)

            # Link rewriting
            try:
                rels = load_relationships_for_primary(root, primary_cid)
            except Exception as e:
                log.debug("Link map build failed: %s", e)
                rels = []
        else:
            rels = []

    elif source_type == SourceType.GOOGLE_DOCS:
        doc_id = extract_google_doc_id(source_state.source_url)
        html = await googledocs_fetch(doc_id, http_client)
        comments_md = None
        rels = []
    else:
        log.warning("Unsupported source type for %s", source_state.source_url)
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
        log.info("Updated %s (content changed)", filename)
    else:
        log.debug("Checked %s (no change)", filename)

    return changed

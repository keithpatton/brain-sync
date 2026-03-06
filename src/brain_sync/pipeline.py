from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from brain_sync.converter import html_to_markdown
from brain_sync.fileops import content_hash, resolve_dirty_path, touch_dirty, write_if_changed
from brain_sync.manifest import Manifest, SourceEntry
from brain_sync.sources import (
    SourceType,
    detect_source_type,
    extract_confluence_page_id,
    extract_google_doc_id,
)
from brain_sync.sources.confluence import confluence_comments, confluence_fetch, confluence_metadata
from brain_sync.sources.googledocs import googledocs_fetch
from brain_sync.state import SourceState

log = logging.getLogger(__name__)


async def process_source(
    manifest: Manifest,
    entry: SourceEntry,
    source_state: SourceState,
    http_client: httpx.AsyncClient,
) -> bool:
    """Process a single source. Returns True if content changed."""
    source_type = detect_source_type(entry.url)
    now = datetime.now(timezone.utc).isoformat()
    target = manifest.path.parent / entry.file

    if source_type == SourceType.CONFLUENCE:
        page_id = extract_confluence_page_id(entry.url)

        # Cheap metadata check
        version = await confluence_metadata(page_id)
        if version is not None and version == source_state.metadata_fingerprint:
            log.debug("Confluence page %s unchanged (version %s)", page_id, version)
            source_state.last_checked_utc = now
            return False

        html = await confluence_fetch(page_id)
        comments_md = await confluence_comments(page_id)
        if version is not None:
            source_state.metadata_fingerprint = version

    elif source_type == SourceType.GOOGLE_DOCS:
        doc_id = extract_google_doc_id(entry.url)
        html = await googledocs_fetch(doc_id, http_client)
    else:
        log.warning("Unsupported source type for %s", entry.url)
        return False

    markdown = html_to_markdown(html)

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
        log.info("Updated %s (content changed)", entry.file)
    else:
        log.debug("Checked %s (no change)", entry.file)

    return changed

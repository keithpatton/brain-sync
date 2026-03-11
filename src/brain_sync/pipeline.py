from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

from brain_sync.converter import format_comments
from brain_sync.fileops import content_hash, write_if_changed
from brain_sync.sources import (
    canonical_filename,
    canonical_id,
    detect_source_type,
    extract_id,
)
from brain_sync.sources.base import UpdateCheckResult, UpdateStatus
from brain_sync.sources.registry import get_adapter
from brain_sync.state import SourceState, load_relationships_for_primary

log = logging.getLogger(__name__)


def _has_context_flags(ss: SourceState) -> bool:
    return ss.include_links or ss.include_children or ss.include_attachments


def _resolve_target_dir(root: Path | None, source_state: SourceState) -> Path:
    if root is not None and source_state.target_path:
        return root / "knowledge" / source_state.target_path
    elif root is not None:
        return root / "knowledge"
    return Path(".")


async def process_source(
    source_state: SourceState,
    http_client: httpx.AsyncClient,
    root: Path | None = None,
) -> bool:
    """Process a single source. Returns True if content changed."""
    source_type = detect_source_type(source_state.source_url)
    adapter = get_adapter(source_type)
    caps = adapter.capabilities
    now = datetime.now(UTC).isoformat()

    # Auth
    auth = adapter.auth_provider.load_auth()
    if auth is None:
        log.warning("No auth for %s, skipping %s", source_type.value, source_state.source_url)
        return False

    # Target directory
    target_dir = _resolve_target_dir(root, source_state)
    target_dir.mkdir(parents=True, exist_ok=True)

    # Version check
    check: UpdateCheckResult | None = None
    if caps.supports_version_check:
        check = await adapter.check_for_update(source_state, auth, http_client)

    # Resolve filename (title may come from check or fetch)
    doc_id = extract_id(source_type, source_state.source_url)
    title = check.title if check else None
    filename = canonical_filename(source_type, doc_id, title)
    target = target_dir / filename

    # Skip if unchanged
    context_dir = target_dir / "_sync-context"
    context_missing = _has_context_flags(source_state) and not context_dir.exists()
    if check and check.status == UpdateStatus.UNCHANGED and target.exists() and not context_missing:
        log.debug("Source %s unchanged (fingerprint %s)", doc_id, check.fingerprint)
        source_state.last_checked_utc = now
        return False

    # Full fetch
    prior_adapter_state = check.adapter_state if check else None
    result = await adapter.fetch(source_state, auth, http_client, root, prior_adapter_state)

    # Re-resolve filename with title from fetch
    if result.title and result.title != title:
        title = result.title
        new_filename = canonical_filename(source_type, doc_id, title)
        if new_filename != filename:
            target = target_dir / new_filename
            filename = new_filename

    # Context sync (capability-gated, stays in pipeline)
    rels = []
    att_title_to_path: dict[str, str] = {}
    if caps.supports_context_sync and _has_context_flags(source_state) and root is not None and result.source_html:
        primary_cid = canonical_id(source_type, source_state.source_url)
        try:
            from brain_sync.context import process_context

            att_title_to_path = await process_context(
                manifest_dir=target_dir,
                entry_url=source_state.source_url,
                primary_html=result.source_html,
                primary_canonical_id=primary_cid,
                auth=auth,  # pyright: ignore[reportArgumentType]
                client=http_client,
                root=root,
                include_links=source_state.include_links,
                include_children=source_state.include_children,
                include_attachments=source_state.include_attachments,
            )
        except Exception as e:
            log.warning("Context processing failed for %s: %s", source_state.source_url, e)

        try:
            rels = load_relationships_for_primary(root, primary_cid)
        except Exception as e:
            log.debug("Link map build failed: %s", e)

    # Link rewriting
    markdown = result.body_markdown
    if rels:
        from brain_sync.link_rewriter import rewrite_links

        cid_to_path = {r.canonical_id: f"./{r.local_path}" for r in rels}
        markdown = rewrite_links(markdown, cid_to_path)

    # Resolve inline attachment image refs (attachment-ref:title → local path)
    if att_title_to_path:

        def _resolve_att(m: re.Match[str]) -> str:
            title = m.group(2)
            path = att_title_to_path.get(title)
            return f"[{m.group(1)}](./{path})" if path else m.group(0)

        markdown = re.sub(r"\[([^\]]*)\]\(attachment-ref:([^)]+)\)", _resolve_att, markdown)

    # Comments (generic, capability-gated)
    if caps.supports_comments and result.comments:
        comments_md = format_comments(result.comments)
        markdown = markdown.rstrip("\n") + "\n\n---\n\n## Comments\n\n" + comments_md + "\n"

    # Write + state update
    changed = write_if_changed(target, markdown)

    source_state.last_checked_utc = now
    source_state.content_hash = content_hash(markdown.encode("utf-8"))
    source_state.source_type = source_type.value
    if result.metadata_fingerprint:
        source_state.metadata_fingerprint = result.metadata_fingerprint

    if changed:
        source_state.last_changed_utc = now
        log.info("Updated %s (content changed)", filename)
    else:
        log.debug("Checked %s (no change)", filename)

    return changed

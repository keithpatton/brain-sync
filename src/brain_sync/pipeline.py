from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from brain_sync.converter import format_comments
from brain_sync.fileops import content_hash, rediscover_local_path, write_if_changed
from brain_sync.sources import (
    canonical_filename,
    canonical_id,
    detect_source_type,
    extract_id,
)
from brain_sync.sources.base import UpdateCheckResult, UpdateStatus
from brain_sync.sources.registry import get_adapter
from brain_sync.state import SourceState

log = logging.getLogger(__name__)


@dataclass
class ChildDiscoveryResult:
    """A child page discovered during sync, to be added as a primary source."""

    canonical_id: str
    url: str
    title: str | None


def _has_context_flags(ss: SourceState) -> bool:
    return ss.include_attachments


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
) -> tuple[bool, list[ChildDiscoveryResult]]:
    """Process a single source. Returns (content_changed, discovered_children)."""
    source_type = detect_source_type(source_state.source_url)
    adapter = get_adapter(source_type)
    caps = adapter.capabilities
    now = datetime.now(UTC).isoformat()
    discovered_children: list[ChildDiscoveryResult] = []

    # Auth
    auth = adapter.auth_provider.load_auth()
    if auth is None:
        log.warning("No auth for %s, skipping %s", source_type.value, source_state.source_url)
        return False, []

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
    attachments_dir = target_dir / "_attachments"
    context_missing = _has_context_flags(source_state) and not attachments_dir.exists()
    if root is not None:
        existing_file = rediscover_local_path(root, source_state.canonical_id)
    else:
        existing_file = target if target.exists() else None
    if check:
        log.debug(
            "Version check for %s: status=%s, fingerprint=%s, stored=%s, target=%s, found=%s",
            doc_id,
            check.status.name,
            check.fingerprint,
            source_state.metadata_fingerprint,
            target,
            existing_file,
        )
    if check and check.status == UpdateStatus.UNCHANGED and existing_file is not None and not context_missing:
        log.debug("Source %s unchanged (fingerprint %s)", doc_id, check.fingerprint)
        source_state.last_checked_utc = now
        return False, []

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

    # Child discovery (one-shot flag, capability-gated)
    if source_state.include_children and caps.supports_children and root is not None:
        primary_cid = canonical_id(source_type, source_state.source_url)
        try:
            from brain_sync.attachments import discover_children

            page_id = primary_cid.split(":", 1)[1]
            children = await discover_children(page_id, auth, http_client)  # pyright: ignore[reportArgumentType]
            for child in children:
                discovered_children.append(
                    ChildDiscoveryResult(
                        canonical_id=child.canonical_id,
                        url=child.url,
                        title=child.title,
                    )
                )
        except Exception as e:
            log.warning("Child discovery failed for %s: %s", source_state.source_url, e)

    # Attachment sync (capability-gated)
    att_title_to_path: dict[str, str] = {}
    if caps.supports_attachments and source_state.include_attachments and root is not None:
        primary_cid = canonical_id(source_type, source_state.source_url)
        try:
            from brain_sync.attachments import process_attachments

            att_title_to_path = await process_attachments(
                target_dir=target_dir,
                primary_canonical_id=primary_cid,
                auth=auth,  # pyright: ignore[reportArgumentType]
                client=http_client,
                root=root,
                include_attachments=source_state.include_attachments,
            )
        except Exception as e:
            log.warning("Attachment processing failed for %s: %s", source_state.source_url, e)

    # Resolve inline attachment image refs (attachment-ref:title → local path)
    markdown = result.body_markdown
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
        log.info("Fetched %s (no content change)", filename)

    return changed, discovered_children

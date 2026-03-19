"""Source sync materialization workflow.

This module orchestrates fetch-time work for one source:
- resolve adapter and auth
- fetch source content and related attachment/context data
- assemble the final markdown payload
- hand durable brain writes off to ``BrainRepository`` when running against a
  real brain root

It is intentionally a workflow layer, not a persistence boundary. Portable
brain writes belong in ``brain_repository.py``; this module prepares content
and delegates those writes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx

from brain_sync.brain.fileops import content_hash, path_exists, rediscover_local_path, write_if_changed
from brain_sync.brain.layout import ATTACHMENTS_DIRNAME, MANAGED_DIRNAME
from brain_sync.brain.managed_markdown import extract_source_id, prepend_managed_header, strip_managed_header
from brain_sync.brain.repository import BrainRepository
from brain_sync.sources import (
    canonical_filename,
    canonical_id,
    detect_source_type,
    extract_id,
)
from brain_sync.sources.base import SourceStateLike, UpdateCheckResult, UpdateStatus
from brain_sync.sources.conversion import format_comments
from brain_sync.sources.registry import get_adapter

__all__ = [
    "ChildDiscoveryResult",
    "extract_source_id",
    "prepend_managed_header",
    "process_source",
    "strip_managed_header",
]

log = logging.getLogger(__name__)


@dataclass
class ChildDiscoveryResult:
    """A child page discovered during sync, to be added as a primary source."""

    canonical_id: str
    url: str
    title: str | None


def _has_context_flags(ss: SourceStateLike) -> bool:
    return ss.sync_attachments


def _resolve_target_dir(root: Path | None, source_state: SourceStateLike) -> Path:
    if root is not None and source_state.target_path:
        return root / "knowledge" / source_state.target_path
    elif root is not None:
        return root / "knowledge"
    return Path(".")


async def process_source(
    source_state: SourceStateLike,
    http_client: httpx.AsyncClient,
    root: Path | None = None,
    *,
    fetch_children: bool = False,
) -> tuple[bool, list[ChildDiscoveryResult]]:
    """Fetch, assemble, and materialize one source.

    Returns ``(content_changed, discovered_children)``.
    """
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
    repository = BrainRepository(root) if root is not None else None
    target_dir = (
        repository.ensure_knowledge_dir(source_state.target_path)
        if repository is not None
        else _resolve_target_dir(root, source_state)
    )

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
    attachments_dir = target_dir / MANAGED_DIRNAME / ATTACHMENTS_DIRNAME
    context_missing = _has_context_flags(source_state) and not path_exists(attachments_dir)
    if root is not None:
        existing_file = rediscover_local_path(root / "knowledge", source_state.canonical_id)
    else:
        existing_file = target if path_exists(target) else None
    if check:
        log.debug(
            "Version check for %s: status=%s, fingerprint=%s, stored=%s, target=%s, found=%s",
            doc_id,
            check.status.name,
            check.fingerprint,
            source_state.remote_fingerprint,
            target,
            existing_file,
        )
    if (
        check
        and check.status == UpdateStatus.UNCHANGED
        and existing_file is not None
        and not context_missing
        and source_state.knowledge_state == "materialized"
    ):
        log.debug("Source %s unchanged (fingerprint %s)", doc_id, check.fingerprint)
        source_state.last_checked_utc = now
        return False, []

    # Defensive guard: if adapter reports UNCHANGED but the local file
    # does not exist (e.g. test adapter or corrupted state), skip fetch.
    # Real adapters return CHANGED on first sync (metadata_fingerprint starts None).
    if (
        check
        and check.status == UpdateStatus.UNCHANGED
        and existing_file is None
        and source_state.knowledge_state == "materialized"
    ):
        log.debug("Source %s unchanged and no local file, skipping", doc_id)
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
    if fetch_children and caps.supports_children and root is not None:
        primary_cid = canonical_id(source_type, source_state.source_url)
        try:
            from brain_sync.sources.confluence.attachments import discover_children

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
    #
    # Google Docs uses inline image discovery in fetch(); it does not support
    # the Confluence-style attachment listing flow in attachments.process_attachments().
    # Restrict that branch to Confluence sources so a Google auth object is never
    # passed into the Confluence attachment client.
    att_title_to_path: dict[str, str] = {}
    if (
        source_type.value == "confluence"
        and caps.supports_attachments
        and source_state.sync_attachments
        and root is not None
        and not result.inline_images
    ):
        primary_cid = canonical_id(source_type, source_state.source_url)
        try:
            from brain_sync.sources.confluence.attachments import process_attachments

            att_title_to_path = await process_attachments(
                target_dir=target_dir,
                primary_canonical_id=primary_cid,
                auth=auth,  # pyright: ignore[reportArgumentType]
                client=http_client,
                root=root,
                sync_attachments=source_state.sync_attachments,
            )
        except Exception as e:
            log.warning("Attachment processing failed for %s: %s", source_state.source_url, e)

    # Process inline images from adapter (source-agnostic)
    if result.inline_images and source_state.sync_attachments and root is not None:
        try:
            from brain_sync.sync.attachments import process_inline_images

            inline_paths = await process_inline_images(
                images=result.inline_images,
                headers=result.download_headers,
                client=http_client,
                target_dir=target_dir,
                primary_canonical_id=result.attachment_parent_id or canonical_id(source_type, source_state.source_url),
                root=root,
            )
            att_title_to_path.update(inline_paths)
        except Exception as e:
            log.warning("Inline image processing failed for %s: %s", source_state.source_url, e)

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

    # Compute content hash from body (excluding managed header) so the hash
    # stays stable across header updates and matches sync_hint semantics.
    body_hash = content_hash(markdown.encode("utf-8"))
    remote_fingerprint = (
        result.remote_fingerprint or (check.fingerprint if check else None) or source_state.remote_fingerprint
    )
    if remote_fingerprint is None:
        raise RuntimeError(f"Adapter did not provide remote_fingerprint for {source_state.canonical_id}")

    source_state.last_checked_utc = now
    source_state.content_hash = body_hash
    source_state.source_type = source_type.value
    source_state.remote_fingerprint = remote_fingerprint

    # The pipeline owns fetch/assembly. Once we have the final markdown body,
    # normal runtime portable writes cross the repository boundary here.
    changed = False
    if repository is not None:
        materialization = repository.materialize_markdown(
            knowledge_path=source_state.target_path,
            filename=filename,
            canonical_id=source_state.canonical_id,
            markdown=markdown,
            source_type=source_state.source_type,
            source_url=source_state.source_url,
            content_hash=body_hash,
            remote_fingerprint=remote_fingerprint,
            materialized_utc=now,
        )
        changed = materialization.changed
        target = repository.knowledge_root / materialization.materialized_path
        source_state.knowledge_path = materialization.materialized_path
        source_state.knowledge_state = "materialized"
        source_state.materialized_utc = now
        source_state.missing_since_utc = None
        for stale_name in materialization.duplicate_files_removed:
            log.warning(
                "Removed duplicate managed file for %s: %s",
                source_state.canonical_id,
                stale_name,
            )
    else:
        # Rootless fallback is kept for narrow non-runtime/test-style usage.
        markdown = prepend_managed_header(
            source_state.canonical_id,
            markdown,
            source_type=source_state.source_type,
            source_url=source_state.source_url,
        )
        changed = write_if_changed(target, markdown)

    if changed:
        source_state.materialized_utc = now
        log.info("Updated %s (content changed)", filename)
    else:
        log.info("Fetched %s (no content change)", filename)

    return changed, discovered_children

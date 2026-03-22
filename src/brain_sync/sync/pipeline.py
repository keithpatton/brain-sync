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

from brain_sync.brain.fileops import content_hash, path_exists, read_text, rediscover_local_path
from brain_sync.brain.layout import ATTACHMENTS_DIRNAME, MANAGED_DIRNAME
from brain_sync.brain.managed_markdown import extract_source_id, prepend_managed_header, strip_managed_header
from brain_sync.sources import (
    canonical_filename,
    canonical_id,
    detect_source_type,
    extract_id,
)
from brain_sync.sources.base import SourceStateLike, UpdateCheckResult, UpdateStatus
from brain_sync.sources.conversion import format_comments
from brain_sync.sources.registry import get_adapter
from brain_sync.sync.attachments import StagedManagedArtifact

__all__ = [
    "ChildDiscoveryResult",
    "PreparedSourceSync",
    "extract_source_id",
    "prepare_source_sync",
    "prepend_managed_header",
    "process_source",
    "strip_managed_header",
]

log = logging.getLogger(__name__)
_ATTACHMENT_CONTEXT_REF_RE = re.compile(
    rf"\]\((?:\./)?{re.escape(MANAGED_DIRNAME)}/{re.escape(ATTACHMENTS_DIRNAME)}/|\]\(attachment-ref:"
)


class SourceLifecycleLeaseConflictError(RuntimeError):
    """Raised when another lifecycle operation currently owns the source lease."""

    def __init__(self, canonical_id: str, lease_owner: str | None):
        self.canonical_id = canonical_id
        self.lease_owner = lease_owner
        super().__init__(f"Lifecycle lease conflict for {canonical_id}: {lease_owner or 'unknown'}")


@dataclass
class ChildDiscoveryResult:
    """A child page discovered during sync, to be added as a primary source."""

    canonical_id: str
    url: str
    title: str | None


@dataclass
class PreparedSourceSync:
    canonical_id: str
    source_url: str
    source_type: str
    target_path: str
    filename: str
    markdown: str
    content_hash: str
    remote_fingerprint: str
    checked_utc: str
    discovered_children: list[ChildDiscoveryResult]
    staged_managed_artifacts: tuple[StagedManagedArtifact, ...] = ()
    skip_materialization: bool = False


def _has_context_flags(ss: SourceStateLike) -> bool:
    return ss.sync_attachments


def _references_attachment_context(existing_file: Path | None) -> bool:
    if existing_file is None:
        return False
    try:
        return _ATTACHMENT_CONTEXT_REF_RE.search(read_text(existing_file)) is not None
    except OSError:
        log.debug("Failed to inspect attachment refs for %s", existing_file, exc_info=True)
        return True


def _resolve_target_dir(root: Path | None, source_state: SourceStateLike) -> Path:
    if root is not None and source_state.target_path:
        return root / "knowledge" / source_state.target_path
    elif root is not None:
        return root / "knowledge"
    return Path(".")


async def prepare_source_sync(
    source_state: SourceStateLike,
    http_client: httpx.AsyncClient,
    root: Path | None = None,
    *,
    fetch_children: bool = False,
) -> PreparedSourceSync:
    """Fetch and assemble one source for lifecycle-owned materialization."""
    source_type = detect_source_type(source_state.source_url)
    adapter = get_adapter(source_type)
    caps = adapter.capabilities
    now = datetime.now(UTC).isoformat()
    discovered_children: list[ChildDiscoveryResult] = []
    staged_managed_artifacts: list[StagedManagedArtifact] = []

    # Auth
    auth = adapter.auth_provider.load_auth()
    if auth is None:
        log.warning("No auth for %s, skipping %s", source_type.value, source_state.source_url)
        return PreparedSourceSync(
            canonical_id=source_state.canonical_id,
            source_url=source_state.source_url,
            source_type=source_type.value,
            target_path=source_state.target_path,
            filename=canonical_filename(source_type, extract_id(source_type, source_state.source_url), None),
            markdown="",
            content_hash=source_state.content_hash or "",
            remote_fingerprint=source_state.remote_fingerprint or "",
            checked_utc=now,
            discovered_children=[],
            skip_materialization=True,
        )

    # Target directory
    target_dir = _resolve_target_dir(root, source_state)

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
    if root is not None:
        existing_file = rediscover_local_path(root / "knowledge", source_state.canonical_id)
    else:
        existing_file = target if path_exists(target) else None
    attachments_dir = target_dir / MANAGED_DIRNAME / ATTACHMENTS_DIRNAME
    context_missing = (
        _has_context_flags(source_state)
        and _references_attachment_context(existing_file)
        and not path_exists(attachments_dir)
    )
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
        return PreparedSourceSync(
            canonical_id=source_state.canonical_id,
            source_url=source_state.source_url,
            source_type=source_type.value,
            target_path=source_state.target_path,
            filename=filename,
            markdown="",
            content_hash=source_state.content_hash or "",
            remote_fingerprint=source_state.remote_fingerprint or check.fingerprint or "",
            checked_utc=now,
            discovered_children=[],
            skip_materialization=True,
        )

    # Defensive guard: if an adapter reports UNCHANGED but we have no local
    # materialized file, do not synthesize content from a fetch path that the
    # adapter did not intend to use for this revision state.
    if (
        check
        and check.status == UpdateStatus.UNCHANGED
        and existing_file is None
        and source_state.knowledge_state != "stale"
    ):
        log.debug("Source %s unchanged and no local file, skipping", doc_id)
        source_state.last_checked_utc = now
        return PreparedSourceSync(
            canonical_id=source_state.canonical_id,
            source_url=source_state.source_url,
            source_type=source_type.value,
            target_path=source_state.target_path,
            filename=filename,
            markdown="",
            content_hash=source_state.content_hash or "",
            remote_fingerprint=source_state.remote_fingerprint or check.fingerprint or "",
            checked_utc=now,
            discovered_children=[],
            skip_materialization=True,
        )

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

            att_title_to_path, staged_artifacts = await process_attachments(
                target_dir=target_dir,
                primary_canonical_id=primary_cid,
                auth=auth,  # pyright: ignore[reportArgumentType]
                client=http_client,
                root=root,
                sync_attachments=source_state.sync_attachments,
            )
            staged_managed_artifacts.extend(staged_artifacts)
        except Exception as e:
            log.warning("Attachment processing failed for %s: %s", source_state.source_url, e)

    # Process inline images from adapter (source-agnostic)
    if result.inline_images and source_state.sync_attachments and root is not None:
        try:
            from brain_sync.sync.attachments import process_inline_images

            inline_paths, inline_artifacts = await process_inline_images(
                images=result.inline_images,
                headers=result.download_headers,
                client=http_client,
                target_dir=target_dir,
                primary_canonical_id=result.attachment_parent_id or canonical_id(source_type, source_state.source_url),
                root=root,
            )
            att_title_to_path.update(inline_paths)
            staged_managed_artifacts.extend(inline_artifacts)
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
    return PreparedSourceSync(
        canonical_id=source_state.canonical_id,
        source_url=source_state.source_url,
        source_type=source_state.source_type,
        target_path=source_state.target_path,
        filename=filename,
        markdown=markdown,
        content_hash=body_hash,
        remote_fingerprint=remote_fingerprint,
        checked_utc=now,
        discovered_children=discovered_children,
        staged_managed_artifacts=tuple(staged_managed_artifacts),
    )


async def process_source(
    source_state: SourceStateLike,
    http_client: httpx.AsyncClient,
    root: Path | None = None,
    *,
    fetch_children: bool = False,
    lifecycle_owner_id: str | None = None,
) -> tuple[bool, list[ChildDiscoveryResult]]:
    """Compatibility wrapper that routes registered-source writes via lifecycle."""
    from brain_sync.sync.lifecycle import process_prepared_source
    from brain_sync.sync.source_state import SourceState

    original_source_state = source_state
    caller_supplied_owner_id = lifecycle_owner_id is not None
    effective_owner_id = lifecycle_owner_id
    if root is not None and effective_owner_id is None:
        import os
        import uuid

        effective_owner_id = f"materialize:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    lease_acquired = False
    try:
        if root is not None and effective_owner_id is not None:
            from datetime import timedelta

            from brain_sync.runtime.repository import acquire_source_lifecycle_lease
            from brain_sync.sync.source_state import load_active_sync_state

            lease_expires_utc = (datetime.now(UTC) + timedelta(seconds=30)).isoformat()
            acquired, existing = acquire_source_lifecycle_lease(
                root,
                source_state.canonical_id,
                effective_owner_id,
                lease_expires_utc=lease_expires_utc,
            )
            if not acquired:
                raise SourceLifecycleLeaseConflictError(
                    canonical_id=source_state.canonical_id,
                    lease_owner=existing.lease_owner if existing is not None else None,
                )
            lease_acquired = True
            refreshed = load_active_sync_state(root).sources.get(source_state.canonical_id)
            if refreshed is None and caller_supplied_owner_id:
                return False, []
            if refreshed is not None:
                # Keep legacy root-backed callers working by preserving the
                # mutable instance they passed in, while still revalidating
                # from manifest-authoritative active state before processing.
                if isinstance(original_source_state, SourceState) and not caller_supplied_owner_id:
                    original_source_state.source_url = refreshed.source_url
                    original_source_state.source_type = refreshed.source_type
                    original_source_state.knowledge_path = refreshed.knowledge_path
                    original_source_state.knowledge_state = refreshed.knowledge_state
                    original_source_state.sync_attachments = refreshed.sync_attachments
                    original_source_state.content_hash = refreshed.content_hash
                    original_source_state.remote_fingerprint = refreshed.remote_fingerprint
                    original_source_state.materialized_utc = refreshed.materialized_utc
                    original_source_state.last_checked_utc = refreshed.last_checked_utc
                    original_source_state.current_interval_secs = refreshed.current_interval_secs
                    original_source_state.next_check_utc = refreshed.next_check_utc
                    original_source_state.interval_seconds = refreshed.interval_seconds
                    source_state = original_source_state
                else:
                    source_state = refreshed

        prepared = await prepare_source_sync(
            source_state,
            http_client,
            root=root,
            fetch_children=fetch_children,
        )
        if root is None:
            return False, prepared.discovered_children

        if not isinstance(source_state, SourceState):
            raise TypeError("root-backed source processing requires a mutable SourceState instance")
        result = process_prepared_source(
            root,
            source_state,
            prepared,
            lifecycle_owner_id=effective_owner_id,
        )
        return result.changed, result.discovered_children
    finally:
        if root is not None and effective_owner_id is not None and lease_acquired:
            from brain_sync.runtime.repository import clear_source_lifecycle_lease

            clear_source_lifecycle_lease(root, source_state.canonical_id, owner_id=effective_owner_id)

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
import yaml

from brain_sync.converter import format_comments
from brain_sync.fileops import (
    content_hash,
    glob_paths,
    path_exists,
    path_is_dir,
    read_bytes,
    rediscover_local_path,
    write_if_changed,
)
from brain_sync.fs_utils import normalize_path
from brain_sync.layout import ATTACHMENTS_DIRNAME, MANAGED_DIRNAME
from brain_sync.sources import (
    canonical_filename,
    canonical_id,
    detect_source_type,
    extract_id,
    to_durable_source_type,
)
from brain_sync.sources.base import UpdateCheckResult, UpdateStatus
from brain_sync.sources.registry import get_adapter
from brain_sync.state import SourceState

log = logging.getLogger(__name__)

# Managed-file identity header lines (embedded in synced markdown files).
MANAGED_HEADER_SOURCE = "<!-- brain-sync-source: {} -->"
MANAGED_HEADER_WARNING = "<!-- brain-sync-managed: local edits may be overwritten -->"

# Regex to detect/strip existing managed headers (for idempotent rewrites).
_MANAGED_HEADER_RE = re.compile(r"^<!-- brain-sync-(source|managed): .* -->\n", re.MULTILINE)

# Regex to extract canonical_id from the identity header (tier-2 resolution).
_EXTRACT_SOURCE_RE = re.compile(r"^<!-- brain-sync-source: (.+) -->\r?$", re.MULTILINE)
_FRONTMATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)
_MANAGED_FRONTMATTER_KEYS = (
    "brain_sync_source",
    "brain_sync_canonical_id",
    "brain_sync_source_url",
)


def _split_frontmatter(text: str) -> tuple[dict[str, object], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    raw = match.group(1)
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(data, dict):
        return {}, text
    return dict(data), text[match.end() :]


def _render_frontmatter(data: dict[str, object], body: str) -> str:
    if not data:
        return body.lstrip("\n")
    rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=False).strip()
    body = body.lstrip("\n")
    if body:
        return f"---\n{rendered}\n---\n\n{body}"
    return f"---\n{rendered}\n---\n"


def _canonical_source_type_for_frontmatter(source_type: str | None, canonical_id_str: str) -> str:
    if source_type:
        return to_durable_source_type(source_type)
    if canonical_id_str.startswith("gdoc:"):
        return "google_doc"
    return canonical_id_str.split(":", 1)[0]


def extract_source_id(path: Path) -> str | None:
    """Extract canonical_id from a file's embedded identity header (tier-2 resolution)."""
    try:
        head = read_bytes(path)[:4096].decode("utf-8", errors="replace")
        frontmatter, _ = _split_frontmatter(head)
        frontmatter_cid = frontmatter.get("brain_sync_canonical_id")
        if isinstance(frontmatter_cid, str):
            return frontmatter_cid
        m = _EXTRACT_SOURCE_RE.search(head)
        return m.group(1) if m else None
    except OSError:
        return None


def _find_identity_matches_in_dir(target_dir: Path, canonical_id_str: str) -> list[Path]:
    """Return managed markdown files in a directory that claim the same canonical id."""
    if not path_is_dir(target_dir):
        return []
    matches: list[Path] = []
    for path in glob_paths(target_dir, "*.md"):
        if extract_source_id(path) == canonical_id_str:
            matches.append(path)
    return matches


def strip_managed_header(text: str) -> str:
    """Remove managed identity from YAML frontmatter and legacy HTML comments."""
    frontmatter, body = _split_frontmatter(text)
    if frontmatter:
        for key in _MANAGED_FRONTMATTER_KEYS:
            frontmatter.pop(key, None)
        text = _render_frontmatter(frontmatter, body)
    return _MANAGED_HEADER_RE.sub("", text).lstrip("\n")


def prepend_managed_header(
    canonical_id_str: str,
    markdown: str,
    *,
    source_type: str | None = None,
    source_url: str | None = None,
) -> str:
    """Write spec-aligned managed identity frontmatter, preserving user keys."""
    frontmatter, body = _split_frontmatter(markdown)
    body = _MANAGED_HEADER_RE.sub("", body).lstrip("\n")
    frontmatter["brain_sync_source"] = _canonical_source_type_for_frontmatter(source_type, canonical_id_str)
    frontmatter["brain_sync_canonical_id"] = canonical_id_str
    if source_url is not None:
        frontmatter["brain_sync_source_url"] = source_url
    return _render_frontmatter(frontmatter, body)


@dataclass
class ChildDiscoveryResult:
    """A child page discovered during sync, to be added as a primary source."""

    canonical_id: str
    url: str
    title: str | None


def _has_context_flags(ss: SourceState) -> bool:
    return ss.sync_attachments


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
            source_state.metadata_fingerprint,
            target,
            existing_file,
        )
    if check and check.status == UpdateStatus.UNCHANGED and existing_file is not None and not context_missing:
        log.debug("Source %s unchanged (fingerprint %s)", doc_id, check.fingerprint)
        source_state.last_checked_utc = now
        return False, []

    # Defensive guard: if adapter reports UNCHANGED but the local file
    # does not exist (e.g. test adapter or corrupted state), skip fetch.
    # Real adapters return CHANGED on first sync (metadata_fingerprint starts None).
    if check and check.status == UpdateStatus.UNCHANGED and existing_file is None:
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
    if source_state.fetch_children and caps.supports_children and root is not None:
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
            from brain_sync.attachments import process_attachments

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
            from brain_sync.attachments import process_inline_images

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

    # Prepend managed-file identity header
    markdown = prepend_managed_header(
        source_state.canonical_id,
        markdown,
        source_type=source_state.source_type,
        source_url=source_state.source_url,
    )

    # Write + state update
    changed = write_if_changed(target, markdown)

    # Heal duplicate managed files after title-driven filename changes.
    # There should only ever be one markdown file per canonical source id
    # within a knowledge area.
    if root is not None:
        identity_matches = _find_identity_matches_in_dir(target_dir, source_state.canonical_id)
        stale_matches = [path for path in identity_matches if path != target]
        for stale_path in stale_matches:
            try:
                stale_path.unlink()
                log.warning(
                    "Removed duplicate managed file for %s: %s",
                    source_state.canonical_id,
                    stale_path.name,
                )
            except OSError:
                log.warning(
                    "Failed to remove duplicate managed file for %s: %s",
                    source_state.canonical_id,
                    stale_path,
                    exc_info=True,
                )

    source_state.last_checked_utc = now
    source_state.content_hash = body_hash
    source_state.source_type = source_type.value
    if result.metadata_fingerprint:
        source_state.metadata_fingerprint = result.metadata_fingerprint

    if changed:
        source_state.last_changed_utc = now
        log.info("Updated %s (content changed)", filename)
    else:
        log.info("Fetched %s (no content change)", filename)

    # Phase 1: update manifest sync_hint and materialized_path after successful sync
    if root is not None:
        try:
            from brain_sync.manifest import update_manifest_materialized_path, update_manifest_sync_hint

            materialized = normalize_path(target.relative_to(root / "knowledge"))
            update_manifest_materialized_path(root, source_state.canonical_id, materialized)
            update_manifest_sync_hint(root, source_state.canonical_id, body_hash, now)
        except Exception:
            log.debug("Manifest update skipped (manifest may not exist yet)", exc_info=True)

    return changed, discovered_children

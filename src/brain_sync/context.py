from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from urllib.parse import urljoin

import httpx

from brain_sync.confluence_rest import (
    ConfluenceAuth,
    download_attachment,
    fetch_attachments,
    fetch_child_pages,
    fetch_page_body,
    fetch_page_version,
)
from brain_sync.converter import html_to_markdown
from brain_sync.fileops import EXCLUDED_DIRS, atomic_write_bytes, content_hash, rediscover_local_path
from brain_sync.sources import (
    SourceType,
    canonical_filename,
    try_extract_confluence_page_id,
)
from brain_sync.state import (
    DocumentState,
    Relationship,
    count_relationships_for_doc,
    load_document,
    load_relationships_for_primary,
    remove_document_if_orphaned,
    remove_relationship,
    save_document,
    save_relationship,
    update_relationship_path,
)

log = logging.getLogger(__name__)

# Must match the entry in EXCLUDED_DIRS (fileops.py) — this folder is
# excluded from content discovery, regen, and watching.
CONTEXT_DIR = "_sync-context"
assert CONTEXT_DIR in EXCLUDED_DIRS, f"{CONTEXT_DIR!r} missing from EXCLUDED_DIRS"


class RelType(str, Enum):
    PRIMARY = "primary"
    LINK = "link"
    CHILD = "child"
    ATTACHMENT = "attachment"


RELTYPE_FOLDER: dict[RelType, str] = {
    RelType.LINK: "linked",
    RelType.CHILD: "children",
    RelType.ATTACHMENT: "attachments",
}


class SafetyError(Exception):
    pass


@dataclass
class DiscoveredDoc:
    canonical_id: str
    url: str
    title: str | None
    relationship_type: RelType
    version: int | None = None
    media_type: str | None = None


def ensure_context_dirs(manifest_dir: Path) -> Path:
    """Create _sync-context/ and subdirectories. Returns context root."""
    context_root = manifest_dir / CONTEXT_DIR
    for folder in RELTYPE_FOLDER.values():
        (context_root / folder).mkdir(parents=True, exist_ok=True)
    return context_root


def remove_synced_file(path: Path, context_root: Path) -> bool:
    """Safely remove a file, asserting it's within context_root."""
    resolved = path.resolve()
    if not resolved.is_relative_to(context_root.resolve()):
        raise SafetyError(f"Refusing to delete {path}: outside context root {context_root}")
    if resolved.exists():
        resolved.unlink()
        return True
    return False


def _generate_frontmatter(
    canonical_id: str,
    source_url: str,
    relationship: str,
    parent_canonical_id: str,
    synced_at: str,
) -> str:
    return (
        "---\n"
        f"canonical_id: {canonical_id}\n"
        f"source_url: {source_url}\n"
        f"relationship: {relationship}\n"
        f"parent: {parent_canonical_id}\n"
        f"synced_at: {synced_at}\n"
        "---\n\n"
    )


# --- Discovery ---


def discover_links_from_html(html: str, source_domain: str) -> list[DiscoveredDoc]:
    """Extract Confluence page links from HTML body. Zero API calls."""
    from selectolax.parser import HTMLParser

    tree = HTMLParser(html)
    seen: set[str] = set()
    results: list[DiscoveredDoc] = []

    for a_tag in tree.css("a[href]"):
        href = a_tag.attributes.get("href", "")
        if not href or href.startswith("#"):
            continue

        # Normalize relative URLs
        if href.startswith("/"):
            href = f"https://{source_domain}{href}"

        # Only process Confluence URLs
        if "atlassian.net/wiki/" not in href:
            continue

        page_id = try_extract_confluence_page_id(href)
        if page_id is None:
            continue

        cid = f"confluence:{page_id}"
        if cid in seen:
            continue
        seen.add(cid)

        results.append(DiscoveredDoc(
            canonical_id=cid,
            url=href,
            title=None,  # Unknown at discovery time
            relationship_type=RelType.LINK,
        ))

    return results


async def discover_children(
    page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient,
) -> list[DiscoveredDoc]:
    """Discover child pages via REST API."""
    children = await fetch_child_pages(page_id, auth, client)
    return [
        DiscoveredDoc(
            canonical_id=f"confluence:{c['id']}",
            url=f"https://{auth.domain}/wiki/spaces/unknown/pages/{c['id']}",
            title=c.get("title"),
            relationship_type=RelType.CHILD,
            version=c.get("version"),
        )
        for c in children
    ]


async def discover_attachments(
    page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient,
) -> list[DiscoveredDoc]:
    """Discover attachments via REST API."""
    attachments = await fetch_attachments(page_id, auth, client)
    return [
        DiscoveredDoc(
            canonical_id=f"confluence-attachment:{a['id']}",
            url=a.get("download_url", ""),
            title=a.get("title"),
            relationship_type=RelType.ATTACHMENT,
            version=a.get("version"),
            media_type=a.get("media_type"),
        )
        for a in attachments
    ]


# --- Path Rediscovery ---


def rediscover_relationship_paths(
    manifest_dir: Path,
    root: Path,
    relationships: list[Relationship],
) -> list[Relationship]:
    """Check stored local_paths and attempt rediscovery for any missing files.

    Returns the (potentially updated) list of relationships.
    """
    updated: list[Relationship] = []
    for rel in relationships:
        file_path = manifest_dir / rel.local_path
        if file_path.exists():
            updated.append(rel)
            continue

        # File missing — attempt rediscovery
        found = rediscover_local_path(manifest_dir, rel.canonical_id)
        if found is not None:
            try:
                new_local = str(found.relative_to(manifest_dir.resolve()))
                # Normalize to forward slashes for consistency
                new_local = new_local.replace("\\", "/")
            except ValueError:
                # Found file is outside manifest_dir — skip
                updated.append(rel)
                continue

            log.info(
                "Rediscovered %s: %s → %s",
                rel.canonical_id, rel.local_path, new_local,
            )
            update_relationship_path(
                root, rel.parent_canonical_id, rel.canonical_id, new_local,
            )
            updated.append(Relationship(
                parent_canonical_id=rel.parent_canonical_id,
                canonical_id=rel.canonical_id,
                relationship_type=rel.relationship_type,
                local_path=new_local,
                source_type=rel.source_type,
                first_seen_utc=rel.first_seen_utc,
                last_seen_utc=rel.last_seen_utc,
            ))
        else:
            # Not found — keep original record (will be re-synced)
            updated.append(rel)

    return updated


# --- Reconciliation ---


def reconcile(
    discovered: list[DiscoveredDoc],
    existing_rels: list[Relationship],
) -> tuple[list[DiscoveredDoc], list[DiscoveredDoc], set[str]]:
    """Compute diff: (to_add, to_check, to_remove_ids)."""
    discovered_ids = {d.canonical_id for d in discovered}
    existing_ids = {r.canonical_id for r in existing_rels}

    to_add = [d for d in discovered if d.canonical_id not in existing_ids]
    to_check = [d for d in discovered if d.canonical_id in existing_ids]
    to_remove_ids = existing_ids - discovered_ids

    return to_add, to_check, to_remove_ids


def _local_path_for_doc(
    doc: DiscoveredDoc, manifest_dir: Path,
) -> str:
    """Compute the local_path (relative from manifest_dir) for a discovered doc."""
    folder = RELTYPE_FOLDER[doc.relationship_type]
    if doc.relationship_type == RelType.ATTACHMENT:
        att_id = doc.canonical_id.split(":", 1)[1]
        filename = f"a{att_id}-{doc.title}" if doc.title else f"a{att_id}"
    else:
        page_id = doc.canonical_id.split(":", 1)[1]
        filename = canonical_filename(SourceType.CONFLUENCE, page_id, doc.title)
    return f"{CONTEXT_DIR}/{folder}/{filename}"


# --- Sync operations ---


async def _sync_page_doc(
    doc: DiscoveredDoc,
    local_path: str,
    manifest_dir: Path,
    parent_canonical_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
    now: str,
) -> DocumentState:
    """Fetch and write a page context document."""
    page_id = doc.canonical_id.split(":", 1)[1]
    html, title, version = await fetch_page_body(page_id, auth, client)

    # Update title if we got one
    if title and not doc.title:
        doc.title = title

    markdown = html_to_markdown(html)

    # Add frontmatter
    frontmatter = _generate_frontmatter(
        canonical_id=doc.canonical_id,
        source_url=doc.url,
        relationship=doc.relationship_type.value,
        parent_canonical_id=parent_canonical_id,
        synced_at=now,
    )
    content = frontmatter + markdown

    target = manifest_dir / local_path
    atomic_write_bytes(target, content.encode("utf-8"))

    return DocumentState(
        canonical_id=doc.canonical_id,
        source_type="confluence",
        url=doc.url,
        title=doc.title,
        last_checked_utc=now,
        last_changed_utc=now,
        content_hash=content_hash(content.encode("utf-8")),
        metadata_fingerprint=str(version) if version else None,
    )


async def _sync_attachment_doc(
    doc: DiscoveredDoc,
    local_path: str,
    manifest_dir: Path,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
    now: str,
) -> DocumentState:
    """Download and write an attachment."""
    data = await download_attachment(doc.url, auth, client)
    target = manifest_dir / local_path
    atomic_write_bytes(target, data)

    return DocumentState(
        canonical_id=doc.canonical_id,
        source_type="confluence",
        url=doc.url,
        title=doc.title,
        last_checked_utc=now,
        last_changed_utc=now,
        content_hash=content_hash(data),
        metadata_fingerprint=str(doc.version) if doc.version else None,
        mime_type=doc.media_type,
    )


# --- Orchestrator ---


async def process_context(
    manifest_dir: Path,
    entry_url: str,
    primary_html: str,
    primary_canonical_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
    root: Path,
    include_links: bool = False,
    include_children: bool = False,
    include_attachments: bool = False,
) -> None:
    """Run full discovery → reconciliation → sync cycle for context documents.

    Only called for primary sources declared in the manifest.
    """
    from brain_sync.context_index import generate_context_index

    now = datetime.now(timezone.utc).isoformat()
    page_id = primary_canonical_id.split(":", 1)[1]

    # Discover
    discovered: list[DiscoveredDoc] = []
    if include_links:
        discovered.extend(discover_links_from_html(primary_html, auth.domain))
    if include_children:
        discovered.extend(await discover_children(page_id, auth, client))
    if include_attachments:
        discovered.extend(await discover_attachments(page_id, auth, client))

    # Deduplicate by canonical_id
    seen: set[str] = set()
    unique: list[DiscoveredDoc] = []
    for d in discovered:
        if d.canonical_id not in seen and d.canonical_id != primary_canonical_id:
            seen.add(d.canonical_id)
            unique.append(d)
    discovered = unique

    # Rediscover any moved files before reconciliation
    existing_rels = load_relationships_for_primary(root, primary_canonical_id)
    existing_rels = rediscover_relationship_paths(manifest_dir, root, existing_rels)

    # Reconcile
    to_add, to_check, to_remove_ids = reconcile(discovered, existing_rels)

    context_root = ensure_context_dirs(manifest_dir)

    # Sync new docs
    for doc in to_add:
        local_path = _local_path_for_doc(doc, manifest_dir)
        try:
            if doc.relationship_type == RelType.ATTACHMENT:
                doc_state = await _sync_attachment_doc(
                    doc, local_path, manifest_dir, auth, client, now,
                )
            else:
                doc_state = await _sync_page_doc(
                    doc, local_path, manifest_dir, primary_canonical_id,
                    auth, client, now,
                )
                # Update local_path if title was resolved
                local_path = _local_path_for_doc(doc, manifest_dir)

            save_document(root, doc_state)
            save_relationship(root, Relationship(
                parent_canonical_id=primary_canonical_id,
                canonical_id=doc.canonical_id,
                relationship_type=doc.relationship_type.value,
                local_path=local_path,
                source_type="confluence",
                first_seen_utc=now,
                last_seen_utc=now,
            ))
            log.info("Added context doc: %s → %s", doc.canonical_id, local_path)
        except Exception as e:
            log.warning("Failed to sync context doc %s: %s", doc.canonical_id, e)

    # Check existing docs (update last_seen, version-check, re-fetch if changed)
    existing_rel_map = {r.canonical_id: r for r in existing_rels}
    for doc in to_check:
        rel = existing_rel_map[doc.canonical_id]
        try:
            # Update last_seen_utc
            save_relationship(root, Relationship(
                parent_canonical_id=primary_canonical_id,
                canonical_id=doc.canonical_id,
                relationship_type=rel.relationship_type,
                local_path=rel.local_path,
                source_type=rel.source_type,
                first_seen_utc=rel.first_seen_utc,
                last_seen_utc=now,
            ))

            # Version check
            existing_doc = load_document(root, doc.canonical_id)
            if doc.relationship_type == RelType.ATTACHMENT:
                if (existing_doc and existing_doc.metadata_fingerprint
                        and doc.version and str(doc.version) == existing_doc.metadata_fingerprint):
                    continue
                doc_state = await _sync_attachment_doc(
                    doc, rel.local_path, manifest_dir, auth, client, now,
                )
            else:
                page_id_check = doc.canonical_id.split(":", 1)[1]
                version = await fetch_page_version(page_id_check, auth, client)
                if (existing_doc and existing_doc.metadata_fingerprint
                        and version and str(version) == existing_doc.metadata_fingerprint):
                    continue
                doc_state = await _sync_page_doc(
                    doc, rel.local_path, manifest_dir, primary_canonical_id,
                    auth, client, now,
                )

            save_document(root, doc_state)
            log.info("Updated context doc: %s", doc.canonical_id)
        except Exception as e:
            log.warning("Failed to check context doc %s: %s", doc.canonical_id, e)

    # Remove stale docs
    for cid in to_remove_ids:
        rel = existing_rel_map.get(cid)
        if rel:
            # Remove relationship
            remove_relationship(root, primary_canonical_id, cid)

            # Only delete file + document if no other primary references it
            if count_relationships_for_doc(root, cid) == 0:
                file_path = manifest_dir / rel.local_path
                try:
                    remove_synced_file(file_path, context_root)
                except SafetyError as e:
                    log.warning("%s", e)
                remove_document_if_orphaned(root, cid)
                log.info("Removed stale context doc: %s", cid)
            else:
                log.debug("Kept context doc %s (still referenced by other primaries)", cid)

    # Generate context index
    generate_context_index(
        parent_canonical_id=primary_canonical_id,
        manifest_dir=manifest_dir,
        root=root,
    )

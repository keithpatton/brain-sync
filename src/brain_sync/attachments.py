from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

import httpx

from brain_sync.confluence_rest import (
    ConfluenceAuth,
    download_attachment,
    fetch_attachments,
    fetch_child_pages,
)
from brain_sync.fileops import EXCLUDED_DIRS, atomic_write_bytes, canonical_prefix, content_hash
from brain_sync.sources import slugify
from brain_sync.sources.base import DiscoveredImage
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
)

log = logging.getLogger(__name__)

# Must match the entry in EXCLUDED_DIRS (fileops.py) — this folder is
# excluded from content discovery, regen, and watching.
ATTACHMENTS_DIR = "_attachments"
assert ATTACHMENTS_DIR in EXCLUDED_DIRS, f"{ATTACHMENTS_DIR!r} missing from EXCLUDED_DIRS"


def _source_dir_id(canonical_id: str) -> str:
    """Derive the prefixed directory name from a canonical_id.

    confluence:12345 → c12345, gdoc:abc123 → gabc123
    """
    return canonical_prefix(canonical_id).rstrip("-")


class RelType(StrEnum):
    ATTACHMENT = "attachment"


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


def attachment_local_path(source_dir_id: str, att_id: str, title: str | None) -> str:
    """Compute the local_path (relative from target_dir) for an attachment.

    Returns a path of the form ``_attachments/{source_dir_id}/a{att_id}-{slug}.{ext}``.
    This is the single source of truth for the attachment path scheme, used by
    sync, remove, move, migration, and ``attachment-ref:`` resolution.
    """
    if title:
        clean = title.split("?")[0]  # strip query params
        stem = Path(clean).stem
        ext = Path(clean).suffix  # e.g. ".png", ".ashx"
        filename = f"a{att_id}-{slugify(stem)}{ext}"
    else:
        filename = f"a{att_id}"
    return f"{ATTACHMENTS_DIR}/{source_dir_id}/{filename}"


def ensure_attachment_dir(target_dir: Path, source_dir_id: str) -> Path:
    """Create _attachments/{source_dir_id}/ directory. Returns the attachment dir."""
    att_dir = target_dir / ATTACHMENTS_DIR / source_dir_id
    att_dir.mkdir(parents=True, exist_ok=True)
    return att_dir


def remove_synced_file(path: Path, safe_root: Path) -> bool:
    """Safely remove a file, asserting it's within safe_root."""
    resolved = path.resolve()
    if not resolved.is_relative_to(safe_root.resolve()):
        raise SafetyError(f"Refusing to delete {path}: outside safe root {safe_root}")
    if resolved.exists():
        resolved.unlink()
        return True
    return False


# --- Discovery ---


@dataclass
class ChildPage:
    """A child page discovered via REST API (not a relationship — children become primary sources)."""

    canonical_id: str
    url: str
    title: str | None


async def discover_children(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> list[ChildPage]:
    """Discover child pages via REST API."""
    children = await fetch_child_pages(page_id, auth, client)
    return [
        ChildPage(
            canonical_id=f"confluence:{c['id']}",
            url=f"https://{auth.domain}/wiki/spaces/unknown/pages/{c['id']}",
            title=c.get("title"),
        )
        for c in children
    ]


async def discover_attachments(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
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


# --- Sync operations ---


async def _sync_attachment_doc(
    doc: DiscoveredDoc,
    local_path: str,
    target_dir: Path,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
    now: str,
) -> DocumentState:
    """Download and write an attachment."""
    data = await download_attachment(doc.url, auth, client)
    target = target_dir / local_path
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


# --- Legacy migration ---

LEGACY_CONTEXT_DIR = "_sync-context"


def migrate_legacy_context(
    target_dir: Path,
    source_dir_id: str,
    primary_canonical_id: str,
    root: Path,
) -> int:
    """Migrate files from legacy _sync-context/attachments/ to _attachments/{source_dir_id}/.

    Also cleans up stale _index.md, children/, and linked/ dirs.
    Also re-migrates bare-ID dirs (``_attachments/12345/``) from earlier migration runs.
    Returns the number of attachment files migrated.
    """
    legacy_root = target_dir / LEGACY_CONTEXT_DIR
    migrated = 0

    if legacy_root.is_dir():
        legacy_att_dir = legacy_root / "attachments"
        if legacy_att_dir.is_dir():
            new_dir = ensure_attachment_dir(target_dir, source_dir_id)

            for f in list(legacy_att_dir.iterdir()):
                if not f.is_file():
                    continue
                dest = new_dir / f.name
                shutil.move(str(f), str(dest))
                migrated += 1

        # Remove the entire legacy _sync-context/ tree
        shutil.rmtree(legacy_root)
        if migrated:
            log.info(
                "Migrated %d attachment(s) from %s to %s/%s/",
                migrated,
                LEGACY_CONTEXT_DIR,
                ATTACHMENTS_DIR,
                source_dir_id,
            )
        else:
            log.info("Cleaned up empty %s/ in %s", LEGACY_CONTEXT_DIR, target_dir)

    # Re-migrate bare-ID dirs from earlier migration runs.
    # e.g. _attachments/12345/ → _attachments/c12345/
    bare_id = primary_canonical_id.split(":", 1)[1]
    bare_dir = target_dir / ATTACHMENTS_DIR / bare_id
    if bare_dir.is_dir() and bare_id != source_dir_id:
        prefixed_dir = ensure_attachment_dir(target_dir, source_dir_id)
        remigrated = 0
        for f in list(bare_dir.iterdir()):
            dest = prefixed_dir / f.name
            shutil.move(str(f), str(dest))
            remigrated += 1
        bare_dir.rmdir()
        log.info("Re-migrated _attachments/%s/ → _attachments/%s/", bare_id, source_dir_id)
        migrated += remigrated

    return migrated


# --- Orchestrator ---


async def process_attachments(
    target_dir: Path,
    primary_canonical_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
    root: Path,
    sync_attachments: bool = False,
) -> dict[str, str]:
    """Run full discovery → reconciliation → sync cycle for attachment documents.

    Only called for primary sources with sync_attachments=True.
    Returns a mapping of original attachment title → local_path for inline image resolution.
    """
    now = datetime.now(UTC).isoformat()
    page_id = primary_canonical_id.split(":", 1)[1]  # bare ID for REST API calls
    source_dir_id = _source_dir_id(primary_canonical_id)  # prefixed ID for filesystem
    att_title_to_path: dict[str, str] = {}

    # Migrate legacy _sync-context/ before any sync logic — ensures path
    # consistency before version checks or downloads.
    migrate_legacy_context(target_dir, source_dir_id, primary_canonical_id, root)

    # Discover
    discovered: list[DiscoveredDoc] = []
    if sync_attachments:
        discovered.extend(await discover_attachments(page_id, auth, client))

    # Deduplicate by canonical_id
    seen: set[str] = set()
    unique: list[DiscoveredDoc] = []
    for d in discovered:
        if d.canonical_id not in seen and d.canonical_id != primary_canonical_id:
            seen.add(d.canonical_id)
            unique.append(d)
    discovered = unique

    existing_rels = load_relationships_for_primary(root, primary_canonical_id)

    # Reconcile
    to_add, to_check, to_remove_ids = reconcile(discovered, existing_rels)

    att_dir = ensure_attachment_dir(target_dir, source_dir_id)

    # Sync new docs
    for doc in to_add:
        att_id = doc.canonical_id.split(":", 1)[1]
        local_path = attachment_local_path(source_dir_id, att_id, doc.title)
        try:
            doc_state = await _sync_attachment_doc(
                doc,
                local_path,
                target_dir,
                auth,
                client,
                now,
            )

            save_document(root, doc_state)
            save_relationship(
                root,
                Relationship(
                    parent_canonical_id=primary_canonical_id,
                    canonical_id=doc.canonical_id,
                    relationship_type=doc.relationship_type.value,
                    source_type="confluence",
                    first_seen_utc=now,
                    last_seen_utc=now,
                ),
            )
            if doc.title:
                att_title_to_path[doc.title] = local_path
            log.info("Added attachment: %s → %s", doc.canonical_id, local_path)
        except Exception as e:
            log.warning("Failed to sync attachment %s: %s", doc.canonical_id, e)

    # Check existing docs (update last_seen, version-check, re-fetch if changed)
    existing_rel_map = {r.canonical_id: r for r in existing_rels}
    for doc in to_check:
        rel = existing_rel_map[doc.canonical_id]
        att_id = doc.canonical_id.split(":", 1)[1]
        local_path = attachment_local_path(source_dir_id, att_id, doc.title)
        try:
            # Update last_seen_utc
            save_relationship(
                root,
                Relationship(
                    parent_canonical_id=primary_canonical_id,
                    canonical_id=doc.canonical_id,
                    relationship_type=rel.relationship_type,
                    source_type=rel.source_type,
                    first_seen_utc=rel.first_seen_utc,
                    last_seen_utc=now,
                ),
            )

            if doc.title:
                att_title_to_path[doc.title] = local_path

            # Version check — also re-download if file is missing on disk
            existing_doc = load_document(root, doc.canonical_id)
            if (
                existing_doc
                and existing_doc.metadata_fingerprint
                and doc.version
                and str(doc.version) == existing_doc.metadata_fingerprint
                and (target_dir / local_path).exists()
            ):
                continue
            doc_state = await _sync_attachment_doc(
                doc,
                local_path,
                target_dir,
                auth,
                client,
                now,
            )

            save_document(root, doc_state)
            log.info("Updated attachment: %s", doc.canonical_id)
        except Exception as e:
            log.warning("Failed to check attachment %s: %s", doc.canonical_id, e)

    # Remove stale docs
    for cid in to_remove_ids:
        rel = existing_rel_map.get(cid)
        if rel:
            # Remove relationship
            remove_relationship(root, primary_canonical_id, cid)

            # Only delete file + document if no other primary references it
            if count_relationships_for_doc(root, cid) == 0:
                existing_doc = load_document(root, cid)
                doc_title = existing_doc.title if existing_doc else None
                att_id = cid.split(":", 1)[1]
                local_path = attachment_local_path(source_dir_id, att_id, doc_title)
                file_path = target_dir / local_path
                try:
                    remove_synced_file(file_path, att_dir)
                except SafetyError as e:
                    log.warning("%s", e)
                remove_document_if_orphaned(root, cid)
                log.info("Removed stale attachment: %s", cid)
            else:
                log.debug("Kept attachment %s (still referenced by other primaries)", cid)

    return att_title_to_path


# --- Generic inline image processing (source-agnostic) ---


def _inline_image_local_path(
    source_dir_id: str, canonical_id: str, image: DiscoveredImage, mime_type: str | None = None
) -> str:
    """Compute the local path for an inline image.

    Returns ``_attachments/{source_dir_id}/a{objectId}-{slug}.{ext}``.
    """
    from brain_sync.sources.googledocs.rest import image_filename

    # Extract objectId from canonical_id (last segment after final colon)
    parts = canonical_id.rsplit(":", 1)
    object_id = parts[1] if len(parts) == 2 else canonical_id
    filename = image_filename(object_id, image.title, None, mime_type or image.mime_type)
    return f"{ATTACHMENTS_DIR}/{source_dir_id}/{filename}"


async def process_inline_images(
    images: list[DiscoveredImage],
    headers: dict[str, str],
    client: httpx.AsyncClient,
    target_dir: Path,
    primary_canonical_id: str,
    root: Path,
) -> dict[str, str]:
    """Download and store inline images. Returns canonical_id → local_path mapping.

    Source-agnostic: works with any adapter that populates DiscoveredImage.
    Re-fetches all discovered images on each sync (URLs may be ephemeral),
    but only writes to disk when content hash changes.
    """
    now = datetime.now(UTC).isoformat()
    source_dir_id = _source_dir_id(primary_canonical_id)
    result_map: dict[str, str] = {}

    # Convert DiscoveredImage list to DiscoveredDoc for reconciliation reuse
    discovered = [
        DiscoveredDoc(
            canonical_id=img.canonical_id,
            url=img.download_url,
            title=img.title,
            relationship_type=RelType.ATTACHMENT,
            media_type=img.mime_type,
        )
        for img in images
    ]

    existing_rels = load_relationships_for_primary(root, primary_canonical_id)
    # Filter to only inline-image relationships (canonical IDs starting with gdoc-image:)
    existing_image_rels = [r for r in existing_rels if r.canonical_id.startswith("gdoc-image:")]

    to_add, to_check, to_remove_ids = reconcile(discovered, existing_image_rels)

    ensure_attachment_dir(target_dir, source_dir_id)
    att_dir = target_dir / ATTACHMENTS_DIR / source_dir_id

    # Build image lookup for description fallback
    image_by_cid = {img.canonical_id: img for img in images}

    # Process new images
    for doc in to_add:
        img = image_by_cid.get(doc.canonical_id)
        if not img:
            continue
        try:
            dl_result = await _download_image(doc.url, headers, client)
            if dl_result is None:
                continue
            data, content_type = dl_result
            effective_mime = content_type or img.mime_type
            local_path = _inline_image_local_path(source_dir_id, doc.canonical_id, img, effective_mime)
            target = target_dir / local_path
            atomic_write_bytes(target, data)
            save_document(
                root,
                DocumentState(
                    canonical_id=doc.canonical_id,
                    source_type="googledocs",
                    url=doc.canonical_id,
                    title=img.title,
                    last_checked_utc=now,
                    last_changed_utc=now,
                    content_hash=content_hash(data),
                    mime_type=effective_mime,
                ),
            )
            save_relationship(
                root,
                Relationship(
                    parent_canonical_id=primary_canonical_id,
                    canonical_id=doc.canonical_id,
                    relationship_type=RelType.ATTACHMENT.value,
                    source_type="googledocs",
                    first_seen_utc=now,
                    last_seen_utc=now,
                ),
            )
            result_map[doc.canonical_id] = local_path
            log.info("Added inline image: %s → %s", doc.canonical_id, local_path)
        except Exception:
            log.exception("Failed to sync inline image %s", doc.canonical_id)

    # Re-check existing images (re-download, content-hash compare)
    existing_rel_map = {r.canonical_id: r for r in existing_image_rels}
    for doc in to_check:
        rel = existing_rel_map[doc.canonical_id]
        img = image_by_cid.get(doc.canonical_id)
        if not img:
            continue
        try:
            save_relationship(
                root,
                Relationship(
                    parent_canonical_id=primary_canonical_id,
                    canonical_id=doc.canonical_id,
                    relationship_type=rel.relationship_type,
                    source_type=rel.source_type,
                    first_seen_utc=rel.first_seen_utc,
                    last_seen_utc=now,
                ),
            )

            # Always re-download (URL may have changed), but only write if content changed
            dl_result = await _download_image(doc.url, headers, client)
            if dl_result is None:
                # Download failed — still return existing path from DB for ref resolution
                existing_doc = load_document(root, doc.canonical_id)
                if existing_doc and existing_doc.mime_type:
                    local_path = _inline_image_local_path(source_dir_id, doc.canonical_id, img, existing_doc.mime_type)
                    result_map[doc.canonical_id] = local_path
                continue
            data, content_type = dl_result
            effective_mime = content_type or img.mime_type
            local_path = _inline_image_local_path(source_dir_id, doc.canonical_id, img, effective_mime)
            result_map[doc.canonical_id] = local_path

            new_hash = content_hash(data)
            existing_doc = load_document(root, doc.canonical_id)
            file_exists = (target_dir / local_path).exists()
            if existing_doc and existing_doc.content_hash == new_hash and file_exists:
                continue

            target = target_dir / local_path
            atomic_write_bytes(target, data)
            save_document(
                root,
                DocumentState(
                    canonical_id=doc.canonical_id,
                    source_type="googledocs",
                    url=doc.canonical_id,
                    title=img.title,
                    last_checked_utc=now,
                    last_changed_utc=now,
                    content_hash=new_hash,
                    mime_type=effective_mime,
                ),
            )
            log.info("Updated inline image: %s", doc.canonical_id)
        except Exception:
            log.exception("Failed to check inline image %s", doc.canonical_id)

    # Remove stale images
    for cid in to_remove_ids:
        rel = existing_rel_map.get(cid)
        if rel:
            remove_relationship(root, primary_canonical_id, cid)
            if count_relationships_for_doc(root, cid) == 0:
                existing_doc = load_document(root, cid)
                if existing_doc:
                    img_dummy = DiscoveredImage(
                        canonical_id=cid, download_url="", title=existing_doc.title, mime_type=existing_doc.mime_type
                    )
                    local_path = _inline_image_local_path(source_dir_id, cid, img_dummy)
                    file_path = target_dir / local_path
                    try:
                        remove_synced_file(file_path, att_dir)
                    except SafetyError as e:
                        log.warning("%s", e)
                remove_document_if_orphaned(root, cid)
                log.info("Removed stale inline image: %s", cid)
            else:
                log.debug("Kept inline image %s (still referenced by other primaries)", cid)

    return result_map


async def _download_image(
    url: str, headers: dict[str, str], client: httpx.AsyncClient
) -> tuple[bytes, str | None] | None:
    """Download an image, returning (data, content_type) or None on failure."""
    try:
        response = await client.get(url, headers=headers, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").split(";")[0].strip() or None
        return response.content, content_type
    except httpx.HTTPError as e:
        log.warning("Failed to download image %s: %s", url, e)
        return None

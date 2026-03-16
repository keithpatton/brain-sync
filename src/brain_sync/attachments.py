from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx

from brain_sync.confluence_rest import (
    ConfluenceAuth,
    download_attachment,
    fetch_attachments,
    fetch_child_pages,
)
from brain_sync.fileops import (
    EXCLUDED_DIRS,
    atomic_write_bytes,
    canonical_prefix,
    content_hash,
    iterdir_paths,
    path_exists,
    path_is_dir,
    path_is_file,
    read_bytes,
)
from brain_sync.layout import ATTACHMENTS_DIRNAME, MANAGED_DIRNAME
from brain_sync.sources import slugify
from brain_sync.sources.base import DiscoveredImage

log = logging.getLogger(__name__)

ATTACHMENTS_DIR = f"{MANAGED_DIRNAME}/{ATTACHMENTS_DIRNAME}"
assert MANAGED_DIRNAME in EXCLUDED_DIRS, f"{MANAGED_DIRNAME!r} missing from EXCLUDED_DIRS"


def _source_dir_id(canonical_id: str) -> str:
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
    if title:
        clean = title.split("?")[0]
        stem = Path(clean).stem
        ext = Path(clean).suffix
        filename = f"a{att_id}-{slugify(stem)}{ext}"
    else:
        filename = f"a{att_id}"
    return f"{ATTACHMENTS_DIR}/{source_dir_id}/{filename}"


def ensure_attachment_dir(target_dir: Path, source_dir_id: str) -> Path:
    att_dir = target_dir / MANAGED_DIRNAME / ATTACHMENTS_DIRNAME / source_dir_id
    att_dir.mkdir(parents=True, exist_ok=True)
    return att_dir


def remove_synced_file(path: Path, safe_root: Path) -> bool:
    resolved = path.resolve()
    if not resolved.is_relative_to(safe_root.resolve()):
        raise SafetyError(f"Refusing to delete {path}: outside safe root {safe_root}")
    if path_exists(resolved):
        resolved.unlink()
        return True
    return False


@dataclass
class ChildPage:
    canonical_id: str
    url: str
    title: str | None


async def discover_children(
    page_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
) -> list[ChildPage]:
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


def reconcile(
    discovered: list[DiscoveredDoc],
    existing_rels: list[object],
) -> tuple[list[DiscoveredDoc], list[DiscoveredDoc], set[str]]:
    discovered_ids: set[str] = {d.canonical_id for d in discovered}
    existing_ids: set[str] = {str(getattr(r, "canonical_id", r)) for r in existing_rels}
    to_add = [d for d in discovered if d.canonical_id not in existing_ids]
    to_check = [d for d in discovered if d.canonical_id in existing_ids]
    to_remove_ids = existing_ids - discovered_ids
    return to_add, to_check, to_remove_ids


LEGACY_CONTEXT_DIR = "_sync-context"


def migrate_legacy_context(
    target_dir: Path,
    source_dir_id: str,
    primary_canonical_id: str,
    root: Path,
) -> int:
    """Best-effort migration from legacy attachment locations into .brain-sync/."""
    migrated = 0

    legacy_root = target_dir / LEGACY_CONTEXT_DIR
    if path_is_dir(legacy_root):
        legacy_att_dir = legacy_root / "attachments"
        if path_is_dir(legacy_att_dir):
            new_dir = ensure_attachment_dir(target_dir, source_dir_id)
            for f in iterdir_paths(legacy_att_dir):
                if not path_is_file(f):
                    continue
                shutil.move(str(f), str(new_dir / f.name))
                migrated += 1
        shutil.rmtree(legacy_root)

    bare_id = primary_canonical_id.split(":", 1)[1]
    legacy_attachment_dir = target_dir / "_attachments" / bare_id
    if path_is_dir(legacy_attachment_dir):
        new_dir = ensure_attachment_dir(target_dir, source_dir_id)
        for f in iterdir_paths(legacy_attachment_dir):
            if not path_is_file(f):
                continue
            shutil.move(str(f), str(new_dir / f.name))
            migrated += 1
        legacy_attachment_dir.rmdir()

    return migrated


async def _sync_binary_file(
    *,
    url: str,
    local_path: str,
    target_dir: Path,
    client: httpx.AsyncClient,
    auth: ConfluenceAuth | None = None,
    headers: dict[str, str] | None = None,
) -> bool:
    if auth is not None:
        data = await download_attachment(url, auth, client)
    else:
        response = await client.get(url, headers=headers, follow_redirects=True, timeout=30.0)
        response.raise_for_status()
        data = response.content

    target = target_dir / local_path
    if path_exists(target) and content_hash(read_bytes(target)) == content_hash(data):
        return False
    atomic_write_bytes(target, data)
    return True


async def process_attachments(
    target_dir: Path,
    primary_canonical_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
    root: Path,
    sync_attachments: bool = False,
) -> dict[str, str]:
    page_id = primary_canonical_id.split(":", 1)[1]
    source_dir_id = _source_dir_id(primary_canonical_id)
    att_title_to_path: dict[str, str] = {}

    migrate_legacy_context(target_dir, source_dir_id, primary_canonical_id, root)
    ensure_attachment_dir(target_dir, source_dir_id)

    if not sync_attachments:
        return att_title_to_path

    discovered = await discover_attachments(page_id, auth, client)
    for doc in discovered:
        att_id = doc.canonical_id.split(":", 1)[1]
        local_path = attachment_local_path(source_dir_id, att_id, doc.title)
        if doc.title:
            att_title_to_path[doc.title] = local_path
        try:
            changed = await _sync_binary_file(
                url=doc.url,
                local_path=local_path,
                target_dir=target_dir,
                client=client,
                auth=auth,
            )
            if changed:
                log.info("Synced attachment: %s → %s", doc.canonical_id, local_path)
        except Exception as e:
            log.warning("Failed to sync attachment %s: %s", doc.canonical_id, e)

    return att_title_to_path


def _inline_image_local_path(
    source_dir_id: str, canonical_id: str, image: DiscoveredImage, mime_type: str | None = None
) -> str:
    from brain_sync.sources.googledocs.rest import image_filename

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
    source_dir_id = _source_dir_id(primary_canonical_id)
    ensure_attachment_dir(target_dir, source_dir_id)
    result_map: dict[str, str] = {}

    for image in images:
        local_path = _inline_image_local_path(source_dir_id, image.canonical_id, image, image.mime_type)
        result_map[image.canonical_id] = local_path
        try:
            changed = await _sync_binary_file(
                url=image.download_url,
                local_path=local_path,
                target_dir=target_dir,
                client=client,
                headers=headers,
            )
            if changed:
                log.info("Synced inline image: %s", image.canonical_id)
        except Exception:
            log.exception("Failed to sync inline image %s", image.canonical_id)

    return result_map

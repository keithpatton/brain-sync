from __future__ import annotations

import logging
from pathlib import Path

import httpx

from brain_sync.brain.fileops import EXCLUDED_DIRS, content_hash, path_exists, read_bytes
from brain_sync.brain.layout import ATTACHMENTS_DIRNAME, MANAGED_DIRNAME
from brain_sync.brain.repository import BrainRepository
from brain_sync.brain.repository import (
    attachment_local_path_for_source_dir as repository_attachment_local_path,
)
from brain_sync.brain.repository import (
    ensure_attachment_dir_for_source_dir as repository_ensure_attachment_dir,
)
from brain_sync.brain.repository import source_dir_id as repository_source_dir_id
from brain_sync.sources.base import DiscoveredImage

log = logging.getLogger(__name__)

ATTACHMENTS_DIR = f"{MANAGED_DIRNAME}/{ATTACHMENTS_DIRNAME}"
LEGACY_CONTEXT_DIR = "_sync-context"
assert MANAGED_DIRNAME in EXCLUDED_DIRS, f"{MANAGED_DIRNAME!r} missing from EXCLUDED_DIRS"


class SafetyError(Exception):
    pass


def _source_dir_id(canonical_id: str) -> str:
    return repository_source_dir_id(canonical_id)


def attachment_local_path(source_dir_id: str, att_id: str, title: str | None) -> str:
    return repository_attachment_local_path(source_dir_id, att_id, title).replace(
        f"{MANAGED_DIRNAME}/{ATTACHMENTS_DIRNAME}",
        ATTACHMENTS_DIR,
    )


def ensure_attachment_dir(target_dir: Path, source_dir_id: str) -> Path:
    return repository_ensure_attachment_dir(target_dir, source_dir_id)


def remove_synced_file(path: Path, safe_root: Path) -> bool:
    resolved = path.resolve()
    if not resolved.is_relative_to(safe_root.resolve()):
        raise SafetyError(f"Refusing to delete {path}: outside safe root {safe_root}")
    if path_exists(resolved):
        resolved.unlink()
        return True
    return False


def migrate_legacy_context(target_dir: Path, source_dir_id: str, primary_canonical_id: str, root: Path) -> int:
    """Best-effort migration from legacy attachment locations into .brain-sync/."""
    repository = BrainRepository(root)
    return repository.migrate_legacy_attachment_context(
        target_dir,
        source_dir=source_dir_id,
        primary_canonical_id=primary_canonical_id,
    )


async def _sync_binary_file(
    *,
    url: str,
    local_path: str,
    target_dir: Path,
    client: httpx.AsyncClient,
    repository: BrainRepository,
    headers: dict[str, str] | None = None,
) -> bool:
    response = await client.get(url, headers=headers, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    data = response.content

    target = target_dir / local_path
    if path_exists(target) and content_hash(read_bytes(target)) == content_hash(data):
        return False
    return repository.write_attachment_bytes(target_dir=target_dir, local_path=local_path, data=data)


def _inline_image_local_path(
    source_dir_id: str,
    canonical_id: str,
    image: DiscoveredImage,
    mime_type: str | None = None,
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
    repository = BrainRepository(root)

    for image in images:
        local_path = _inline_image_local_path(source_dir_id, image.canonical_id, image, image.mime_type)
        result_map[image.canonical_id] = local_path
        try:
            changed = await _sync_binary_file(
                url=image.download_url,
                local_path=local_path,
                target_dir=target_dir,
                client=client,
                repository=repository,
                headers=headers,
            )
            if changed:
                log.info("Synced inline image: %s", image.canonical_id)
        except Exception:
            log.exception("Failed to sync inline image %s", image.canonical_id)

    return result_map


__all__ = [
    "ATTACHMENTS_DIR",
    "LEGACY_CONTEXT_DIR",
    "SafetyError",
    "attachment_local_path",
    "ensure_attachment_dir",
    "migrate_legacy_context",
    "process_inline_images",
    "remove_synced_file",
]

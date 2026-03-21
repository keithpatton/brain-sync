from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import httpx

from brain_sync.brain.fileops import EXCLUDED_DIRS, path_exists
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


@dataclass(frozen=True)
class StagedManagedArtifact:
    local_path: str
    data: bytes


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
    client: httpx.AsyncClient,
    headers: dict[str, str] | None = None,
) -> bytes:
    response = await client.get(url, headers=headers, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    return response.content


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
    primary_canonical_id: str,
    target_dir: Path,
    root: Path,
) -> tuple[dict[str, str], list[StagedManagedArtifact]]:
    del target_dir, root
    source_dir_id = _source_dir_id(primary_canonical_id)
    result_map: dict[str, str] = {}
    staged_artifacts: list[StagedManagedArtifact] = []

    for image in images:
        local_path = _inline_image_local_path(source_dir_id, image.canonical_id, image, image.mime_type)
        result_map[image.canonical_id] = local_path
        try:
            data = await _sync_binary_file(
                url=image.download_url,
                client=client,
                headers=headers,
            )
            staged_artifacts.append(StagedManagedArtifact(local_path=local_path, data=data))
        except Exception:
            log.exception("Failed to sync inline image %s", image.canonical_id)

    return result_map, staged_artifacts


__all__ = [
    "ATTACHMENTS_DIR",
    "LEGACY_CONTEXT_DIR",
    "SafetyError",
    "StagedManagedArtifact",
    "attachment_local_path",
    "ensure_attachment_dir",
    "migrate_legacy_context",
    "process_inline_images",
    "remove_synced_file",
]

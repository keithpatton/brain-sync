from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import httpx

from brain_sync.brain.repository import source_dir_id as repository_source_dir_id
from brain_sync.sources.confluence.rest import (
    ConfluenceAuth,
    download_attachment,
    fetch_attachments,
    fetch_child_pages,
)
from brain_sync.sync.attachments import (
    StagedManagedArtifact,
    attachment_local_path,
)

log = logging.getLogger(__name__)


class RelType(StrEnum):
    ATTACHMENT = "attachment"


@dataclass
class DiscoveredDoc:
    canonical_id: str
    url: str
    title: str | None
    relationship_type: RelType
    version: int | None = None
    media_type: str | None = None


@dataclass
class ChildPage:
    canonical_id: str
    url: str
    title: str | None


async def discover_children(page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient) -> list[ChildPage]:
    children = await fetch_child_pages(page_id, auth, client)
    return [
        ChildPage(
            canonical_id=f"confluence:{child['id']}",
            url=f"https://{auth.domain}/wiki/spaces/unknown/pages/{child['id']}",
            title=child.get("title"),
        )
        for child in children
    ]


async def discover_attachments(page_id: str, auth: ConfluenceAuth, client: httpx.AsyncClient) -> list[DiscoveredDoc]:
    attachments = await fetch_attachments(page_id, auth, client)
    return [
        DiscoveredDoc(
            canonical_id=f"confluence-attachment:{attachment['id']}",
            url=attachment.get("download_url", ""),
            title=attachment.get("title"),
            relationship_type=RelType.ATTACHMENT,
            version=attachment.get("version"),
            media_type=attachment.get("media_type"),
        )
        for attachment in attachments
    ]


def reconcile(
    discovered: list[DiscoveredDoc],
    existing_rels: list[object],
) -> tuple[list[DiscoveredDoc], list[DiscoveredDoc], set[str]]:
    discovered_ids: set[str] = {doc.canonical_id for doc in discovered}
    existing_ids: set[str] = {str(getattr(rel, "canonical_id", rel)) for rel in existing_rels}
    to_add = [doc for doc in discovered if doc.canonical_id not in existing_ids]
    to_check = [doc for doc in discovered if doc.canonical_id in existing_ids]
    to_remove_ids = existing_ids - discovered_ids
    return to_add, to_check, to_remove_ids


async def _sync_confluence_attachment(
    *,
    url: str,
    client: httpx.AsyncClient,
    auth: ConfluenceAuth,
) -> bytes:
    return await download_attachment(url, auth, client)


async def process_attachments(
    target_dir: Path,
    primary_canonical_id: str,
    auth: ConfluenceAuth,
    client: httpx.AsyncClient,
    root: Path,
    sync_attachments: bool = False,
) -> tuple[dict[str, str], list[StagedManagedArtifact]]:
    page_id = primary_canonical_id.split(":", 1)[1]
    del target_dir, root
    source_dir_id = repository_source_dir_id(primary_canonical_id)
    att_title_to_path: dict[str, str] = {}
    staged_artifacts: list[StagedManagedArtifact] = []

    if not sync_attachments:
        return att_title_to_path, staged_artifacts

    discovered = await discover_attachments(page_id, auth, client)
    for doc in discovered:
        att_id = doc.canonical_id.split(":", 1)[1]
        local_path = attachment_local_path(source_dir_id, att_id, doc.title)
        if doc.title:
            att_title_to_path[doc.title] = local_path
        try:
            data = await _sync_confluence_attachment(
                url=doc.url,
                client=client,
                auth=auth,
            )
            staged_artifacts.append(StagedManagedArtifact(local_path=local_path, data=data))
        except Exception as exc:
            log.warning("Failed to sync attachment %s: %s", doc.canonical_id, exc)

    return att_title_to_path, staged_artifacts


__all__ = [
    "ChildPage",
    "DiscoveredDoc",
    "RelType",
    "discover_attachments",
    "discover_children",
    "process_attachments",
    "reconcile",
]

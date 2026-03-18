"""Application-owned child-discovery policy."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from brain_sync.application.source_state import SyncState, load_state
from brain_sync.application.sources import SourceAlreadyExistsError, add_source
from brain_sync.runtime.repository import ChildDiscoveryRequest, clear_child_discovery_request, record_operational_event
from brain_sync.sources import slugify
from brain_sync.sync.pipeline import ChildDiscoveryResult

log = logging.getLogger(__name__)

__all__ = ["compute_child_target_base", "process_discovered_children"]


def compute_child_target_base(
    *,
    parent_target: str,
    parent_canonical_id: str,
    parent_source_url: str,
    request: ChildDiscoveryRequest,
) -> str:
    """Resolve the target area for children discovered from one parent source."""
    if request.child_path == ".":
        return parent_target
    if request.child_path:
        return f"{parent_target}/{request.child_path}" if parent_target else request.child_path

    parent_id = parent_canonical_id.split(":", 1)[1]
    slug = slugify(parent_source_url.rstrip("/").split("/")[-1] or parent_id)
    suffix = f"c{parent_id}-{slug}"
    return f"{parent_target}/{suffix}" if parent_target else suffix


def process_discovered_children(
    root: Path,
    *,
    parent_canonical_id: str,
    parent_source_url: str,
    parent_target: str,
    sync_attachments: bool,
    request: ChildDiscoveryRequest | None,
    discovered_children: list[ChildDiscoveryResult],
    schedule_immediate: Callable[[str], None],
    state: SyncState,
) -> SyncState:
    """Register discovered child sources and clear the one-shot request."""
    if request is None or not request.fetch_children:
        return state

    try:
        child_target_base = compute_child_target_base(
            parent_target=parent_target,
            parent_canonical_id=parent_canonical_id,
            parent_source_url=parent_source_url,
            request=request,
        )
        for child in discovered_children:
            try:
                child_result = add_source(
                    root=root,
                    url=child.url,
                    target_path=child_target_base,
                    sync_attachments=sync_attachments,
                )
                refreshed = load_state(root).sources.get(child_result.canonical_id)
                if refreshed is not None:
                    state.sources[child_result.canonical_id] = refreshed
                schedule_immediate(child_result.canonical_id)
                record_operational_event(
                    event_type="source.child_registered",
                    canonical_id=child_result.canonical_id,
                    knowledge_path=child_result.target_path,
                    outcome="registered",
                    details={"parent_canonical_id": parent_canonical_id},
                )
                log.info("Added child source %s -> knowledge/%s", child_result.canonical_id, child_result.target_path)
            except SourceAlreadyExistsError:
                log.debug("Child %s already registered, skipping", child.canonical_id)
            except Exception as exc:
                log.warning("Failed to add child %s: %s", child.canonical_id, exc)
    finally:
        clear_child_discovery_request(root, parent_canonical_id)

    return state

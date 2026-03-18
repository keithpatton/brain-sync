"""Compatibility facade for runtime child-discovery requests.

The runtime DB owner is ``brain_sync.runtime.repository``. This module keeps a
small import surface for existing callers while delegating all persistence.
"""

from __future__ import annotations

from pathlib import Path

from brain_sync.runtime.repository import (
    ChildDiscoveryRequest,
    clear_child_discovery_request,
    load_all_child_discovery_requests,
    load_child_discovery_request,
    save_child_discovery_request,
)

__all__ = [
    "ChildDiscoveryRequest",
    "clear_child_discovery_request",
    "load_all_child_discovery_requests",
    "load_child_discovery_request",
    "save_child_discovery_request",
]


def delete_child_discovery_request(root: Path, canonical_id: str) -> None:
    clear_child_discovery_request(root, canonical_id)

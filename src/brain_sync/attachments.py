"""Compatibility shim for attachment helpers."""

from brain_sync.sources.confluence.attachments import (
    ChildPage,
    DiscoveredDoc,
    RelType,
    discover_attachments,
    discover_children,
    process_attachments,
    reconcile,
)
from brain_sync.sync.attachments import (
    ATTACHMENTS_DIR,
    LEGACY_CONTEXT_DIR,
    SafetyError,
    attachment_local_path,
    ensure_attachment_dir,
    migrate_legacy_context,
    process_inline_images,
    remove_synced_file,
)

__all__ = [
    "ATTACHMENTS_DIR",
    "LEGACY_CONTEXT_DIR",
    "ChildPage",
    "DiscoveredDoc",
    "RelType",
    "SafetyError",
    "attachment_local_path",
    "discover_attachments",
    "discover_children",
    "ensure_attachment_dir",
    "migrate_legacy_context",
    "process_attachments",
    "process_inline_images",
    "reconcile",
    "remove_synced_file",
]

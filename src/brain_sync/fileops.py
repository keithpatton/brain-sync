from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

from brain_sync.layout import INSIGHT_STATE_FILENAME, MANAGED_DIRNAME, SUMMARY_FILENAME

# Canonical whitelist of file formats processed from knowledge/.
# Text formats are inlined in regen prompts; images are passed to Claude
# multimodal. Everything else is ignored.
TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
KNOWLEDGE_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS

# Extensions accepted by add-file / brain_sync_add_file for local file import.
ADDFILE_EXTENSIONS = {".md", ".txt"}

# Directories excluded from content discovery, regen, and watching.
EXCLUDED_DIRS = frozenset({MANAGED_DIRNAME, "_attachments", "_sync-context"})


def win_long_path(p: Path) -> Path:
    """On Windows, apply extended-length prefix to bypass MAX_PATH (260 chars).

    Python's os.* functions support the ``\\\\?\\`` prefix natively.
    On non-Windows platforms this is a no-op.
    """
    if sys.platform == "win32":
        s = str(p.resolve())
        if not s.startswith("\\\\?\\"):
            return Path("\\\\?\\" + s)
    return p


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(target: Path, data: bytes) -> None:
    safe_parent = win_long_path(target.parent)
    safe_target = win_long_path(target)
    safe_parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=safe_parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        os.write(fd, data)
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp_path, safe_target)
        # Fsync parent directory to ensure the rename is durable.
        # On Windows, os.open on directories may fail — NTFS journaling
        # provides metadata durability anyway.
        try:
            dir_fd = os.open(str(safe_parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except BaseException:
        if fd >= 0:
            os.close(fd)
        Path(tmp_path).unlink(missing_ok=True)
        raise


def write_if_changed(target: Path, markdown: str) -> bool:
    encoded = markdown.encode("utf-8")
    new_hash = content_hash(encoded)

    safe_target = win_long_path(target)
    if safe_target.exists():
        old_hash = content_hash(safe_target.read_bytes())
        if old_hash == new_hash:
            return False

    atomic_write_bytes(target, encoded)
    return True


# Only these files are regenerable and safe to delete during cleanup.
# Everything else (journal entries, future artifact types) is preserved automatically.
REGENERABLE_FILES = frozenset({SUMMARY_FILENAME, INSIGHT_STATE_FILENAME})

# Subdirectories within insights/ that contain non-regenerable artifacts.
# These are NOT mirrors of knowledge/ folders and must be excluded from
# orphan detection. Currently only journal/; future types added here.
INSIGHT_ARTIFACT_DIRS = frozenset({"journal"})


def clean_insights_tree(insights_dir: Path) -> bool:
    """Recursively remove regenerable artifacts from an insights subtree.

    Walks bottom-up through the entire subtree. At each level, removes only
    files listed in REGENERABLE_FILES. Prunes directories that become empty.
    Any file NOT in REGENERABLE_FILES is automatically preserved — this means
    journal entries and any future non-regenerable artifact types are safe
    without needing to be explicitly listed.

    Returns True if the root directory was fully removed.
    """
    if not insights_dir.is_dir():
        return False

    # Bottom-up walk: recurse into ALL child directories
    for child in sorted(insights_dir.iterdir()):
        if child.is_dir():
            clean_insights_tree(child)

    # Remove only regenerable files at this level
    for name in REGENERABLE_FILES:
        target = insights_dir / name
        if target.is_file():
            target.unlink()

    # Remove this directory only if completely empty
    if not any(insights_dir.iterdir()):
        insights_dir.rmdir()
        return True
    return False


def canonical_prefix(canonical_id: str) -> str:
    """Convert a canonical_id to the filename prefix used for rediscovery."""
    if canonical_id.startswith("confluence-attachment:"):
        return f"a{canonical_id.split(':', 1)[1]}-"
    if canonical_id.startswith("confluence:"):
        return f"c{canonical_id.split(':', 1)[1]}-"
    if canonical_id.startswith("gdoc-image:"):
        # gdoc-image:{docId}:{objectId} → gi{docId}-{objectId}-
        parts = canonical_id.split(":", 2)
        return f"gi{parts[1]}-{parts[2]}-" if len(parts) == 3 else f"gi{parts[1]}-"
    if canonical_id.startswith("gdoc:"):
        return f"g{canonical_id.split(':', 1)[1]}-"
    return canonical_id.split(":", 1)[1] + "-"


def _in_excluded_dir(path: Path) -> bool:
    """Check if any component of the path is an excluded directory."""
    return any(part in EXCLUDED_DIRS for part in path.parts)


def rediscover_local_path(root: Path, canonical_id: str) -> Path | None:
    """Search root recursively for a file matching the canonical_id prefix.

    Returns the first matching path relative to root, or None.
    Only called when the stored local_path no longer exists.
    Skips paths containing EXCLUDED_DIRS components.
    """
    prefix = canonical_prefix(canonical_id)
    resolved_root = root.resolve()
    for path in resolved_root.rglob(f"{prefix}*"):
        if path.is_file() and not _in_excluded_dir(path.relative_to(resolved_root)):
            return path
    # Also try without trailing content (e.g. "c123456.md" for titleless docs)
    bare_prefix = prefix.rstrip("-")
    if bare_prefix != prefix:
        for path in resolved_root.rglob(f"{bare_prefix}.*"):
            if path.is_file() and not _in_excluded_dir(path.relative_to(resolved_root)):
                return path
    return None

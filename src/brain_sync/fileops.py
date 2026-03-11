from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

# Canonical whitelist of file formats processed from knowledge/.
# Text formats are inlined in regen prompts; images are passed to Claude
# multimodal. Everything else is ignored.
TEXT_EXTENSIONS = {".md", ".txt", ".csv", ".json"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}
KNOWLEDGE_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS

# Directories excluded from content discovery, regen, and watching.
# _sync-context/ contains relationship metadata managed by the sync engine.
EXCLUDED_DIRS = frozenset({"_sync-context"})


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


def canonical_prefix(canonical_id: str) -> str:
    """Convert a canonical_id to the filename prefix used for rediscovery."""
    if canonical_id.startswith("confluence-attachment:"):
        return f"a{canonical_id.split(':', 1)[1]}-"
    if canonical_id.startswith("confluence:"):
        return f"c{canonical_id.split(':', 1)[1]}-"
    if canonical_id.startswith("gdoc:"):
        return f"g{canonical_id.split(':', 1)[1]}-"
    return canonical_id.split(":", 1)[1] + "-"


def rediscover_local_path(root: Path, canonical_id: str) -> Path | None:
    """Search root recursively for a file matching the canonical_id prefix.

    Returns the first matching path relative to root, or None.
    Only called when the stored local_path no longer exists.
    """
    prefix = canonical_prefix(canonical_id)
    resolved_root = root.resolve()
    for path in resolved_root.rglob(f"{prefix}*"):
        if path.is_file():
            return path
    # Also try without trailing content (e.g. "c123456.md" for titleless docs)
    bare_prefix = prefix.rstrip("-")
    if bare_prefix != prefix:
        for path in resolved_root.rglob(f"{bare_prefix}.*"):
            if path.is_file():
                return path
    return None

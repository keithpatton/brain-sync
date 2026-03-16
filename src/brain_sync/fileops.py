from __future__ import annotations

import fnmatch
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


def _normalise_display_path(p: Path | str) -> Path:
    """Convert an internal extended-length path back to its normal form."""
    s = str(p)
    if s.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + s[8:])
    if s.startswith("\\\\?\\"):
        return Path(s[4:])
    return Path(s)


def _safe_path_str(p: Path | str) -> str:
    return str(win_long_path(_normalise_display_path(p)))


def _path_sort_key(path: Path) -> tuple[str, ...]:
    return tuple(part.casefold() for part in _normalise_display_path(path).parts)


def path_exists(path: Path) -> bool:
    return os.path.exists(_safe_path_str(path))


def path_is_file(path: Path) -> bool:
    return os.path.isfile(_safe_path_str(path))


def path_is_dir(path: Path) -> bool:
    return os.path.isdir(_safe_path_str(path))


def read_bytes(path: Path) -> bytes:
    with open(_safe_path_str(path), "rb") as f:
        return f.read()


def read_text(path: Path, *, encoding: str = "utf-8", errors: str | None = None) -> str:
    with open(_safe_path_str(path), encoding=encoding, errors=errors) as f:
        return f.read()


def iterdir_paths(directory: Path) -> list[Path]:
    if not path_is_dir(directory):
        return []
    with os.scandir(_safe_path_str(directory)) as entries:
        children = [directory / entry.name for entry in entries]
    return sorted(children, key=_path_sort_key)


def glob_paths(directory: Path, pattern: str) -> list[Path]:
    return [path for path in iterdir_paths(directory) if fnmatch.fnmatch(path.name, pattern)]


def rglob_paths(directory: Path, pattern: str) -> list[Path]:
    if not path_is_dir(directory):
        return []
    matches: list[Path] = []
    stack = [directory]
    while stack:
        current = stack.pop()
        for child in iterdir_paths(current):
            if path_is_dir(child):
                stack.append(child)
            if fnmatch.fnmatch(child.name, pattern):
                matches.append(child)
    return sorted(matches, key=_path_sort_key)


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


def write_bytes_if_changed(target: Path, data: bytes) -> bool:
    """Atomically write bytes only when the durable content changes."""
    if path_exists(target) and read_bytes(target) == data:
        return False
    atomic_write_bytes(target, data)
    return True


def write_if_changed(target: Path, markdown: str) -> bool:
    return write_bytes_if_changed(target, markdown.encode("utf-8"))


# Only these files are regenerable and safe to delete during cleanup.
# Everything else (journal entries, future artifact types) is preserved automatically.
REGENERABLE_FILES = frozenset({SUMMARY_FILENAME, INSIGHT_STATE_FILENAME})

# Subdirectories within .brain-sync/insights/ that contain non-regenerable artifacts.
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
    if not path_is_dir(insights_dir):
        return False

    # Bottom-up walk: recurse into ALL child directories
    for child in iterdir_paths(insights_dir):
        if path_is_dir(child):
            clean_insights_tree(child)

    # Remove only regenerable files at this level
    for name in REGENERABLE_FILES:
        target = insights_dir / name
        if path_is_file(target):
            target.unlink()

    # Remove this directory only if completely empty
    if not iterdir_paths(insights_dir):
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
    for path in rglob_paths(resolved_root, f"{prefix}*"):
        if path_is_file(path) and not _in_excluded_dir(path.relative_to(resolved_root)):
            return path
    # Also try without trailing content (e.g. "c123456.md" for titleless docs)
    bare_prefix = prefix.rstrip("-")
    if bare_prefix != prefix:
        for path in rglob_paths(resolved_root, f"{bare_prefix}.*"):
            if path_is_file(path) and not _in_excluded_dir(path.relative_to(resolved_root)):
                return path
    return None

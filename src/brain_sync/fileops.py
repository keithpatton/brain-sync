from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from brain_sync.manifest import Manifest


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        os.write(fd, data)
        os.close(fd)
        fd = -1
        os.replace(tmp_path, target)
    except BaseException:
        if fd >= 0:
            os.close(fd)
        Path(tmp_path).unlink(missing_ok=True)
        raise


def write_if_changed(target: Path, markdown: str) -> bool:
    encoded = markdown.encode("utf-8")
    new_hash = content_hash(encoded)

    if target.exists():
        old_hash = content_hash(target.read_bytes())
        if old_hash == new_hash:
            return False

    atomic_write_bytes(target, encoded)
    return True


def resolve_dirty_path(manifest: Manifest) -> Path:
    manifest_dir = manifest.path.parent
    if manifest.touch_dirty_relative_path is not None:
        return (manifest_dir / manifest.touch_dirty_relative_path).resolve()
    return manifest_dir / ".dirty"


def touch_dirty(dirty_path: Path) -> None:
    dirty_path.parent.mkdir(parents=True, exist_ok=True)
    dirty_path.touch()

"""Insight sidecar read/write utilities.

Each insights folder has a `.regen-meta.json` sidecar that persists the
three regen hashes (content_hash, summary_hash, structure_hash) to the
filesystem.  Sidecars are the sole authority for regen hashes (v21+).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from brain_sync.fileops import atomic_write_bytes, path_exists, path_is_dir, read_bytes, rglob_paths
from brain_sync.layout import INSIGHT_STATE_FILENAME, INSIGHT_STATE_VERSION, area_insight_state_path

log = logging.getLogger(__name__)

SIDECAR_FILENAME = INSIGHT_STATE_FILENAME
SIDECAR_VERSION = INSIGHT_STATE_VERSION


class UnsupportedSidecarVersion(Exception):
    """Raised when a sidecar has an unrecognised version."""

    def __init__(self, path: str, version: int):
        self.path = path
        self.version = version
        super().__init__(f"Unsupported sidecar version {version} in {path} (max supported: {SIDECAR_VERSION})")


@dataclass
class RegenMeta:
    """On-disk representation of regen hashes for one insights folder."""

    version: int = SIDECAR_VERSION
    content_hash: str | None = None
    summary_hash: str | None = None
    structure_hash: str | None = None
    last_regen_utc: str | None = None


def write_regen_meta(insights_dir: Path, meta: RegenMeta) -> None:
    """Atomically write a .regen-meta.json sidecar to an insights folder."""
    d: dict[str, object] = {"version": meta.version}
    if meta.content_hash is not None:
        d["content_hash"] = meta.content_hash
    if meta.summary_hash is not None:
        d["summary_hash"] = meta.summary_hash
    if meta.structure_hash is not None:
        d["structure_hash"] = meta.structure_hash
    if meta.last_regen_utc is not None:
        d["last_regen_utc"] = meta.last_regen_utc
    data = (json.dumps(d, indent=2, sort_keys=False) + "\n").encode("utf-8")
    atomic_write_bytes(insights_dir / SIDECAR_FILENAME, data)
    log.debug("Wrote sidecar %s", insights_dir / SIDECAR_FILENAME)


def read_regen_meta(insights_dir: Path) -> RegenMeta | None:
    """Read a .regen-meta.json sidecar. Returns None if missing or malformed."""
    target = insights_dir / SIDECAR_FILENAME
    if not path_exists(target):
        return None
    try:
        d = json.loads(read_bytes(target))
    except (json.JSONDecodeError, OSError) as e:
        log.warning("Failed to read sidecar %s: %s", target, e)
        return None
    version = d.get("version")
    if not isinstance(version, int) or version < 1:
        log.warning("Invalid sidecar version in %s: %s", target, version)
        return None
    if version > SIDECAR_VERSION:
        raise UnsupportedSidecarVersion(str(target), version)
    return RegenMeta(
        version=version,
        content_hash=d.get("content_hash"),
        summary_hash=d.get("summary_hash"),
        structure_hash=d.get("structure_hash"),
        last_regen_utc=d.get("last_regen_utc"),
    )


def read_all_regen_meta(insights_root: Path) -> dict[str, RegenMeta]:
    """Walk knowledge/ and return {knowledge_path: RegenMeta} for all insight-state files."""
    result: dict[str, RegenMeta] = {}
    if not path_is_dir(insights_root):
        return result
    for sidecar_path in rglob_paths(insights_root, SIDECAR_FILENAME):
        parts = sidecar_path.relative_to(insights_root).parts
        if len(parts) < 3 or parts[-3:] != (".brain-sync", "insights", SIDECAR_FILENAME):
            continue
        area_parts = parts[:-3]
        knowledge_path = "/".join(area_parts)
        try:
            meta = read_regen_meta(sidecar_path.parent)
            if meta is not None:
                result[knowledge_path] = meta
        except UnsupportedSidecarVersion:
            raise
    return result


def delete_regen_meta(insights_dir: Path) -> None:
    """Delete a .regen-meta.json sidecar. No-op if missing."""
    target = insights_dir / SIDECAR_FILENAME
    if path_exists(target):
        target.unlink()
        log.debug("Deleted sidecar %s", target)


def load_regen_hashes(root: Path, knowledge_path: str) -> RegenMeta | None:
    """Read regen hashes from the co-located insight-state file."""
    return read_regen_meta(area_insight_state_path(root, knowledge_path).parent)

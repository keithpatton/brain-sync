"""Insight sidecar read/write utilities.

Each insights folder has a `.regen-meta.json` sidecar that persists the
three regen hashes (content_hash, summary_hash, structure_hash) to the
filesystem.  Sidecars are the authoritative source for regen hashes,
with DB fallback for pre-Phase-5 data that lacks sidecars.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from brain_sync.fileops import atomic_write_bytes

log = logging.getLogger(__name__)

SIDECAR_FILENAME = ".regen-meta.json"
SIDECAR_VERSION = 1


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
    if not target.exists():
        return None
    try:
        d = json.loads(target.read_bytes())
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
    """Walk insights/ and return {knowledge_path: RegenMeta} for all sidecars."""
    result: dict[str, RegenMeta] = {}
    if not insights_root.is_dir():
        return result
    for sidecar_path in insights_root.rglob(SIDECAR_FILENAME):
        rel = sidecar_path.parent.relative_to(insights_root)
        knowledge_path = str(rel).replace("\\", "/")
        if knowledge_path == ".":
            knowledge_path = ""
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
    if target.exists():
        target.unlink()
        log.debug("Deleted sidecar %s", target)


def load_regen_hashes(root: Path, knowledge_path: str) -> RegenMeta | None:
    """Read regen hashes from sidecar first, fall back to DB insight_state.

    This is the authoritative read path for regen hash comparison.
    Sidecars are the primary source; DB is a fallback for pre-Phase-5
    data that was never exported to sidecars.
    """
    insights_dir = root / "insights" / knowledge_path if knowledge_path else root / "insights"
    meta = read_regen_meta(insights_dir)
    if meta is not None:
        return meta
    # Fallback: read from DB (pre-Phase-4 data without sidecars)
    from brain_sync.state import load_insight_state

    istate = load_insight_state(root, knowledge_path)
    if istate is None or not istate.content_hash:
        return None
    return RegenMeta(
        content_hash=istate.content_hash,
        summary_hash=istate.summary_hash,
        structure_hash=istate.structure_hash,
        last_regen_utc=istate.last_regen_utc,
    )


def synchronize_sidecars_from_db(root: Path) -> int:
    """Ensure all sidecars are synchronized from DB authority.

    For each insight_state row with non-null hashes:
    - If sidecar missing: write from DB values
    - If sidecar exists but hashes disagree with DB: overwrite from DB values
    - If sidecar matches DB: no-op

    This is a transitional function used during the Phase 5a authority
    transfer.  After Phase 5b (v21 migration drops insight_state), this
    becomes a no-op and is removed in Phase 6.

    Returns count of sidecars written/repaired.
    """
    from brain_sync.state import load_all_insight_states

    all_states = load_all_insight_states(root)
    repaired = 0
    for istate in all_states:
        if not istate.content_hash:
            continue
        kp = istate.knowledge_path
        insights_dir = root / "insights" / kp if kp else root / "insights"
        if not insights_dir.is_dir():
            continue
        existing = read_regen_meta(insights_dir)
        db_meta = RegenMeta(
            content_hash=istate.content_hash,
            summary_hash=istate.summary_hash,
            structure_hash=istate.structure_hash,
            last_regen_utc=istate.last_regen_utc,
        )
        if existing is None or (
            existing.content_hash != db_meta.content_hash
            or existing.summary_hash != db_meta.summary_hash
            or existing.structure_hash != db_meta.structure_hash
        ):
            write_regen_meta(insights_dir, db_meta)
            repaired += 1
    log.info("Sidecar synchronization: %d repaired/written", repaired)
    return repaired

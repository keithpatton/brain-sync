"""Application-owned insight state projection and orchestration helpers."""

from __future__ import annotations

from pathlib import Path

from brain_sync.application.state_models import InsightState
from brain_sync.brain.layout import area_insights_dir, knowledge_root
from brain_sync.brain.repository import BrainRepository
from brain_sync.brain.sidecar import read_all_regen_meta, read_regen_meta
from brain_sync.brain.tree import normalize_path
from brain_sync.runtime.repository import (
    RegenLock,
    delete_regen_lock,
    load_all_regen_locks,
    load_regen_lock,
    save_regen_lock,
)

__all__ = [
    "InsightState",
    "delete_insight_state",
    "load_all_insight_states",
    "load_insight_state",
    "save_insight_state",
]


def _to_insight_state(meta, lock: RegenLock | None, knowledge_path: str) -> InsightState:
    return InsightState(
        knowledge_path=knowledge_path,
        content_hash=meta.content_hash if meta else None,
        summary_hash=meta.summary_hash if meta else None,
        structure_hash=meta.structure_hash if meta else None,
        regen_started_utc=lock.regen_started_utc if lock else None,
        last_regen_utc=meta.last_regen_utc if meta else None,
        regen_status=lock.regen_status if lock else "idle",
        owner_id=lock.owner_id if lock else None,
        error_reason=lock.error_reason if lock else None,
    )


def load_insight_state(root: Path, knowledge_path: str) -> InsightState | None:
    """Return merged portable + runtime insight state for one knowledge path."""
    normalized_path = normalize_path(knowledge_path)
    lock = load_regen_lock(root, normalized_path)
    meta = read_regen_meta(area_insights_dir(root, normalized_path))
    if lock is None and meta is None:
        return None
    return _to_insight_state(meta, lock, normalized_path)


def load_all_insight_states(root: Path) -> list[InsightState]:
    """Return merged portable + runtime insight state for all known knowledge paths."""
    all_meta = read_all_regen_meta(knowledge_root(root))
    locks_by_path = {lock.knowledge_path: lock for lock in load_all_regen_locks(root)}

    result: list[InsightState] = []
    for knowledge_path in set(all_meta.keys()) | set(locks_by_path.keys()):
        result.append(
            _to_insight_state(
                all_meta.get(knowledge_path),
                locks_by_path.get(knowledge_path),
                knowledge_path,
            )
        )
    return result


def save_insight_state(root: Path, insight_state: InsightState) -> None:
    """Persist portable insight hashes and runtime lifecycle as one application workflow."""
    normalized_path = normalize_path(insight_state.knowledge_path)

    if insight_state.content_hash is not None:
        BrainRepository(root).save_portable_insight_state(
            normalized_path,
            content_hash=insight_state.content_hash,
            summary_hash=insight_state.summary_hash,
            structure_hash=insight_state.structure_hash,
            last_regen_utc=insight_state.last_regen_utc,
        )

    save_regen_lock(
        root,
        RegenLock(
            knowledge_path=normalized_path,
            regen_status=insight_state.regen_status,
            regen_started_utc=insight_state.regen_started_utc,
            owner_id=insight_state.owner_id,
            error_reason=insight_state.error_reason,
        ),
    )


def delete_insight_state(root: Path, knowledge_path: str) -> None:
    """Delete portable insight state and runtime lifecycle for a knowledge path."""
    normalized_path = normalize_path(knowledge_path)
    BrainRepository(root).delete_portable_insight_state(normalized_path)
    delete_regen_lock(root, normalized_path)

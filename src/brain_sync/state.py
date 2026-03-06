from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from brain_sync.fileops import atomic_write_bytes

log = logging.getLogger(__name__)

STATE_FILENAME = ".sync-state.json"
STATE_VERSION = 1


@dataclass
class SourceState:
    manifest_path: str
    source_url: str
    target_file: str
    source_type: str
    last_checked_utc: str | None = None
    last_changed_utc: str | None = None
    current_interval_secs: int = 3600
    content_hash: str | None = None
    metadata_fingerprint: str | None = None


@dataclass
class SyncState:
    version: int = STATE_VERSION
    sources: dict[str, SourceState] = field(default_factory=dict)


def source_key(manifest_path: str, source_url: str) -> str:
    return f"{manifest_path}::{source_url}"


def load_state(root: Path) -> SyncState:
    state_path = root / STATE_FILENAME
    if not state_path.exists():
        return SyncState()
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        sources = {}
        for key, val in data.get("sources", {}).items():
            sources[key] = SourceState(**val)
        return SyncState(version=data.get("version", STATE_VERSION), sources=sources)
    except Exception as e:
        log.warning("Corrupt sync state, starting fresh: %s", e)
        return SyncState()


def save_state(root: Path, state: SyncState) -> None:
    state_path = root / STATE_FILENAME
    data = {
        "version": state.version,
        "sources": {k: asdict(v) for k, v in state.sources.items()},
    }
    content = json.dumps(data, indent=2, sort_keys=True).encode("utf-8")
    atomic_write_bytes(state_path, content)


def prune_state(state: SyncState, active_keys: set[str]) -> None:
    stale = [k for k in state.sources if k not in active_keys]
    for k in stale:
        del state.sources[k]
        log.info("Pruned state for removed source: %s", k)

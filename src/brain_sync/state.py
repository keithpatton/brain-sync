from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

STATE_FILENAME = ".sync-state.sqlite"
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    source_key TEXT PRIMARY KEY,
    manifest_path TEXT NOT NULL,
    source_url TEXT NOT NULL,
    target_file TEXT NOT NULL,
    source_type TEXT NOT NULL,
    last_checked_utc TEXT,
    last_changed_utc TEXT,
    current_interval_secs INTEGER NOT NULL DEFAULT 3600,
    content_hash TEXT,
    metadata_fingerprint TEXT
);
"""


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
    version: int = SCHEMA_VERSION
    sources: dict[str, SourceState] = field(default_factory=dict)


def source_key(manifest_path: str, source_url: str) -> str:
    return f"{manifest_path}::{source_url}"


def _db_path(root: Path) -> Path:
    return root / STATE_FILENAME


def _connect(root: Path) -> sqlite3.Connection:
    db = _db_path(root)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()
    return conn


def load_state(root: Path) -> SyncState:
    try:
        conn = _connect(root)
    except Exception as e:
        log.warning("Cannot open sync state DB, starting fresh: %s", e)
        return SyncState()

    state = SyncState()
    try:
        rows = conn.execute(
            "SELECT source_key, manifest_path, source_url, target_file, source_type, "
            "last_checked_utc, last_changed_utc, current_interval_secs, "
            "content_hash, metadata_fingerprint FROM sources"
        ).fetchall()
        for row in rows:
            state.sources[row[0]] = SourceState(
                manifest_path=row[1],
                source_url=row[2],
                target_file=row[3],
                source_type=row[4],
                last_checked_utc=row[5],
                last_changed_utc=row[6],
                current_interval_secs=row[7],
                content_hash=row[8],
                metadata_fingerprint=row[9],
            )
    except Exception as e:
        log.warning("Error reading sync state, starting fresh: %s", e)
        state = SyncState()
    finally:
        conn.close()

    return state


def save_state(root: Path, state: SyncState) -> None:
    conn = _connect(root)
    try:
        for key, ss in state.sources.items():
            conn.execute(
                "INSERT OR REPLACE INTO sources "
                "(source_key, manifest_path, source_url, target_file, source_type, "
                "last_checked_utc, last_changed_utc, current_interval_secs, "
                "content_hash, metadata_fingerprint) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    key,
                    ss.manifest_path,
                    ss.source_url,
                    ss.target_file,
                    ss.source_type,
                    ss.last_checked_utc,
                    ss.last_changed_utc,
                    ss.current_interval_secs,
                    ss.content_hash,
                    ss.metadata_fingerprint,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def prune_state(state: SyncState, active_keys: set[str]) -> None:
    stale = [k for k in state.sources if k not in active_keys]
    for k in stale:
        del state.sources[k]
        log.info("Pruned state for removed source: %s", k)


def prune_db(root: Path, active_keys: set[str]) -> None:
    """Remove rows from the DB that are no longer active."""
    conn = _connect(root)
    try:
        existing = {
            row[0] for row in conn.execute("SELECT source_key FROM sources").fetchall()
        }
        stale = existing - active_keys
        for key in stale:
            conn.execute("DELETE FROM sources WHERE source_key = ?", (key,))
            log.info("Pruned DB row for removed source: %s", key)
        if stale:
            conn.commit()
    finally:
        conn.close()

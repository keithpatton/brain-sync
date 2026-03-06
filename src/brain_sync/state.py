from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

STATE_FILENAME = ".sync-state.sqlite"
SCHEMA_VERSION = 2

_SCHEMA_V1 = """
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

_SCHEMA_V2_ADDITIONS = """
CREATE TABLE IF NOT EXISTS documents (
    canonical_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    last_checked_utc TEXT,
    last_changed_utc TEXT,
    content_hash TEXT,
    metadata_fingerprint TEXT,
    mime_type TEXT
);

CREATE TABLE IF NOT EXISTS relationships (
    parent_canonical_id TEXT NOT NULL,
    canonical_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    local_path TEXT NOT NULL,
    source_type TEXT NOT NULL,
    first_seen_utc TEXT,
    last_seen_utc TEXT,
    PRIMARY KEY (parent_canonical_id, canonical_id)
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
    next_check_utc: str | None = None
    interval_seconds: int | None = None


@dataclass
class SyncState:
    version: int = SCHEMA_VERSION
    sources: dict[str, SourceState] = field(default_factory=dict)


@dataclass
class DocumentState:
    canonical_id: str
    source_type: str
    url: str
    title: str | None = None
    last_checked_utc: str | None = None
    last_changed_utc: str | None = None
    content_hash: str | None = None
    metadata_fingerprint: str | None = None
    mime_type: str | None = None


@dataclass
class Relationship:
    parent_canonical_id: str
    canonical_id: str
    relationship_type: str
    local_path: str
    source_type: str
    first_seen_utc: str | None = None
    last_seen_utc: str | None = None


def source_key(manifest_path: str, source_url: str) -> str:
    return f"{manifest_path}::{source_url}"


def _db_path(root: Path) -> Path:
    return root / STATE_FILENAME


def _migrate(conn: sqlite3.Connection, from_version: int) -> None:
    """Run migrations from from_version to SCHEMA_VERSION."""
    if from_version < 2:
        conn.executescript(_SCHEMA_V2_ADDITIONS)
        # Add new columns to sources table
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(sources)").fetchall()
        }
        if "next_check_utc" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN next_check_utc TEXT")
        if "interval_seconds" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN interval_seconds INTEGER")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        log.info("Migrated DB schema from v%d to v%d", from_version, SCHEMA_VERSION)


def _connect(root: Path) -> sqlite3.Connection:
    db = _db_path(root)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # Ensure base schema exists
    conn.executescript(_SCHEMA_V1)
    conn.execute(
        "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', '1')",
    )
    conn.commit()
    # Check version and migrate if needed
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    current_version = int(row[0]) if row else 1
    if current_version < SCHEMA_VERSION:
        _migrate(conn, current_version)
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
            "content_hash, metadata_fingerprint, next_check_utc, interval_seconds "
            "FROM sources"
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
                next_check_utc=row[10],
                interval_seconds=row[11],
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
                "content_hash, metadata_fingerprint, next_check_utc, interval_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    ss.next_check_utc,
                    ss.interval_seconds,
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


# --- Document & Relationship operations ---


def save_document(root: Path, doc: DocumentState) -> None:
    """UPSERT a document record."""
    conn = _connect(root)
    try:
        conn.execute(
            "INSERT INTO documents "
            "(canonical_id, source_type, url, title, last_checked_utc, "
            "last_changed_utc, content_hash, metadata_fingerprint, mime_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(canonical_id) DO UPDATE SET "
            "source_type=excluded.source_type, url=excluded.url, title=excluded.title, "
            "last_checked_utc=excluded.last_checked_utc, "
            "last_changed_utc=excluded.last_changed_utc, "
            "content_hash=excluded.content_hash, "
            "metadata_fingerprint=excluded.metadata_fingerprint, "
            "mime_type=excluded.mime_type",
            (
                doc.canonical_id,
                doc.source_type,
                doc.url,
                doc.title,
                doc.last_checked_utc,
                doc.last_changed_utc,
                doc.content_hash,
                doc.metadata_fingerprint,
                doc.mime_type,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_document(root: Path, canonical_id: str) -> DocumentState | None:
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT canonical_id, source_type, url, title, last_checked_utc, "
            "last_changed_utc, content_hash, metadata_fingerprint, mime_type "
            "FROM documents WHERE canonical_id = ?",
            (canonical_id,),
        ).fetchone()
        if row is None:
            return None
        return DocumentState(
            canonical_id=row[0],
            source_type=row[1],
            url=row[2],
            title=row[3],
            last_checked_utc=row[4],
            last_changed_utc=row[5],
            content_hash=row[6],
            metadata_fingerprint=row[7],
            mime_type=row[8],
        )
    finally:
        conn.close()


def save_relationship(root: Path, rel: Relationship) -> None:
    """UPSERT a relationship record."""
    conn = _connect(root)
    try:
        conn.execute(
            "INSERT INTO relationships "
            "(parent_canonical_id, canonical_id, relationship_type, local_path, "
            "source_type, first_seen_utc, last_seen_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(parent_canonical_id, canonical_id) DO UPDATE SET "
            "relationship_type=excluded.relationship_type, "
            "local_path=excluded.local_path, "
            "source_type=excluded.source_type, "
            "last_seen_utc=excluded.last_seen_utc",
            (
                rel.parent_canonical_id,
                rel.canonical_id,
                rel.relationship_type,
                rel.local_path,
                rel.source_type,
                rel.first_seen_utc,
                rel.last_seen_utc,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_relationships_for_primary(
    root: Path, parent_canonical_id: str
) -> list[Relationship]:
    conn = _connect(root)
    try:
        rows = conn.execute(
            "SELECT parent_canonical_id, canonical_id, relationship_type, local_path, "
            "source_type, first_seen_utc, last_seen_utc "
            "FROM relationships WHERE parent_canonical_id = ?",
            (parent_canonical_id,),
        ).fetchall()
        return [
            Relationship(
                parent_canonical_id=r[0],
                canonical_id=r[1],
                relationship_type=r[2],
                local_path=r[3],
                source_type=r[4],
                first_seen_utc=r[5],
                last_seen_utc=r[6],
            )
            for r in rows
        ]
    finally:
        conn.close()


def update_relationship_path(
    root: Path, parent_canonical_id: str, canonical_id: str, new_local_path: str,
) -> None:
    """Update the local_path for a relationship after file rediscovery."""
    conn = _connect(root)
    try:
        conn.execute(
            "UPDATE relationships SET local_path = ? "
            "WHERE parent_canonical_id = ? AND canonical_id = ?",
            (new_local_path, parent_canonical_id, canonical_id),
        )
        conn.commit()
    finally:
        conn.close()


def remove_relationship(
    root: Path, parent_canonical_id: str, canonical_id: str
) -> None:
    conn = _connect(root)
    try:
        conn.execute(
            "DELETE FROM relationships "
            "WHERE parent_canonical_id = ? AND canonical_id = ?",
            (parent_canonical_id, canonical_id),
        )
        conn.commit()
    finally:
        conn.close()


def count_relationships_for_doc(root: Path, canonical_id: str) -> int:
    """Count how many relationships reference a document (across all parents)."""
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM relationships WHERE canonical_id = ?",
            (canonical_id,),
        ).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def remove_document_if_orphaned(root: Path, canonical_id: str) -> bool:
    """Remove a document only if no relationships reference it. Returns True if removed."""
    if count_relationships_for_doc(root, canonical_id) > 0:
        return False
    conn = _connect(root)
    try:
        conn.execute(
            "DELETE FROM documents WHERE canonical_id = ?", (canonical_id,)
        )
        conn.commit()
        return True
    finally:
        conn.close()

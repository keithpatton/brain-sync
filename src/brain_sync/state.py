from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from brain_sync.manifest import SourceManifest

from brain_sync.fs_utils import normalize_path

log = logging.getLogger(__name__)

STATE_FILENAME = ".sync-state.sqlite"
SCHEMA_VERSION = 21

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

# --- DDL used by v4->v5 migration only ---

_INSIGHT_STATE_DDL = """
CREATE TABLE IF NOT EXISTS insight_state (
    knowledge_path TEXT PRIMARY KEY,
    content_hash TEXT,
    summary_hash TEXT,
    structure_hash TEXT,
    regen_started_utc TEXT,
    last_regen_utc TEXT,
    regen_status TEXT NOT NULL DEFAULT 'idle',
    owner_id TEXT,
    error_reason TEXT
);
"""

_TOKEN_EVENTS_DDL = """
CREATE TABLE IF NOT EXISTS token_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK(operation_type IN ('regen','query','classify')),
    resource_type TEXT,
    resource_id TEXT,
    is_chunk INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    duration_ms INTEGER,
    num_turns INTEGER,
    success INTEGER NOT NULL CHECK(success IN (0,1)),
    created_utc TEXT NOT NULL
);

CREATE INDEX idx_token_events_session ON token_events(session_id);
CREATE INDEX idx_token_events_resource ON token_events(resource_type, resource_id)
    WHERE resource_type IS NOT NULL;
CREATE INDEX idx_token_events_resource_session
    ON token_events(resource_type, resource_id, session_id)
    WHERE resource_type IS NOT NULL;
"""

_DOCUMENTS_DDL = """
CREATE TABLE IF NOT EXISTS documents (
    canonical_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    last_checked_utc TEXT,
    last_changed_utc TEXT,
    content_hash TEXT,
    metadata_fingerprint TEXT,
    mime_type TEXT
);
"""

_RELATIONSHIPS_DDL = """
CREATE TABLE IF NOT EXISTS relationships (
    parent_canonical_id TEXT NOT NULL,
    canonical_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    source_type TEXT NOT NULL,
    first_seen_utc TEXT,
    last_seen_utc TEXT,
    PRIMARY KEY (parent_canonical_id, canonical_id)
);
"""

_DAEMON_STATUS_DDL = """
CREATE TABLE IF NOT EXISTS daemon_status (
    pid       INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    status     TEXT NOT NULL
);
"""

_SYNC_CACHE_DDL = """
CREATE TABLE IF NOT EXISTS sync_cache (
    canonical_id TEXT PRIMARY KEY,
    last_checked_utc TEXT,
    last_changed_utc TEXT,
    current_interval_secs INTEGER NOT NULL DEFAULT 1800,
    content_hash TEXT,
    metadata_fingerprint TEXT,
    next_check_utc TEXT,
    interval_seconds INTEGER
);
"""

_REGEN_LOCKS_DDL = """
CREATE TABLE IF NOT EXISTS regen_locks (
    knowledge_path TEXT PRIMARY KEY,
    regen_status TEXT NOT NULL DEFAULT 'idle',
    regen_started_utc TEXT,
    owner_id TEXT,
    error_reason TEXT
);
"""

## source_bindings removed in v5 — each source has one target_path in sources table

# --- DDL used only during migrations from older schemas ---

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
    source_type TEXT NOT NULL,
    first_seen_utc TEXT,
    last_seen_utc TEXT,
    PRIMARY KEY (parent_canonical_id, canonical_id)
);
"""

_MIGRATION_V3_SOURCES = """
CREATE TABLE IF NOT EXISTS sources_v3 (
    canonical_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    last_checked_utc TEXT,
    last_changed_utc TEXT,
    current_interval_secs INTEGER NOT NULL DEFAULT 1800,
    content_hash TEXT,
    metadata_fingerprint TEXT,
    next_check_utc TEXT,
    interval_seconds INTEGER
);
"""

_MIGRATION_V3_BINDINGS = """
CREATE TABLE IF NOT EXISTS source_bindings (
    canonical_id TEXT NOT NULL,
    manifest_path TEXT NOT NULL,
    target_file TEXT NOT NULL,
    include_links INTEGER NOT NULL DEFAULT 0,
    include_children INTEGER NOT NULL DEFAULT 0,
    include_attachments INTEGER NOT NULL DEFAULT 0,
    link_depth INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (canonical_id, manifest_path)
);
"""


class _PathNormalized:
    """Mixin that auto-normalizes path fields on assignment.

    Subclasses declare which fields are path fields via _PATH_FIELDS.
    Works on both construction and mutation.
    """

    _PATH_FIELDS: ClassVar[set[str]] = set()

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._PATH_FIELDS and isinstance(value, str | PathLike):
            value = normalize_path(str(value))
        super().__setattr__(name, value)


@dataclass
class SourceState(_PathNormalized):
    _PATH_FIELDS: ClassVar[set[str]] = {"target_path"}

    canonical_id: str
    source_url: str
    source_type: str
    last_checked_utc: str | None = None
    last_changed_utc: str | None = None
    current_interval_secs: int = 1800
    content_hash: str | None = None
    metadata_fingerprint: str | None = None
    next_check_utc: str | None = None
    interval_seconds: int | None = None
    target_path: str = ""
    fetch_children: bool = False
    sync_attachments: bool = False
    child_path: str | None = None


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
class InsightState(_PathNormalized):
    _PATH_FIELDS: ClassVar[set[str]] = {"knowledge_path"}

    knowledge_path: str
    content_hash: str | None = None
    summary_hash: str | None = None
    structure_hash: str | None = None
    regen_started_utc: str | None = None
    last_regen_utc: str | None = None
    regen_status: str = "idle"
    owner_id: str | None = None
    error_reason: str | None = None


@dataclass
class RegenLock(_PathNormalized):
    """Lifecycle-only regen state stored in regen_locks table (v21+)."""

    _PATH_FIELDS: ClassVar[set[str]] = {"knowledge_path"}

    knowledge_path: str
    regen_status: str = "idle"
    regen_started_utc: str | None = None
    owner_id: str | None = None
    error_reason: str | None = None


@dataclass
class Relationship:
    parent_canonical_id: str
    canonical_id: str
    relationship_type: str
    source_type: str
    first_seen_utc: str | None = None
    last_seen_utc: str | None = None


def _db_path(root: Path) -> Path:
    return root / STATE_FILENAME


def _compute_canonical_id_from_row(source_type: str, source_url: str) -> str:
    """Compute canonical_id for migration. Falls back to unknown:{url} on failure."""
    try:
        from brain_sync.sources import SourceType, canonical_id

        stype = SourceType(source_type)
        return canonical_id(stype, source_url)
    except (ValueError, KeyError):
        return f"unknown:{source_url}"


def _migrate(conn: sqlite3.Connection, from_version: int, root: Path | None = None) -> None:
    """Run migrations from from_version to SCHEMA_VERSION."""
    if from_version < 2:
        conn.executescript(_SCHEMA_V2_ADDITIONS)
        # Add new columns to sources table (v1 -> v2)
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
        if "next_check_utc" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN next_check_utc TEXT")
        if "interval_seconds" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN interval_seconds INTEGER")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '2')",
        )
        conn.commit()
        log.info("Migrated DB schema from v%d to v2", from_version)
        from_version = 2

    if from_version < 3:
        # Create new sources table with canonical_id PK
        conn.executescript(_MIGRATION_V3_SOURCES)
        conn.executescript(_MIGRATION_V3_BINDINGS)

        # Migrate data from old sources table
        rows = conn.execute(
            "SELECT source_key, manifest_path, source_url, target_file, source_type, "
            "last_checked_utc, last_changed_utc, current_interval_secs, "
            "content_hash, metadata_fingerprint, next_check_utc, interval_seconds "
            "FROM sources"
        ).fetchall()

        # Group by canonical_id for conflict resolution
        by_cid: dict[str, list[tuple]] = {}
        for row in rows:
            source_type = row[4]
            source_url = row[2]
            cid = _compute_canonical_id_from_row(source_type, source_url)
            by_cid.setdefault(cid, []).append(row)

        for cid, group in by_cid.items():
            # Deterministic conflict resolution:
            # 1. Prefer most recent last_checked_utc (descending)
            # 2. If tied, prefer non-null content_hash
            # 3. If still tied, prefer smallest manifest_path (ascending)
            best = max(group, key=lambda r: (r[5] or "", r[8] is not None))
            candidates = [
                r for r in group if (r[5] or "") == (best[5] or "") and (r[8] is not None) == (best[8] is not None)
            ]
            candidates.sort(key=lambda r: r[1])  # lexicographic manifest_path
            winner = candidates[0]

            conn.execute(
                "INSERT OR IGNORE INTO sources_v3 "
                "(canonical_id, source_url, source_type, last_checked_utc, "
                "last_changed_utc, current_interval_secs, content_hash, "
                "metadata_fingerprint, next_check_utc, interval_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cid,
                    winner[2],  # source_url
                    winner[4],  # source_type
                    winner[5],  # last_checked_utc
                    winner[6],  # last_changed_utc
                    winner[7],  # current_interval_secs
                    winner[8],  # content_hash
                    winner[9],  # metadata_fingerprint
                    winner[10],  # next_check_utc
                    winner[11],  # interval_seconds
                ),
            )

            # All rows create bindings
            for r in group:
                conn.execute(
                    "INSERT OR IGNORE INTO source_bindings (canonical_id, manifest_path, target_file) VALUES (?, ?, ?)",
                    (cid, r[1], r[3]),
                )

        # Drop old sources table and rename
        conn.execute("DROP TABLE IF EXISTS sources")
        conn.execute("ALTER TABLE sources_v3 RENAME TO sources")

        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '3')",
        )
        conn.commit()
        log.info("Migrated DB schema from v%d to v3", from_version)
        from_version = 3

    if from_version < 4:
        # v3 → v4: Add FK CASCADE on relationships, UNIQUE(url) on documents

        # Add UNIQUE constraint on documents.url
        # Deduplicate first (shouldn't happen, but be safe)
        conn.execute("""
            DELETE FROM documents WHERE rowid NOT IN (
                SELECT MIN(rowid) FROM documents GROUP BY url
            )
        """)
        # Recreate documents with UNIQUE(url)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS documents_v4 (
                canonical_id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                url TEXT NOT NULL UNIQUE,
                title TEXT,
                last_checked_utc TEXT,
                last_changed_utc TEXT,
                content_hash TEXT,
                metadata_fingerprint TEXT,
                mime_type TEXT
            )
        """)
        conn.execute("INSERT OR IGNORE INTO documents_v4 SELECT * FROM documents")
        conn.execute("DROP TABLE IF EXISTS documents")
        conn.execute("ALTER TABLE documents_v4 RENAME TO documents")

        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '4')",
        )
        conn.commit()
        log.info("Migrated DB schema from v%d to v4", from_version)
        from_version = 4

    if from_version < 5:
        # v4 → v5: Add target_path + context flags to sources, add insight_state,
        # drop source_bindings
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
        if "target_path" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN target_path TEXT NOT NULL DEFAULT ''")
        if "include_links" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN include_links INTEGER NOT NULL DEFAULT 0")
        if "include_children" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN include_children INTEGER NOT NULL DEFAULT 0")
        if "include_attachments" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN include_attachments INTEGER NOT NULL DEFAULT 0")

        # Migrate bindings data into sources if bindings table exists
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "source_bindings" in tables:
            # For each source, pick the first binding's flags and derive target_path
            rows = conn.execute(
                "SELECT canonical_id, manifest_path, target_file, "
                "include_links, include_children, include_attachments "
                "FROM source_bindings"
            ).fetchall()
            seen: set[str] = set()
            for r in rows:
                cid = r[0]
                if cid in seen:
                    continue
                seen.add(cid)
                # Derive target_path from manifest_path's parent directory
                manifest_path = Path(r[1])
                try:
                    if root is not None:
                        target_path = str(manifest_path.parent.relative_to(root))
                        from brain_sync.fs_utils import normalize_path

                        target_path = normalize_path(target_path)
                    else:
                        target_path = ""
                except ValueError:
                    target_path = ""
                conn.execute(
                    "UPDATE sources SET target_path = ?, include_links = ?, "
                    "include_children = ?, include_attachments = ? "
                    "WHERE canonical_id = ?",
                    (target_path, r[3], r[4], r[5], cid),
                )
            conn.execute("DROP TABLE IF EXISTS source_bindings")

        # Create insight_state table
        conn.executescript(_INSIGHT_STATE_DDL)

        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '5')",
        )
        conn.commit()
        log.info("Migrated DB schema from v%d to v5", from_version)
        from_version = 5

    if from_version < 6:
        # v5 → v6: Add regen timing and token tracking to insight_state
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        if "regen_started_utc" not in existing_cols:
            conn.execute("ALTER TABLE insight_state ADD COLUMN regen_started_utc TEXT")
        if "input_tokens" not in existing_cols:
            conn.execute("ALTER TABLE insight_state ADD COLUMN input_tokens INTEGER")
        if "output_tokens" not in existing_cols:
            conn.execute("ALTER TABLE insight_state ADD COLUMN output_tokens INTEGER")

        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '6')",
        )
        conn.commit()
        from_version = 6

    if from_version < 7:
        # v6 → v7: Add num_turns and model to insight_state
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        if "num_turns" not in existing_cols:
            conn.execute("ALTER TABLE insight_state ADD COLUMN num_turns INTEGER")
        if "model" not in existing_cols:
            conn.execute("ALTER TABLE insight_state ADD COLUMN model TEXT")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '7')",
        )
        conn.commit()
        from_version = 7

    if from_version < 8:
        # v7 → v8: Drop cost_usd column
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        if "cost_usd" in existing_cols:
            conn.execute("ALTER TABLE insight_state DROP COLUMN cost_usd")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '8')",
        )
        conn.commit()
        from_version = 8

    if from_version < 9:
        # v8 → v9: Drop retry_count (queue now owns retry budgeting)
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        if "retry_count" in existing_cols:
            conn.execute("ALTER TABLE insight_state DROP COLUMN retry_count")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '9')",
        )
        conn.commit()
        from_version = 9

    if from_version < 10:
        # v9 → v10: Normalize all path separators (backslash → forward slash).
        # Use OR IGNORE on updates because multiple rows can collide after
        # normalisation; cleanup steps remove any leftover stale rows.
        bs = "\\"

        # insight_state: delete backslash duplicates that clash with existing
        # forward-slash rows, then normalize the rest
        conn.execute(
            "DELETE FROM insight_state WHERE knowledge_path LIKE ? "
            "AND REPLACE(knowledge_path, ?, '/') IN "
            "(SELECT knowledge_path FROM insight_state WHERE knowledge_path NOT LIKE ?)",
            (f"%{bs}%", bs, f"%{bs}%"),
        )
        conn.execute(
            "UPDATE OR IGNORE insight_state SET knowledge_path = REPLACE(knowledge_path, ?, '/')",
            (bs,),
        )
        # Delete rows whose backslash form was skipped by OR IGNORE
        conn.execute(
            "DELETE FROM insight_state WHERE knowledge_path LIKE ?",
            (f"%{bs}%",),
        )
        # Strip accidental 'knowledge/' prefix
        conn.execute(
            "UPDATE OR IGNORE insight_state SET knowledge_path = SUBSTR(knowledge_path, 11) "
            "WHERE knowledge_path LIKE 'knowledge/%'"
        )
        conn.execute("DELETE FROM insight_state WHERE knowledge_path LIKE 'knowledge/%'")
        # Deduplicate any remaining collisions
        conn.execute("""
            DELETE FROM insight_state WHERE rowid NOT IN (
                SELECT MAX(rowid) FROM insight_state GROUP BY knowledge_path
            )
        """)

        # sources: normalize target_path
        conn.execute(
            "UPDATE sources SET target_path = REPLACE(target_path, ?, '/')",
            (bs,),
        )

        # relationships: normalize local_path (column may not exist on fresh DBs post-v17)
        rel_cols = {row[1] for row in conn.execute("PRAGMA table_info(relationships)").fetchall()}
        if "local_path" in rel_cols:
            conn.execute(
                "UPDATE relationships SET local_path = REPLACE(local_path, ?, '/')",
                (bs,),
            )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '10')",
        )
        conn.commit()
        log.info("Normalized knowledge_path separators in insight_state")
        from_version = 10

    if from_version < 11:
        # v10 → v11: Add owner_id and error_reason to insight_state
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        if "owner_id" not in existing_cols:
            conn.execute("ALTER TABLE insight_state ADD COLUMN owner_id TEXT")
        if "error_reason" not in existing_cols:
            conn.execute("ALTER TABLE insight_state ADD COLUMN error_reason TEXT")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '11')",
        )
        conn.commit()
        from_version = 11

    if from_version < 12:
        # v11 → v12: Re-run backslash normalization for paths that escaped v10.
        # Use OR IGNORE on updates because multiple rows can collide after
        # normalisation (e.g. 'knowledge/a\b' → 'knowledge/a/b' → 'a/b'
        # may clash with an existing 'a/b').  The dedup step at the end
        # removes any leftover duplicates.
        bs = "\\"
        conn.execute(
            "DELETE FROM insight_state WHERE knowledge_path LIKE ? "
            "AND REPLACE(knowledge_path, ?, '/') IN "
            "(SELECT knowledge_path FROM insight_state WHERE knowledge_path NOT LIKE ?)",
            (f"%{bs}%", bs, f"%{bs}%"),
        )
        conn.execute(
            "UPDATE OR IGNORE insight_state SET knowledge_path = REPLACE(knowledge_path, ?, '/')",
            (bs,),
        )
        # Delete rows whose backslash form was skipped by OR IGNORE (they are
        # now duplicates of the already-existing forward-slash row).
        conn.execute(
            "DELETE FROM insight_state WHERE knowledge_path LIKE ?",
            (f"%{bs}%",),
        )
        conn.execute(
            "UPDATE OR IGNORE insight_state SET knowledge_path = SUBSTR(knowledge_path, 11) "
            "WHERE knowledge_path LIKE 'knowledge/%'"
        )
        # Remove any rows still carrying the prefix (collided with existing row)
        conn.execute("DELETE FROM insight_state WHERE knowledge_path LIKE 'knowledge/%'")
        conn.execute("""
            DELETE FROM insight_state WHERE rowid NOT IN (
                SELECT MAX(rowid) FROM insight_state GROUP BY knowledge_path
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '12')",
        )
        conn.commit()
        log.info("Re-normalized backslash paths in insight_state (v12)")
        from_version = 12

    if from_version < 13:
        # v12 → v13: Remove include_links, add child_path, clean up link/child relationships
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
        if "include_links" in existing_cols:
            conn.execute("ALTER TABLE sources DROP COLUMN include_links")
        if "child_path" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN child_path TEXT")

        # Delete link and child relationships + orphaned documents
        link_child_docs = conn.execute(
            "SELECT DISTINCT canonical_id FROM relationships WHERE relationship_type IN ('link', 'child')"
        ).fetchall()
        conn.execute("DELETE FROM relationships WHERE relationship_type IN ('link', 'child')")
        # Remove documents that are now orphaned (no remaining relationships)
        for (cid,) in link_child_docs:
            remaining = conn.execute("SELECT COUNT(*) FROM relationships WHERE canonical_id = ?", (cid,)).fetchone()
            if remaining and remaining[0] == 0:
                conn.execute("DELETE FROM documents WHERE canonical_id = ?", (cid,))

        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '13')",
        )
        conn.commit()
        log.info("Migrated DB schema from v%d to v13: removed links, added child_path", from_version)
        from_version = 13

    if from_version < 14:
        # v13 → v14: Rename include_children → fetch_children, include_attachments → sync_attachments
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(sources)").fetchall()}
        if "include_children" in existing_cols:
            conn.execute("ALTER TABLE sources RENAME COLUMN include_children TO fetch_children")
        if "include_attachments" in existing_cols:
            conn.execute("ALTER TABLE sources RENAME COLUMN include_attachments TO sync_attachments")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '14')",
        )
        conn.commit()
        log.info("Migrated DB schema from v%d to v14: renamed children/attachments flags", from_version)
        from_version = 14

    if from_version < 15:
        # v14 → v15: Add token_events table for invocation-level telemetry
        conn.executescript(_TOKEN_EVENTS_DDL)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '15')",
        )
        conn.commit()
        log.info("Migrated DB schema to v15: added token_events table")
        from_version = 15

    if from_version < 16:
        # v15 → v16: Remove token columns from insight_state (now tracked in token_events)
        conn.execute("ALTER TABLE insight_state RENAME TO insight_state_old")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS insight_state (
                knowledge_path TEXT PRIMARY KEY,
                content_hash TEXT,
                summary_hash TEXT,
                structure_hash TEXT,
                regen_started_utc TEXT,
                last_regen_utc TEXT,
                regen_status TEXT NOT NULL DEFAULT 'idle',
                owner_id TEXT,
                error_reason TEXT
            );
            INSERT INTO insight_state (knowledge_path, content_hash, summary_hash,
                regen_started_utc, last_regen_utc, regen_status, owner_id, error_reason)
            SELECT knowledge_path, content_hash, summary_hash,
                regen_started_utc, last_regen_utc, regen_status, owner_id, error_reason
            FROM insight_state_old;
        """)
        conn.execute("DROP TABLE insight_state_old")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '16')",
        )
        conn.commit()
        log.info("Migrated DB schema to v16: removed token columns from insight_state")
        from_version = 16

    if from_version < 17:
        # v16 → v17: Drop local_path from relationships (now computed deterministically)
        rel_cols = {row[1] for row in conn.execute("PRAGMA table_info(relationships)").fetchall()}
        if "local_path" in rel_cols:
            conn.execute("ALTER TABLE relationships DROP COLUMN local_path")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '17')",
        )
        conn.commit()
        log.info("Migrated DB schema to v17: dropped local_path from relationships")
        from_version = 17

    if from_version < 18:
        # v17 → v18: Add structure_hash to insight_state for content/structure hash split
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()}
        if "structure_hash" not in existing_cols:
            conn.execute("ALTER TABLE insight_state ADD COLUMN structure_hash TEXT")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '18')",
        )
        conn.commit()
        log.info("Migrated DB schema to v18: added structure_hash to insight_state")
        from_version = 18

    if from_version < 19:
        # v18 → v19: Reset structure_hash to re-trigger content hash backfill.
        # The v18 backfill had a bug (preserved old-algorithm content_hash).
        # NULLing structure_hash lets the corrected backfill in regen.py re-run,
        # setting content_hash to the new algorithm without any Claude calls.
        conn.execute("UPDATE insight_state SET structure_hash = NULL")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '19')",
        )
        conn.commit()
        log.info("Migrated DB schema to v19: reset structure_hash for content hash re-backfill")
        from_version = 19

    if from_version < 20:
        conn.executescript(_DAEMON_STATUS_DDL)
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '20')",
        )
        conn.commit()
        log.info("Migrated DB schema to v20: added daemon_status table")
        from_version = 20

    if from_version < 21:
        # v20 → v21: Replace insight_state with regen_locks, sources with sync_cache.
        # Sidecars become authoritative for hashes; DB becomes lifecycle-only + sync-progress.
        #
        # Step 1: Export insight_state hashes to sidecars.
        # IMPORTANT: Read directly from `conn` (the open migration connection).
        # Do NOT call synchronize_sidecars_from_db() — it calls _connect()
        # which would recurse back into _migrate().
        if root is not None:
            from brain_sync.sidecar import RegenMeta, read_regen_meta, write_regen_meta

            insight_rows = conn.execute(
                "SELECT knowledge_path, content_hash, summary_hash, "
                "structure_hash, last_regen_utc "
                "FROM insight_state WHERE content_hash IS NOT NULL"
            ).fetchall()
            sidecar_count = 0
            for kp, ch, sh, sth, lru in insight_rows:
                insights_dir = root / "insights" / kp if kp else root / "insights"
                if not insights_dir.is_dir():
                    continue
                existing = read_regen_meta(insights_dir)
                db_meta = RegenMeta(
                    content_hash=ch,
                    summary_hash=sh,
                    structure_hash=sth,
                    last_regen_utc=lru,
                )
                if existing is None or (
                    existing.content_hash != db_meta.content_hash
                    or existing.summary_hash != db_meta.summary_hash
                    or existing.structure_hash != db_meta.structure_hash
                ):
                    try:
                        write_regen_meta(insights_dir, db_meta)
                        sidecar_count += 1
                    except Exception:
                        log.warning("v20→v21: Failed to write sidecar for %s", kp, exc_info=True)
            log.info("v20→v21: Exported %d insight_state hashes to sidecars", sidecar_count)

        # Step 2: Ensure manifests exist (guard for pre-Phase-2 brains).
        if root is not None:
            manifest_dir = root / Path(".brain-sync") / "sources"
            if not manifest_dir.is_dir() or not any(manifest_dir.glob("*.json")):
                try:
                    from brain_sync.commands.sources import _bootstrap_manifests_from_db

                    # Build a minimal SyncState from DB for bootstrap
                    rows = conn.execute(
                        "SELECT canonical_id, source_url, source_type, "
                        "last_checked_utc, last_changed_utc, current_interval_secs, "
                        "content_hash, metadata_fingerprint, next_check_utc, interval_seconds, "
                        "target_path, fetch_children, sync_attachments, child_path "
                        "FROM sources"
                    ).fetchall()
                    db_sources: dict[str, SourceState] = {}
                    for r in rows:
                        db_sources[r[0]] = SourceState(
                            canonical_id=r[0],
                            source_url=r[1],
                            source_type=r[2],
                            last_checked_utc=r[3],
                            last_changed_utc=r[4],
                            current_interval_secs=r[5],
                            content_hash=r[6],
                            metadata_fingerprint=r[7],
                            next_check_utc=r[8],
                            interval_seconds=r[9],
                            target_path=r[10] or "",
                            fetch_children=bool(r[11]),
                            sync_attachments=bool(r[12]),
                            child_path=r[13],
                        )
                    if db_sources:
                        _bootstrap_manifests_from_db(root, SyncState(sources=db_sources))
                        log.info("v20→v21: Bootstrapped manifests from DB sources")
                except Exception as e:
                    log.warning("v20→v21: Failed to bootstrap manifests: %s", e)

        # Step 3: Create sync_cache from sources progress columns.
        conn.executescript(_SYNC_CACHE_DDL)
        # Check if sources table exists before copying
        if "sources" in {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
            conn.execute(
                "INSERT OR IGNORE INTO sync_cache "
                "(canonical_id, last_checked_utc, last_changed_utc, "
                "current_interval_secs, content_hash, metadata_fingerprint, "
                "next_check_utc, interval_seconds) "
                "SELECT canonical_id, last_checked_utc, last_changed_utc, "
                "current_interval_secs, content_hash, metadata_fingerprint, "
                "next_check_utc, interval_seconds "
                "FROM sources"
            )

        # Step 4: Create regen_locks from insight_state — reset all lifecycle to idle.
        conn.executescript(_REGEN_LOCKS_DDL)
        if "insight_state" in {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }:
            conn.execute(
                "INSERT OR IGNORE INTO regen_locks (knowledge_path, regen_status) "
                "SELECT knowledge_path, 'idle' FROM insight_state"
            )

        # Step 5-6: Drop old tables.
        conn.execute("DROP TABLE IF EXISTS insight_state")
        conn.execute("DROP TABLE IF EXISTS sources")

        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '21')",
        )
        conn.commit()
        log.info("Migrated DB schema to v21: replaced insight_state+sources with regen_locks+sync_cache")
        from_version = 21

    log.info("Migrated DB schema to v%d", SCHEMA_VERSION)


def _connect(root: Path) -> sqlite3.Connection:
    db = _db_path(root)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Check if DB is fresh (no tables yet)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}

    if not tables or "meta" not in tables:
        # Fresh DB — create current schema directly
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.executescript(_SYNC_CACHE_DDL)
        conn.executescript(_DOCUMENTS_DDL)
        conn.executescript(_RELATIONSHIPS_DDL)
        conn.executescript(_REGEN_LOCKS_DDL)
        conn.executescript(_TOKEN_EVENTS_DDL)
        conn.executescript(_DAEMON_STATUS_DDL)
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    else:
        # Existing DB — check version and migrate if needed
        row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        current_version = int(row[0]) if row else 1
        if current_version < SCHEMA_VERSION:
            _migrate(conn, current_version, root=root)

    return conn


def _load_db_sync_progress(root: Path) -> dict[str, SourceState]:
    """Read all sync_cache rows from the DB. Returns {canonical_id: partial SourceState}.

    The returned SourceState objects contain only sync-progress fields.
    Intent fields (source_url, source_type, target_path, flags) are empty/defaults
    and must be populated from manifests by load_state().
    """
    try:
        conn = _connect(root)
    except Exception as e:
        log.warning("Cannot open sync state DB: %s", e)
        return {}

    result: dict[str, SourceState] = {}
    try:
        rows = conn.execute(
            "SELECT canonical_id, last_checked_utc, last_changed_utc, "
            "current_interval_secs, content_hash, metadata_fingerprint, "
            "next_check_utc, interval_seconds "
            "FROM sync_cache"
        ).fetchall()
        for row in rows:
            result[row[0]] = SourceState(
                canonical_id=row[0],
                source_url="",
                source_type="",
                last_checked_utc=row[1],
                last_changed_utc=row[2],
                current_interval_secs=row[3],
                content_hash=row[4],
                metadata_fingerprint=row[5],
                next_check_utc=row[6],
                interval_seconds=row[7],
            )
    except Exception as e:
        log.warning("Error reading sync state: %s", e)
    finally:
        conn.close()

    return result


def _seed_from_hint(root: Path, m: SourceManifest, target_path: str) -> SourceState:
    """Create a SourceState from a manifest with no DB row, seeding from sync_hint if possible."""
    ss = SourceState(
        canonical_id=m.canonical_id,
        source_url=m.source_url,
        source_type=m.source_type,
        target_path=target_path,
        fetch_children=m.fetch_children,
        sync_attachments=m.sync_attachments,
        child_path=m.child_path,
    )

    # Try to seed from sync_hint to avoid thundering-herd re-fetch
    if m.sync_hint and m.sync_hint.content_hash and m.materialized_path:
        local_file = root / "knowledge" / m.materialized_path
        if local_file.is_file():
            # Inline imports to avoid circular deps
            from brain_sync.fileops import content_hash as compute_hash
            from brain_sync.pipeline import strip_managed_header

            try:
                raw = local_file.read_text(encoding="utf-8")
                body = strip_managed_header(raw)
                local_hash = compute_hash(body.encode("utf-8"))
                if local_hash == m.sync_hint.content_hash:
                    ss.content_hash = m.sync_hint.content_hash
                    ss.last_checked_utc = m.sync_hint.last_synced_utc
                    # Seed scheduler fields so schedule_from_persisted() is used
                    if m.sync_hint.last_synced_utc:
                        from datetime import datetime, timedelta

                        try:
                            last = datetime.fromisoformat(m.sync_hint.last_synced_utc)
                            ss.next_check_utc = (last + timedelta(seconds=1800)).isoformat()
                            ss.interval_seconds = 1800
                        except (ValueError, TypeError):
                            pass
                    log.info("Seeded %s from sync_hint (hash match)", m.canonical_id)
            except OSError:
                pass

    return ss


def _has_sync_progress(ss: SourceState) -> bool:
    """Check if a SourceState has any persistable sync progress."""
    return (
        ss.last_checked_utc is not None
        or ss.content_hash is not None
        or ss.metadata_fingerprint is not None
        or ss.next_check_utc is not None
    )


def load_state(root: Path) -> SyncState:
    db_sources = _load_db_sync_progress(root)

    # Legacy detection: .brain-sync/sources/ absent → pre-Phase-2 brain, DB-only
    manifest_dir = root / ".brain-sync" / "sources"
    if not manifest_dir.is_dir():
        return SyncState(sources=db_sources)

    # Manifests are authoritative. DB-only sources are orphan cache.
    from brain_sync.manifest import read_all_source_manifests, write_source_manifest

    manifests = read_all_source_manifests(root)

    # Empty-manifest-dir migration: dir exists but no manifests, DB has sources.
    # Bootstrap before applying manifest-authoritative logic so CLI commands
    # (list, add duplicate-check) don't observe a false-empty source set.
    if not manifests and db_sources:
        from brain_sync.commands.sources import _bootstrap_manifests_from_db

        _bootstrap_manifests_from_db(root, SyncState(sources=db_sources))
        manifests = read_all_source_manifests(root)

    merged: dict[str, SourceState] = {}
    for cid, m in manifests.items():
        # Skip missing-status sources — they are not schedulable
        if m.status == "missing":
            continue

        # Derive target_path: explicit field > materialized_path parent > ""
        target_path = m.target_path
        if not target_path and m.materialized_path:
            target_path = normalize_path(Path(m.materialized_path).parent)

        # Phase 1→2 migration backfill: if manifest has no target_path and no
        # materialized_path (unsynced source), but DB has a non-empty target_path,
        # use the DB value and write it back to the manifest. One-time self-healing.
        if not target_path and not m.materialized_path and cid in db_sources:
            db_tp = db_sources[cid].target_path
            if db_tp:
                target_path = db_tp
                m.target_path = db_tp
                write_source_manifest(root, m)
                log.info("Backfilled target_path '%s' into manifest for %s", db_tp, cid)

        if cid in db_sources:
            # Merge: manifest intent + DB progress
            db = db_sources[cid]
            merged[cid] = SourceState(
                # Intent from manifest
                canonical_id=cid,
                source_url=m.source_url,
                source_type=m.source_type,
                target_path=target_path,
                fetch_children=m.fetch_children,
                sync_attachments=m.sync_attachments,
                child_path=m.child_path,
                # Progress from DB
                last_checked_utc=db.last_checked_utc,
                last_changed_utc=db.last_changed_utc,
                current_interval_secs=db.current_interval_secs,
                content_hash=db.content_hash,
                metadata_fingerprint=db.metadata_fingerprint,
                next_check_utc=db.next_check_utc,
                interval_seconds=db.interval_seconds,
            )
        else:
            # Manifest-only: seed from sync_hint if possible
            merged[cid] = _seed_from_hint(root, m, target_path)

    return SyncState(sources=merged)


def save_state(root: Path, state: SyncState) -> None:
    """Save sync progress for all sources to sync_cache.

    sync_cache stores only progress fields (no intent — that's in manifests).
    Uses UPSERT pattern: INSERT OR REPLACE to keep it simple.
    """
    conn = _connect(root)
    try:
        for key, ss in state.sources.items():
            if not _has_sync_progress(ss):
                continue
            conn.execute(
                "INSERT INTO sync_cache "
                "(canonical_id, last_checked_utc, last_changed_utc, "
                "current_interval_secs, content_hash, metadata_fingerprint, "
                "next_check_utc, interval_seconds) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(canonical_id) DO UPDATE SET "
                "last_checked_utc=excluded.last_checked_utc, "
                "last_changed_utc=excluded.last_changed_utc, "
                "current_interval_secs=excluded.current_interval_secs, "
                "content_hash=excluded.content_hash, "
                "metadata_fingerprint=excluded.metadata_fingerprint, "
                "next_check_utc=excluded.next_check_utc, "
                "interval_seconds=excluded.interval_seconds",
                (
                    key,
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


def update_source_target_path(root: Path, canonical_id: str, new_target_path: str) -> None:
    """No-op: target_path is now manifest-only (v21+).

    Kept as a stub for callers that haven't been updated yet.
    """
    # target_path lives in manifests now, not in the DB.
    pass


def delete_source(root: Path, canonical_id: str) -> None:
    """Delete a sync_cache row from the DB by canonical ID."""
    conn = _connect(root)
    try:
        conn.execute("DELETE FROM sync_cache WHERE canonical_id = ?", (canonical_id,))
        conn.commit()
    finally:
        conn.close()


def update_source_flags(
    root: Path,
    canonical_id: str,
    *,
    fetch_children: bool | None = None,
    sync_attachments: bool | None = None,
    child_path: str | None = ...,  # type: ignore[assignment]  # sentinel
) -> None:
    """No-op: source flags are now manifest-only (v21+).

    Kept as a stub for callers that haven't been updated yet.
    """
    # Flags live in manifests now, not in the DB.
    pass


def clear_children_flag(root: Path, canonical_id: str) -> None:
    """Clear the one-shot fetch_children flag and child_path after processing.

    In v21+, these flags live in manifests. This updates the manifest directly.
    """
    from brain_sync.manifest import read_source_manifest, write_source_manifest

    m = read_source_manifest(root, canonical_id)
    if m is not None:
        m.fetch_children = False
        m.child_path = None
        write_source_manifest(root, m)


def ensure_db(root: Path) -> None:
    """Ensure the SQLite state database exists with the current schema applied."""
    conn = _connect(root)
    conn.close()


def prune_db(root: Path, active_keys: set[str]) -> None:
    """Remove rows from the DB that are no longer active."""
    conn = _connect(root)
    try:
        existing = {row[0] for row in conn.execute("SELECT canonical_id FROM sync_cache").fetchall()}
        stale = existing - active_keys
        for key in stale:
            conn.execute("DELETE FROM sync_cache WHERE canonical_id = ?", (key,))
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
            "(parent_canonical_id, canonical_id, relationship_type, "
            "source_type, first_seen_utc, last_seen_utc) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(parent_canonical_id, canonical_id) DO UPDATE SET "
            "relationship_type=excluded.relationship_type, "
            "source_type=excluded.source_type, "
            "last_seen_utc=excluded.last_seen_utc",
            (
                rel.parent_canonical_id,
                rel.canonical_id,
                rel.relationship_type,
                rel.source_type,
                rel.first_seen_utc,
                rel.last_seen_utc,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_relationships_for_primary(root: Path, parent_canonical_id: str) -> list[Relationship]:
    conn = _connect(root)
    try:
        rows = conn.execute(
            "SELECT parent_canonical_id, canonical_id, relationship_type, "
            "source_type, first_seen_utc, last_seen_utc "
            "FROM relationships WHERE parent_canonical_id = ?",
            (parent_canonical_id,),
        ).fetchall()
        return [
            Relationship(
                parent_canonical_id=r[0],
                canonical_id=r[1],
                relationship_type=r[2],
                source_type=r[3],
                first_seen_utc=r[4],
                last_seen_utc=r[5],
            )
            for r in rows
        ]
    finally:
        conn.close()


def remove_relationship(root: Path, parent_canonical_id: str, canonical_id: str) -> None:
    conn = _connect(root)
    try:
        conn.execute(
            "DELETE FROM relationships WHERE parent_canonical_id = ? AND canonical_id = ?",
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
    """Remove a document only if no relationships reference it. Returns True if removed.

    With FK CASCADE on relationships.canonical_id, deleting a document also
    removes any relationships that reference it as the child side.
    """
    if count_relationships_for_doc(root, canonical_id) > 0:
        return False
    conn = _connect(root)
    try:
        conn.execute("DELETE FROM documents WHERE canonical_id = ?", (canonical_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# --- Insight state operations ---


_MAX_ERROR_REASON_LEN = 500


def _clamp_error_reason(reason: str | None) -> str | None:
    """Bound error_reason to prevent the state table becoming a log sink."""
    if reason is None:
        return None
    cleaned = " ".join(reason.split())
    if len(cleaned) > _MAX_ERROR_REASON_LEN:
        return cleaned[: _MAX_ERROR_REASON_LEN - 3] + "..."
    return cleaned


def load_insight_state(root: Path, knowledge_path: str) -> InsightState | None:
    """Load insight state: hashes from sidecar, lifecycle from regen_locks."""
    from brain_sync.sidecar import read_regen_meta

    knowledge_path = normalize_path(knowledge_path)

    # Read lifecycle from regen_locks
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT knowledge_path, regen_status, regen_started_utc, "
            "owner_id, error_reason "
            "FROM regen_locks WHERE knowledge_path = ?",
            (knowledge_path,),
        ).fetchone()
    finally:
        conn.close()

    # Read hashes from sidecar
    insights_dir = root / "insights" / knowledge_path if knowledge_path else root / "insights"
    meta = read_regen_meta(insights_dir)

    if row is None and meta is None:
        return None

    return InsightState(
        knowledge_path=knowledge_path,
        content_hash=meta.content_hash if meta else None,
        summary_hash=meta.summary_hash if meta else None,
        structure_hash=meta.structure_hash if meta else None,
        regen_started_utc=row[2] if row else None,
        last_regen_utc=meta.last_regen_utc if meta else None,
        regen_status=row[1] if row else "idle",
        owner_id=row[3] if row else None,
        error_reason=row[4] if row else None,
    )


def save_insight_state(root: Path, istate: InsightState) -> None:
    """Save insight state: hashes to sidecar, lifecycle to regen_locks."""
    from brain_sync.sidecar import RegenMeta, write_regen_meta

    kp = normalize_path(istate.knowledge_path)
    error_reason = _clamp_error_reason(istate.error_reason)

    # Write hashes to sidecar
    insights_dir = root / "insights" / kp if kp else root / "insights"
    if istate.content_hash is not None:
        try:
            write_regen_meta(
                insights_dir,
                RegenMeta(
                    content_hash=istate.content_hash,
                    summary_hash=istate.summary_hash,
                    structure_hash=istate.structure_hash,
                    last_regen_utc=istate.last_regen_utc,
                ),
            )
        except Exception:
            log.warning("Failed to write sidecar for %s", kp, exc_info=True)

    # Write lifecycle to regen_locks
    conn = _connect(root)
    try:
        conn.execute(
            "INSERT INTO regen_locks "
            "(knowledge_path, regen_status, regen_started_utc, "
            "owner_id, error_reason) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(knowledge_path) DO UPDATE SET "
            "regen_status=excluded.regen_status, "
            "regen_started_utc=excluded.regen_started_utc, "
            "owner_id=excluded.owner_id, "
            "error_reason=excluded.error_reason",
            (
                kp,
                istate.regen_status,
                istate.regen_started_utc,
                istate.owner_id,
                error_reason,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_all_insight_states(root: Path) -> list[InsightState]:
    """Load all insight states: hashes from sidecars, lifecycle from regen_locks."""
    from brain_sync.sidecar import read_all_regen_meta

    # Read all sidecars
    insights_root = root / "insights"
    all_meta = read_all_regen_meta(insights_root)

    # Read all regen_locks
    conn = _connect(root)
    try:
        rows = conn.execute(
            "SELECT knowledge_path, regen_status, regen_started_utc, owner_id, error_reason FROM regen_locks"
        ).fetchall()
    finally:
        conn.close()

    locks_by_path: dict[str, tuple] = {r[0]: r for r in rows}

    # Merge: union of all paths from both sources
    all_paths = set(all_meta.keys()) | set(locks_by_path.keys())
    result: list[InsightState] = []
    for kp in all_paths:
        meta = all_meta.get(kp)
        lock = locks_by_path.get(kp)
        result.append(
            InsightState(
                knowledge_path=kp,
                content_hash=meta.content_hash if meta else None,
                summary_hash=meta.summary_hash if meta else None,
                structure_hash=meta.structure_hash if meta else None,
                regen_started_utc=lock[2] if lock else None,
                last_regen_utc=meta.last_regen_utc if meta else None,
                regen_status=lock[1] if lock else "idle",
                owner_id=lock[3] if lock else None,
                error_reason=lock[4] if lock else None,
            )
        )
    return result


def delete_insight_state(root: Path, knowledge_path: str) -> None:
    """Delete regen_locks row + sidecar for a knowledge path."""
    from brain_sync.sidecar import delete_regen_meta

    knowledge_path = normalize_path(knowledge_path)

    # Delete sidecar
    insights_dir = root / "insights" / knowledge_path if knowledge_path else root / "insights"
    try:
        delete_regen_meta(insights_dir)
    except Exception:
        log.warning("Failed to delete sidecar for %s", knowledge_path, exc_info=True)

    # Delete regen_locks row
    conn = _connect(root)
    try:
        conn.execute(
            "DELETE FROM regen_locks WHERE knowledge_path = ?",
            (knowledge_path,),
        )
        conn.commit()
    finally:
        conn.close()


def acquire_regen_ownership(
    root: Path, knowledge_path: str, owner_id: str, stale_threshold_secs: float = 600.0
) -> bool:
    """Atomically acquire ownership of a regen slot for a knowledge path.

    Returns True if ownership was acquired, False if another process owns it.
    Uses INSERT OR IGNORE + UPDATE pattern to handle missing rows.
    Reclaims stale ownership from crashed processes.
    """
    from datetime import UTC, datetime, timedelta

    knowledge_path = normalize_path(knowledge_path)
    now = datetime.now(UTC).isoformat()
    stale_cutoff = (datetime.now(UTC) - timedelta(seconds=stale_threshold_secs)).isoformat()

    conn = _connect(root)
    try:
        # Ensure row exists (no-op if already present)
        conn.execute(
            "INSERT OR IGNORE INTO regen_locks (knowledge_path, regen_status) VALUES (?, 'idle')",
            (knowledge_path,),
        )
        # Atomically claim ownership if available, already ours, or stale
        cur = conn.execute(
            "UPDATE regen_locks "
            "SET owner_id = ?, regen_status = 'running', regen_started_utc = ? "
            "WHERE knowledge_path = ? "
            "  AND (owner_id IS NULL "
            "       OR owner_id = ? "
            "       OR (regen_status = 'running' "
            "           AND regen_started_utc < ?))",
            (owner_id, now, knowledge_path, owner_id, stale_cutoff),
        )
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def reclaim_stale_running_states(root: Path, stale_threshold_secs: float = 600.0) -> int:
    """Reclaim 'running' insight states older than threshold (startup recovery).

    Parses ``regen_started_utc`` in Python rather than relying on SQL lexical
    comparison, to be robust against future timestamp format drift.  Rows with
    malformed or missing timestamps are treated as stale and reclaimed — recovery
    must not crash on bad historic data.
    """
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(seconds=stale_threshold_secs)
    conn = _connect(root)
    try:
        rows = conn.execute(
            "SELECT knowledge_path, regen_started_utc FROM regen_locks WHERE regen_status = 'running'"
        ).fetchall()
        stale_paths: list[str] = []
        for kp, started_utc in rows:
            if not started_utc:
                # Missing timestamp — treat as stale
                stale_paths.append(kp)
                continue
            try:
                started = datetime.fromisoformat(started_utc)
                if started < cutoff:
                    stale_paths.append(kp)
            except (ValueError, TypeError):
                # Malformed timestamp — treat as stale, do not crash recovery
                log.warning(
                    "Malformed regen_started_utc for %s: %r, treating as stale",
                    kp,
                    started_utc,
                )
                stale_paths.append(kp)
        if stale_paths:
            conn.executemany(
                "UPDATE regen_locks SET regen_status = 'idle', owner_id = NULL WHERE knowledge_path = ?",
                [(kp,) for kp in stale_paths],
            )
            conn.commit()
        return len(stale_paths)
    finally:
        conn.close()


def release_owned_running_states(root: Path, owner_id: str) -> int:
    """Release 'running' insight states owned by the given session (finally-cleanup).

    Only resets rows where ``owner_id`` matches, so concurrent sessions cannot
    corrupt each other's in-flight work.

    Note: This resets ALL running rows for the session.  This is correct for the
    current single-sequential-invocation model.  If parallelism is later added
    *within* a session, this function must be scoped more narrowly (e.g. by
    knowledge_path).
    """
    conn = _connect(root)
    try:
        cur = conn.execute(
            "UPDATE regen_locks SET regen_status = 'idle', owner_id = NULL "
            "WHERE regen_status = 'running' AND owner_id = ?",
            (owner_id,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def get_regen_health(root: Path, stale_threshold_secs: float = 600.0) -> dict:
    """Return observability metrics for regen pipeline health."""
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(seconds=stale_threshold_secs)
    conn = _connect(root)
    try:
        running_rows = conn.execute(
            "SELECT knowledge_path, regen_started_utc FROM regen_locks WHERE regen_status = 'running'"
        ).fetchall()
        stale_running = 0
        for _, started_utc in running_rows:
            if not started_utc:
                stale_running += 1
                continue
            try:
                if datetime.fromisoformat(started_utc) < cutoff:
                    stale_running += 1
            except (ValueError, TypeError):
                stale_running += 1

        failed_rows = conn.execute(
            "SELECT knowledge_path, error_reason FROM regen_locks WHERE regen_status = 'failed'"
        ).fetchall()
        return {
            "stale_running": stale_running,
            "running": len(running_rows),
            "failed": len(failed_rows),
            "failed_paths": [
                {
                    "knowledge_path": r[0],
                    "error_reason": r[1],
                }
                for r in failed_rows
            ],
        }
    finally:
        conn.close()


def update_insight_path(root: Path, old_path: str, new_path: str) -> None:
    """Update a knowledge_path in regen_locks (for folder renames)."""
    old_path = normalize_path(old_path)
    new_path = normalize_path(new_path)
    conn = _connect(root)
    try:
        conn.execute(
            "UPDATE regen_locks SET knowledge_path = ? WHERE knowledge_path = ?",
            (new_path, old_path),
        )
        conn.commit()
    finally:
        conn.close()


# --- daemon_status helpers ---


def write_daemon_status(root: Path, pid: int, status: str) -> None:
    """Write the daemon lifecycle status as a single-row table.

    DELETE + INSERT on 'starting' keeps exactly one row.  On crash the
    row remains as 'ready' or 'starting' — diagnostic evidence preserved.
    """
    from datetime import UTC, datetime

    conn = _connect(root)
    try:
        if status == "starting":
            # New lifecycle: clear previous row, insert fresh
            conn.execute("DELETE FROM daemon_status")
            conn.execute(
                "INSERT INTO daemon_status (pid, started_at, status) VALUES (?, ?, ?)",
                (pid, datetime.now(UTC).isoformat(), status),
            )
        else:
            conn.execute("UPDATE daemon_status SET status = ? WHERE pid = ?", (status, pid))
        conn.commit()
    finally:
        conn.close()


def read_daemon_status(root: Path) -> dict | None:
    """Read the single daemon_status row.  Returns dict or None."""
    conn = _connect(root)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT pid, started_at, status FROM daemon_status").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()

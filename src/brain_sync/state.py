from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

STATE_FILENAME = ".sync-state.sqlite"
SCHEMA_VERSION = 9

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

# --- DDL used for fresh DB creation (current schema) ---

_SOURCES_DDL = """
CREATE TABLE IF NOT EXISTS sources (
    canonical_id TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    source_type TEXT NOT NULL,
    last_checked_utc TEXT,
    last_changed_utc TEXT,
    current_interval_secs INTEGER NOT NULL DEFAULT 1800,
    content_hash TEXT,
    metadata_fingerprint TEXT,
    next_check_utc TEXT,
    interval_seconds INTEGER,
    target_path TEXT NOT NULL DEFAULT '',
    include_links INTEGER NOT NULL DEFAULT 0,
    include_children INTEGER NOT NULL DEFAULT 0,
    include_attachments INTEGER NOT NULL DEFAULT 0
);
"""

_INSIGHT_STATE_DDL = """
CREATE TABLE IF NOT EXISTS insight_state (
    knowledge_path TEXT PRIMARY KEY,
    content_hash TEXT,
    summary_hash TEXT,
    regen_started_utc TEXT,
    last_regen_utc TEXT,
    regen_status TEXT NOT NULL DEFAULT 'idle',
    input_tokens INTEGER,
    output_tokens INTEGER,
    num_turns INTEGER,
    model TEXT
);
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
    local_path TEXT NOT NULL,
    source_type TEXT NOT NULL,
    first_seen_utc TEXT,
    last_seen_utc TEXT,
    PRIMARY KEY (parent_canonical_id, canonical_id)
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
    local_path TEXT NOT NULL,
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


@dataclass
class SourceState:
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
    include_links: bool = False
    include_children: bool = False
    include_attachments: bool = False


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
class InsightState:
    knowledge_path: str
    content_hash: str | None = None
    summary_hash: str | None = None
    regen_started_utc: str | None = None
    last_regen_utc: str | None = None
    regen_status: str = "idle"
    input_tokens: int | None = None
    output_tokens: int | None = None
    num_turns: int | None = None
    model: str | None = None


@dataclass
class Relationship:
    parent_canonical_id: str
    canonical_id: str
    relationship_type: str
    local_path: str
    source_type: str
    first_seen_utc: str | None = None
    last_seen_utc: str | None = None


def source_key_for_entry(entry_url: str) -> str:
    """Compute canonical_id from a source URL. This is the source identity key."""
    from brain_sync.sources import canonical_id, detect_source_type
    stype = detect_source_type(entry_url)
    return canonical_id(stype, entry_url)


# Keep old source_key for migration compatibility
def source_key(manifest_path: str, source_url: str) -> str:
    return f"{manifest_path}::{source_url}"


def _db_path(root: Path) -> Path:
    return root / STATE_FILENAME


def _compute_canonical_id_from_row(source_type: str, source_url: str) -> str:
    """Compute canonical_id for migration. Falls back to unknown:{url} on failure."""
    try:
        from brain_sync.sources import canonical_id, SourceType
        stype = SourceType(source_type)
        return canonical_id(stype, source_url)
    except Exception:
        return f"unknown:{source_url}"


def _migrate(conn: sqlite3.Connection, from_version: int, root: Path | None = None) -> None:
    """Run migrations from from_version to SCHEMA_VERSION."""
    if from_version < 2:
        conn.executescript(_SCHEMA_V2_ADDITIONS)
        # Add new columns to sources table (v1 -> v2)
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(sources)").fetchall()
        }
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
                r for r in group
                if (r[5] or "") == (best[5] or "")
                and (r[8] is not None) == (best[8] is not None)
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
                    "INSERT OR IGNORE INTO source_bindings "
                    "(canonical_id, manifest_path, target_file) "
                    "VALUES (?, ?, ?)",
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
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(sources)").fetchall()
        }
        if "target_path" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN target_path TEXT NOT NULL DEFAULT ''")
        if "include_links" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN include_links INTEGER NOT NULL DEFAULT 0")
        if "include_children" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN include_children INTEGER NOT NULL DEFAULT 0")
        if "include_attachments" not in existing_cols:
            conn.execute("ALTER TABLE sources ADD COLUMN include_attachments INTEGER NOT NULL DEFAULT 0")

        # Migrate bindings data into sources if bindings table exists
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
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
                        target_path = target_path.replace("\\", "/")
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
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()
        }
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
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()
        }
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
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()
        }
        if "cost_usd" in existing_cols:
            conn.execute("ALTER TABLE insight_state DROP COLUMN cost_usd")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', '8')",
        )
        conn.commit()
        from_version = 8

    if from_version < 9:
        # v8 → v9: Drop retry_count (queue now owns retry budgeting)
        existing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(insight_state)").fetchall()
        }
        if "retry_count" in existing_cols:
            conn.execute("ALTER TABLE insight_state DROP COLUMN retry_count")
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()

    log.info("Migrated DB schema to v%d", SCHEMA_VERSION)


def _connect(root: Path) -> sqlite3.Connection:
    db = _db_path(root)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Check if DB is fresh (no tables yet)
    tables = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    if not tables or "meta" not in tables:
        # Fresh DB — create current schema directly
        conn.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        conn.executescript(_SOURCES_DDL)
        conn.executescript(_DOCUMENTS_DDL)
        conn.executescript(_RELATIONSHIPS_DDL)
        conn.executescript(_INSIGHT_STATE_DDL)
        conn.execute(
            "INSERT OR IGNORE INTO meta (key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    else:
        # Existing DB — check version and migrate if needed
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        current_version = int(row[0]) if row else 1
        if current_version < SCHEMA_VERSION:
            _migrate(conn, current_version, root=root)

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
            "SELECT canonical_id, source_url, source_type, "
            "last_checked_utc, last_changed_utc, current_interval_secs, "
            "content_hash, metadata_fingerprint, next_check_utc, interval_seconds, "
            "target_path, include_links, include_children, include_attachments "
            "FROM sources"
        ).fetchall()
        for row in rows:
            state.sources[row[0]] = SourceState(
                canonical_id=row[0],
                source_url=row[1],
                source_type=row[2],
                last_checked_utc=row[3],
                last_changed_utc=row[4],
                current_interval_secs=row[5],
                content_hash=row[6],
                metadata_fingerprint=row[7],
                next_check_utc=row[8],
                interval_seconds=row[9],
                target_path=row[10] or "",
                include_links=bool(row[11]),
                include_children=bool(row[12]),
                include_attachments=bool(row[13]),
            )
    except Exception as e:
        log.warning("Error reading sync state, starting fresh: %s", e)
        state = SyncState()
    finally:
        conn.close()

    return state


def save_state(root: Path, state: SyncState) -> None:
    """Save sync progress for all sources.

    Uses UPDATE for existing rows to preserve CLI-managed config fields
    (target_path, include_links, include_children, include_attachments).
    Only inserts if the source doesn't exist yet.
    """
    conn = _connect(root)
    try:
        for key, ss in state.sources.items():
            # Try UPDATE first — only touch sync-progress fields
            cur = conn.execute(
                "UPDATE sources SET "
                "last_checked_utc = ?, last_changed_utc = ?, "
                "current_interval_secs = ?, content_hash = ?, "
                "metadata_fingerprint = ?, next_check_utc = ?, "
                "interval_seconds = ? "
                "WHERE canonical_id = ?",
                (
                    ss.last_checked_utc,
                    ss.last_changed_utc,
                    ss.current_interval_secs,
                    ss.content_hash,
                    ss.metadata_fingerprint,
                    ss.next_check_utc,
                    ss.interval_seconds,
                    key,
                ),
            )
            if cur.rowcount == 0:
                # New source — full insert
                conn.execute(
                    "INSERT INTO sources "
                    "(canonical_id, source_url, source_type, "
                    "last_checked_utc, last_changed_utc, current_interval_secs, "
                    "content_hash, metadata_fingerprint, next_check_utc, interval_seconds, "
                    "target_path, include_links, include_children, include_attachments) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        key,
                        ss.source_url,
                        ss.source_type,
                        ss.last_checked_utc,
                        ss.last_changed_utc,
                        ss.current_interval_secs,
                        ss.content_hash,
                        ss.metadata_fingerprint,
                        ss.next_check_utc,
                        ss.interval_seconds,
                        ss.target_path,
                        int(ss.include_links),
                        int(ss.include_children),
                        int(ss.include_attachments),
                    ),
                )
        conn.commit()
    finally:
        conn.close()


def update_source_target_path(root: Path, canonical_id: str, new_target_path: str) -> None:
    """Update a source's target_path directly in the DB."""
    conn = _connect(root)
    try:
        conn.execute(
            "UPDATE sources SET target_path = ? WHERE canonical_id = ?",
            (new_target_path, canonical_id),
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
            row[0] for row in conn.execute("SELECT canonical_id FROM sources").fetchall()
        }
        stale = existing - active_keys
        for key in stale:
            conn.execute("DELETE FROM sources WHERE canonical_id = ?", (key,))
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
    """Remove a document only if no relationships reference it. Returns True if removed.

    With FK CASCADE on relationships.canonical_id, deleting a document also
    removes any relationships that reference it as the child side.
    """
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


# --- Insight state operations ---


def load_insight_state(root: Path, knowledge_path: str) -> InsightState | None:
    """Load insight state for a knowledge path."""
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT knowledge_path, content_hash, summary_hash, "
            "regen_started_utc, last_regen_utc, regen_status, "
            "input_tokens, output_tokens, num_turns, model "
            "FROM insight_state WHERE knowledge_path = ?",
            (knowledge_path,),
        ).fetchone()
        if row is None:
            return None
        return InsightState(
            knowledge_path=row[0],
            content_hash=row[1],
            summary_hash=row[2],
            regen_started_utc=row[3],
            last_regen_utc=row[4],
            regen_status=row[5],
            input_tokens=row[6],
            output_tokens=row[7],
            num_turns=row[8],
            model=row[9],
        )
    finally:
        conn.close()


def save_insight_state(root: Path, istate: InsightState) -> None:
    """UPSERT insight state for a knowledge path."""
    conn = _connect(root)
    try:
        conn.execute(
            "INSERT INTO insight_state "
            "(knowledge_path, content_hash, summary_hash, "
            "regen_started_utc, last_regen_utc, regen_status, "
            "input_tokens, output_tokens, num_turns, model) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(knowledge_path) DO UPDATE SET "
            "content_hash=excluded.content_hash, "
            "summary_hash=excluded.summary_hash, "
            "regen_started_utc=excluded.regen_started_utc, "
            "last_regen_utc=excluded.last_regen_utc, "
            "regen_status=excluded.regen_status, "
            "input_tokens=excluded.input_tokens, "
            "output_tokens=excluded.output_tokens, "
            "num_turns=excluded.num_turns, "
            "model=excluded.model",
            (
                istate.knowledge_path,
                istate.content_hash,
                istate.summary_hash,
                istate.regen_started_utc,
                istate.last_regen_utc,
                istate.regen_status,
                istate.input_tokens,
                istate.output_tokens,
                istate.num_turns,
                istate.model,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_all_insight_states(root: Path) -> list[InsightState]:
    """Load all insight states."""
    conn = _connect(root)
    try:
        rows = conn.execute(
            "SELECT knowledge_path, content_hash, summary_hash, "
            "regen_started_utc, last_regen_utc, regen_status, "
            "input_tokens, output_tokens, num_turns, model "
            "FROM insight_state"
        ).fetchall()
        return [
            InsightState(
                knowledge_path=r[0],
                content_hash=r[1],
                summary_hash=r[2],
                regen_started_utc=r[3],
                last_regen_utc=r[4],
                regen_status=r[5],
                input_tokens=r[6],
                output_tokens=r[7],
                num_turns=r[8],
                model=r[9],
            )
            for r in rows
        ]
    finally:
        conn.close()


def delete_insight_state(root: Path, knowledge_path: str) -> None:
    """Delete an insight_state entry."""
    conn = _connect(root)
    try:
        conn.execute(
            "DELETE FROM insight_state WHERE knowledge_path = ?",
            (knowledge_path,),
        )
        conn.commit()
    finally:
        conn.close()


def reset_running_insight_states(root: Path) -> int:
    """Reset any 'running' insight states to 'idle' (orphaned from a crash)."""
    conn = _connect(root)
    try:
        cur = conn.execute(
            "UPDATE insight_state SET regen_status = 'idle' WHERE regen_status = 'running'"
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def update_insight_path(root: Path, old_path: str, new_path: str) -> None:
    """Update a knowledge_path in insight_state (for folder renames)."""
    conn = _connect(root)
    try:
        conn.execute(
            "UPDATE insight_state SET knowledge_path = ? WHERE knowledge_path = ?",
            (new_path, old_path),
        )
        conn.commit()
    finally:
        conn.close()

"""Runtime-owned child-discovery request state.

Owns one-shot child-discovery requests for registered sources. This state is
machine-local and intentionally separate from the portable source manifest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from brain_sync.runtime.repository import _connect

log = logging.getLogger(__name__)

_CHILD_DISCOVERY_REQUESTS_DDL = """
CREATE TABLE IF NOT EXISTS child_discovery_requests (
    canonical_id TEXT PRIMARY KEY,
    fetch_children INTEGER NOT NULL DEFAULT 0 CHECK(fetch_children IN (0,1)),
    child_path TEXT,
    updated_utc TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ChildDiscoveryRequest:
    canonical_id: str
    fetch_children: bool = False
    child_path: str | None = None
    updated_utc: str | None = None


def _ensure_table(root: Path) -> None:
    conn = _connect(root)
    try:
        conn.executescript(_CHILD_DISCOVERY_REQUESTS_DDL)
        conn.commit()
    finally:
        conn.close()


def load_child_discovery_request(root: Path, canonical_id: str) -> ChildDiscoveryRequest | None:
    _ensure_table(root)
    conn = _connect(root)
    try:
        row = conn.execute(
            "SELECT canonical_id, fetch_children, child_path, updated_utc "
            "FROM child_discovery_requests WHERE canonical_id = ?",
            (canonical_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    return ChildDiscoveryRequest(
        canonical_id=row[0],
        fetch_children=bool(row[1]),
        child_path=row[2],
        updated_utc=row[3],
    )


def load_all_child_discovery_requests(root: Path) -> dict[str, ChildDiscoveryRequest]:
    _ensure_table(root)
    conn = _connect(root)
    try:
        rows = conn.execute(
            "SELECT canonical_id, fetch_children, child_path, updated_utc FROM child_discovery_requests"
        ).fetchall()
    finally:
        conn.close()

    return {
        row[0]: ChildDiscoveryRequest(
            canonical_id=row[0],
            fetch_children=bool(row[1]),
            child_path=row[2],
            updated_utc=row[3],
        )
        for row in rows
    }


def save_child_discovery_request(
    root: Path,
    canonical_id: str,
    *,
    fetch_children: bool,
    child_path: str | None,
) -> None:
    _ensure_table(root)
    if not fetch_children:
        delete_child_discovery_request(root, canonical_id)
        return

    updated_utc = datetime.now(UTC).isoformat()
    conn = _connect(root)
    try:
        conn.execute(
            "INSERT INTO child_discovery_requests "
            "(canonical_id, fetch_children, child_path, updated_utc) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(canonical_id) DO UPDATE SET "
            "fetch_children=excluded.fetch_children, "
            "child_path=excluded.child_path, "
            "updated_utc=excluded.updated_utc",
            (canonical_id, int(fetch_children), child_path, updated_utc),
        )
        conn.commit()
    finally:
        conn.close()


def clear_child_discovery_request(root: Path, canonical_id: str) -> None:
    delete_child_discovery_request(root, canonical_id)


def delete_child_discovery_request(root: Path, canonical_id: str) -> None:
    _ensure_table(root)
    conn = _connect(root)
    try:
        conn.execute("DELETE FROM child_discovery_requests WHERE canonical_id = ?", (canonical_id,))
        conn.commit()
    finally:
        conn.close()

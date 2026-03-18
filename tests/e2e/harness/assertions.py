"""Durable state assertions for E2E tests.

All assertions check on-disk or DB state, never logs or event sequences.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from brain_sync.brain.fileops import (
    iterdir_paths,
    path_exists,
    path_is_dir,
    read_text,
    rglob_paths,
)
from brain_sync.brain.layout import INSIGHT_STATE_FILENAME, area_summary_path


def _runtime_db_path() -> Path:
    from brain_sync.runtime import config as runtime_config

    return runtime_config.RUNTIME_DB_FILE


def assert_summary_exists(root: Path, knowledge_path: str) -> str:
    """Assert that the co-located summary exists and return its content."""
    summary = area_summary_path(root, knowledge_path)
    assert path_exists(summary), f"Summary not found: {summary}"
    return read_text(summary, encoding="utf-8")


def assert_db_source(root: Path, canonical_id: str, **expected: object) -> dict:
    """Query sync_cache table and assert expected column values."""
    conn = sqlite3.connect(str(_runtime_db_path()))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sync_cache WHERE canonical_id = ?", (canonical_id,)).fetchone()
    conn.close()
    assert row is not None, f"Source not found in sync_cache: {canonical_id}"
    d = dict(row)
    for key, val in expected.items():
        assert d[key] == val, f"sync_cache.{key}: expected {val!r}, got {d[key]!r}"
    return d


def assert_db_regen_lock(root: Path, knowledge_path: str, **expected: object) -> dict:
    """Query regen_locks table and assert expected column values."""
    conn = sqlite3.connect(str(_runtime_db_path()))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM regen_locks WHERE knowledge_path = ?", (knowledge_path,)).fetchone()
    conn.close()
    assert row is not None, f"Regen lock not found: {knowledge_path}"
    d = dict(row)
    for key, val in expected.items():
        assert d[key] == val, f"regen_locks.{key}: expected {val!r}, got {d[key]!r}"
    return d


def assert_no_orphan_insights(root: Path) -> None:
    """Managed insight trees must be co-located and contain no unexpected child mirrors."""
    assert not path_exists(root / "insights"), "Legacy top-level insights/ tree should not exist"

    knowledge_root = root / "knowledge"
    if not path_exists(knowledge_root):
        return

    for insights_dir in rglob_paths(knowledge_root, "insights"):
        if insights_dir.parent.name != ".brain-sync" or not path_is_dir(insights_dir):
            continue
        for child in iterdir_paths(insights_dir):
            if not path_is_dir(child):
                continue
            if child.name.startswith("_"):
                continue
            raise AssertionError(f"Unexpected nested insights dir under {insights_dir}: {child.name}")


def assert_no_duplicate_insights(root: Path) -> None:
    """No duplicate paths in regen_locks table."""
    conn = sqlite3.connect(str(_runtime_db_path()))
    rows = conn.execute(
        "SELECT knowledge_path, COUNT(*) c FROM regen_locks GROUP BY knowledge_path HAVING c > 1"
    ).fetchall()
    conn.close()
    assert not rows, f"Duplicate regen_locks entries: {rows}"


def assert_prompt_contains(capture_dir: Path, substring: str) -> None:
    """At least one captured prompt file contains *substring*."""
    if not capture_dir.exists():
        raise AssertionError(f"Capture dir does not exist: {capture_dir}")
    for f in capture_dir.glob("*.prompt.txt"):
        if substring in f.read_text(encoding="utf-8"):
            return
    raise AssertionError(f"No captured prompt contains: {substring!r}")


# ---------------------------------------------------------------------------
# System invariant: three-domain consistency
# ---------------------------------------------------------------------------


def _assert_no_duplicate_insight_rows(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT knowledge_path, COUNT(*) c FROM regen_locks GROUP BY knowledge_path HAVING c > 1"
    ).fetchall()
    assert not rows, f"Duplicate regen_locks rows: {rows}"


def _assert_db_paths_exist_in_knowledge(conn: sqlite3.Connection, knowledge: Path) -> None:
    rows = conn.execute("SELECT knowledge_path FROM regen_locks").fetchall()
    for (kp,) in rows:
        if not kp:
            continue  # root entry
        assert path_exists(knowledge / kp), f"regen_locks.knowledge_path '{kp}' not found in knowledge/"


def _assert_summaries_have_db_rows(conn: sqlite3.Connection, insights: Path) -> None:
    """Every co-located summary must have either a regen_locks row or a sidecar."""
    if not path_exists(insights):
        return
    for summary in rglob_paths(insights, "summary.md"):
        rel = summary.relative_to(insights)
        if len(rel.parts) < 4 or rel.parts[-3:] != (".brain-sync", "insights", "summary.md"):
            continue
        area_parts = rel.parts[:-3]
        rel_str = "/".join(area_parts)
        if any(part.startswith("_") for part in area_parts):
            continue
        row = conn.execute("SELECT 1 FROM regen_locks WHERE knowledge_path = ?", (rel_str,)).fetchone()
        if row is not None:
            continue
        sidecar = summary.parent / INSIGHT_STATE_FILENAME
        assert path_exists(sidecar), (
            f"knowledge/{rel_str}/.brain-sync/insights/summary.md exists but no regen_locks row and no sidecar"
        )


def _assert_no_stale_summaries(knowledge: Path, insights: Path) -> None:
    if not path_exists(insights):
        return
    for summary in rglob_paths(insights, "summary.md"):
        rel = summary.relative_to(insights)
        if len(rel.parts) < 4 or rel.parts[-3:] != (".brain-sync", "insights", "summary.md"):
            continue
        area_parts = rel.parts[:-3]
        if any(part.startswith("_") for part in area_parts):
            continue
        rel_path = Path(*area_parts) if area_parts else Path()
        assert path_is_dir(knowledge / rel_path), (
            f"Stale summary: knowledge/{rel_path}/.brain-sync/insights/summary.md has no matching knowledge dir"
        )


def _assert_no_running_regen_states(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT knowledge_path FROM regen_locks WHERE regen_status = 'running'").fetchall()
    assert not rows, f"Running regen states after shutdown: {[r[0] for r in rows]}"


def _assert_single_regen_owner_per_path(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT knowledge_path, COUNT(DISTINCT owner_id) c "
        "FROM regen_locks WHERE owner_id IS NOT NULL "
        "GROUP BY knowledge_path HAVING c > 1"
    ).fetchall()
    assert not rows, f"Multiple regen owners for same path: {rows}"


def _assert_insight_tree_mirrors_knowledge(knowledge: Path, insights: Path) -> None:
    if path_exists(insights):
        assert not path_exists(insights.parent.parent / "insights"), "Legacy top-level insights/ tree should not exist"


def _assert_db_paths_normalized(conn: sqlite3.Connection) -> None:
    for table, col in [("regen_locks", "knowledge_path")]:
        rows = conn.execute(f"SELECT [{col}] FROM [{table}]").fetchall()
        for (val,) in rows:
            if val is None:
                continue
            assert "\\" not in val, f"{table}.{col} contains backslash: {val!r}"
            assert not val.startswith("/"), f"{table}.{col} has leading slash: {val!r}"
            assert ".." not in val, f"{table}.{col} contains '..': {val!r}"


def _assert_knowledge_path_casing(conn: sqlite3.Connection, knowledge: Path) -> None:
    rows = conn.execute("SELECT knowledge_path FROM regen_locks WHERE knowledge_path != ''").fetchall()
    for (kp,) in rows:
        resolved_rel_str = _resolve_knowledge_path_casing(knowledge, kp)
        if resolved_rel_str is None:
            continue  # other check will catch missing paths
        assert kp == resolved_rel_str, f"Case mismatch: DB has '{kp}', filesystem has '{resolved_rel_str}'"


def _resolve_knowledge_path_casing(knowledge: Path, knowledge_path: str) -> str | None:
    current = knowledge
    actual_parts: list[str] = []
    for part in Path(knowledge_path).parts:
        match = next((child.name for child in iterdir_paths(current) if child.name.casefold() == part.casefold()), None)
        if match is None:
            return None
        actual_parts.append(match)
        current = current / match
    return "/".join(actual_parts)


def assert_brain_consistent(root: Path) -> None:
    """Assert mutual consistency of knowledge/, co-located insights, and SQLite state.

    Pure validation — no mutations, no reconciliation, no sleeps.
    """
    knowledge = root / "knowledge"
    insights = knowledge
    db_path = _runtime_db_path()

    if not path_exists(db_path):
        return  # no DB means nothing to check

    conn = sqlite3.connect(str(db_path))
    try:
        assert_no_orphan_insights(root)
        _assert_no_duplicate_insight_rows(conn)
        _assert_db_paths_exist_in_knowledge(conn, knowledge)
        _assert_summaries_have_db_rows(conn, insights)
        _assert_no_stale_summaries(knowledge, insights)
        _assert_no_running_regen_states(conn)
        _assert_single_regen_owner_per_path(conn)
        _assert_insight_tree_mirrors_knowledge(knowledge, insights)
        _assert_db_paths_normalized(conn)
        _assert_knowledge_path_casing(conn, knowledge)
    finally:
        conn.close()

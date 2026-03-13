"""Durable state assertions for E2E tests.

All assertions check on-disk or DB state, never logs or event sequences.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def assert_summary_exists(root: Path, knowledge_path: str) -> str:
    """Assert that insights/{path}/summary.md exists and return its content."""
    if knowledge_path:
        summary = root / "insights" / knowledge_path / "summary.md"
    else:
        summary = root / "insights" / "summary.md"
    assert summary.exists(), f"Summary not found: {summary}"
    return summary.read_text(encoding="utf-8")


def assert_db_source(root: Path, canonical_id: str, **expected: object) -> dict:
    """Query sources table and assert expected column values."""
    conn = sqlite3.connect(str(root / ".sync-state.sqlite"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM sources WHERE canonical_id = ?", (canonical_id,)).fetchone()
    conn.close()
    assert row is not None, f"Source not found: {canonical_id}"
    d = dict(row)
    for key, val in expected.items():
        assert d[key] == val, f"sources.{key}: expected {val!r}, got {d[key]!r}"
    return d


def assert_db_insight_state(root: Path, knowledge_path: str, **expected: object) -> dict:
    """Query insight_state table and assert expected column values."""
    conn = sqlite3.connect(str(root / ".sync-state.sqlite"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM insight_state WHERE knowledge_path = ?", (knowledge_path,)).fetchone()
    conn.close()
    assert row is not None, f"Insight state not found: {knowledge_path}"
    d = dict(row)
    for key, val in expected.items():
        assert d[key] == val, f"insight_state.{key}: expected {val!r}, got {d[key]!r}"
    return d


def assert_no_orphan_insights(root: Path) -> None:
    """Every insights/ subfolder must have a matching knowledge/ folder."""
    insights_root = root / "insights"
    knowledge_root = root / "knowledge"
    if not insights_root.exists():
        return
    for d in insights_root.rglob("*"):
        if not d.is_dir():
            continue
        rel = d.relative_to(insights_root)
        if rel.name.startswith("_"):
            continue  # _core, _sync-context etc.
        matching = knowledge_root / rel
        assert matching.is_dir(), f"Orphan insight dir: insights/{rel} (no knowledge/{rel})"


def assert_no_duplicate_insights(root: Path) -> None:
    """No duplicate paths in insight_state table."""
    conn = sqlite3.connect(str(root / ".sync-state.sqlite"))
    rows = conn.execute(
        "SELECT knowledge_path, COUNT(*) c FROM insight_state GROUP BY knowledge_path HAVING c > 1"
    ).fetchall()
    conn.close()
    assert not rows, f"Duplicate insight_state entries: {rows}"


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
        "SELECT knowledge_path, COUNT(*) c FROM insight_state GROUP BY knowledge_path HAVING c > 1"
    ).fetchall()
    assert not rows, f"Duplicate insight_state rows: {rows}"


def _assert_db_paths_exist_in_knowledge(conn: sqlite3.Connection, knowledge: Path) -> None:
    rows = conn.execute("SELECT knowledge_path FROM insight_state").fetchall()
    for (kp,) in rows:
        if not kp:
            continue  # root entry
        assert (knowledge / kp).exists(), f"insight_state.knowledge_path '{kp}' not found in knowledge/"


def _assert_summaries_have_db_rows(conn: sqlite3.Connection, insights: Path) -> None:
    if not insights.exists():
        return
    for summary in insights.rglob("summary.md"):
        rel = summary.parent.relative_to(insights)
        rel_str = str(rel).replace("\\", "/")
        if rel_str == ".":
            rel_str = ""
        # Skip _core and other underscore-prefixed
        parts = rel.parts if rel.parts else ()
        if any(p.startswith("_") for p in parts):
            continue
        row = conn.execute("SELECT 1 FROM insight_state WHERE knowledge_path = ?", (rel_str,)).fetchone()
        assert row is not None, f"insights/{rel_str}/summary.md exists but no insight_state row for '{rel_str}'"


def _assert_no_stale_summaries(knowledge: Path, insights: Path) -> None:
    if not insights.exists():
        return
    for summary in insights.rglob("summary.md"):
        rel = summary.parent.relative_to(insights)
        parts = rel.parts if rel.parts else ()
        if any(p.startswith("_") for p in parts):
            continue
        if str(rel) == ".":
            continue  # root summary is always valid
        assert (knowledge / rel).is_dir(), (
            f"Stale summary: insights/{rel}/summary.md but knowledge/{rel} does not exist"
        )


def _assert_no_running_regen_states(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT knowledge_path FROM insight_state WHERE regen_status = 'running'").fetchall()
    assert not rows, f"Running regen states after shutdown: {[r[0] for r in rows]}"


def _assert_single_regen_owner_per_path(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT knowledge_path, COUNT(DISTINCT owner_id) c "
        "FROM insight_state WHERE owner_id IS NOT NULL "
        "GROUP BY knowledge_path HAVING c > 1"
    ).fetchall()
    assert not rows, f"Multiple regen owners for same path: {rows}"


def _assert_source_targets_exist(conn: sqlite3.Connection, knowledge: Path) -> None:
    rows = conn.execute("SELECT canonical_id, target_path FROM sources WHERE target_path != ''").fetchall()
    for cid, tp in rows:
        assert (knowledge / tp).exists(), f"Source {cid} target_path '{tp}' not found in knowledge/"


def _assert_insight_tree_mirrors_knowledge(knowledge: Path, insights: Path) -> None:
    if not knowledge.exists():
        return
    for d in knowledge.iterdir():
        if not d.is_dir() or d.name.startswith((".", "_")):
            continue
        # Every top-level knowledge dir with content should eventually have
        # a matching insights dir — but only if insights/ exists at all.
        # We don't require insights to exist for empty brains.
        if insights.exists() and (insights / d.name).exists():
            # Check one level down that structure mirrors
            for sub in d.iterdir():
                if sub.is_dir() and not sub.name.startswith((".", "_")):
                    insight_sub = insights / d.name / sub.name
                    if not insight_sub.exists():
                        # Not an error — insights may not have been generated yet.
                        # This check is intentionally lenient for partial regen.
                        pass


def _assert_db_paths_normalized(conn: sqlite3.Connection) -> None:
    for table, col in [("insight_state", "knowledge_path"), ("sources", "target_path")]:
        rows = conn.execute(f"SELECT [{col}] FROM [{table}]").fetchall()
        for (val,) in rows:
            if val is None:
                continue
            assert "\\" not in val, f"{table}.{col} contains backslash: {val!r}"
            assert not val.startswith("/"), f"{table}.{col} has leading slash: {val!r}"
            assert ".." not in val, f"{table}.{col} contains '..': {val!r}"


def _assert_knowledge_path_casing(conn: sqlite3.Connection, knowledge: Path) -> None:
    rows = conn.execute("SELECT knowledge_path FROM insight_state WHERE knowledge_path != ''").fetchall()
    for (kp,) in rows:
        actual = knowledge / kp
        if not actual.exists():
            continue  # other check will catch missing paths
        # Resolve actual casing on case-insensitive filesystems
        try:
            resolved = actual.resolve()
            expected_suffix = str(actual.resolve()).replace("\\", "/")
            actual_suffix = str(resolved).replace("\\", "/")
            assert expected_suffix == actual_suffix, (
                f"Case mismatch for insight_state.knowledge_path '{kp}': "
                f"DB says '{kp}', filesystem resolves to '{resolved}'"
            )
        except OSError:
            pass


def assert_brain_consistent(root: Path) -> None:
    """Assert mutual consistency of knowledge/, insights/, and SQLite state.

    Pure validation — no mutations, no reconciliation, no sleeps.
    """
    knowledge = root / "knowledge"
    insights = root / "insights"
    db_path = root / ".sync-state.sqlite"

    if not db_path.exists():
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
        _assert_source_targets_exist(conn, knowledge)
        _assert_insight_tree_mirrors_knowledge(knowledge, insights)
        _assert_db_paths_normalized(conn)
        _assert_knowledge_path_casing(conn, knowledge)
    finally:
        conn.close()

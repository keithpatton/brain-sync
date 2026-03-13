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

"""Failure diagnostic capture for E2E tests.

Pytest plugin that captures diagnostics to ``{tmp_path}/_failure_artifacts/``
when a test fails.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from brain_sync.layout import area_insights_dir


def _runtime_db_path() -> Path:
    from brain_sync import config as runtime_config

    return runtime_config.RUNTIME_DB_FILE


def _tree_listing(directory: Path, prefix: str = "") -> str:
    """Generate a tree-style listing of a directory."""
    lines: list[str] = []
    if not directory.exists():
        return f"{prefix}(not found)\n"
    for item in sorted(directory.iterdir()):
        lines.append(f"{prefix}{item.name}")
        if item.is_dir() and not item.name.startswith("."):
            lines.append(_tree_listing(item, prefix + "  "))
    return "\n".join(lines)


def _dump_sqlite(db_path: Path) -> str:
    """Dump all tables from a SQLite database."""
    if not db_path.exists():
        return "(no database)"
    try:
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        parts: list[str] = []
        for (table_name,) in tables:
            parts.append(f"\n=== {table_name} ===")
            rows = conn.execute(f"SELECT * FROM [{table_name}]").fetchall()
            cols = [desc[0] for desc in conn.execute(f"SELECT * FROM [{table_name}] LIMIT 0").description]
            parts.append("  | ".join(cols))
            for row in rows:
                parts.append("  | ".join(str(v) for v in row))
        conn.close()
        return "\n".join(parts)
    except Exception as e:
        return f"(error: {e})"


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):  # type: ignore[type-arg]
    """Capture failure artifacts after test teardown."""
    outcome = yield
    report = outcome.get_result()

    if report.when != "call" or not report.failed:
        return

    tmp_path = item.funcargs.get("tmp_path")  # pyright: ignore[reportAttributeAccessIssue]
    if tmp_path is None:
        return

    artifacts = Path(tmp_path) / "_failure_artifacts"
    artifacts.mkdir(exist_ok=True)

    # Brain root tree listings
    brain = Path(tmp_path) / "brain"
    if brain.exists():
        knowledge = brain / "knowledge"
        insights = area_insights_dir(brain)
        (artifacts / "knowledge_tree.txt").write_text(_tree_listing(knowledge), encoding="utf-8")
        (artifacts / "insights_tree.txt").write_text(_tree_listing(insights), encoding="utf-8")

        # SQLite dump
        db_path = _runtime_db_path()
        (artifacts / "db_dump.txt").write_text(_dump_sqlite(db_path), encoding="utf-8")

    # Daemon stdout/stderr (shut down if still running so pipes can be read)
    daemon_fixture = item.funcargs.get("daemon")  # pyright: ignore[reportAttributeAccessIssue]
    if daemon_fixture is not None:
        try:
            if daemon_fixture.is_running():
                daemon_fixture.shutdown()
            stdout = daemon_fixture.stdout_text
            stderr = daemon_fixture.stderr_text
            if stdout:
                (artifacts / "daemon_stdout.txt").write_text(stdout, encoding="utf-8")
            if stderr:
                (artifacts / "daemon_stderr.txt").write_text(stderr, encoding="utf-8")
        except Exception:
            pass

    # Captured prompts
    prompts_dir = Path(tmp_path) / "prompts"
    if prompts_dir.exists():
        for f in prompts_dir.glob("*.prompt.txt"):
            (artifacts / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")

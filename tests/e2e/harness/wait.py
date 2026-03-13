"""Polling utilities for eventual-consistency assertions in E2E tests.

All assertions check eventual state, never event sequences.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")

DEFAULT_TIMEOUT = 30.0
POLL_INTERVAL = 0.5


def wait_for_file(path: Path, timeout: float = DEFAULT_TIMEOUT) -> None:
    """Wait until *path* exists on disk."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"File not found after {timeout}s: {path}")


def wait_for_no_file(path: Path, timeout: float = DEFAULT_TIMEOUT) -> None:
    """Wait until *path* no longer exists on disk."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not path.exists():
            return
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"File still exists after {timeout}s: {path}")


def wait_for_db(
    db_path: Path,
    query: str,
    predicate: Callable[[list], bool],
    timeout: float = DEFAULT_TIMEOUT,
) -> list:
    """Poll SQLite with *query* until *predicate(rows)* is true.

    Opens a fresh connection each poll to avoid stale reads.
    Returns the rows on success.
    """
    deadline = time.monotonic() + timeout
    last_rows: list = []
    while time.monotonic() < deadline:
        try:
            conn = sqlite3.connect(str(db_path), timeout=1)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query).fetchall()
            conn.close()
            last_rows = rows
            if predicate(rows):
                return rows
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            pass
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"DB condition not met after {timeout}s. Last rows: {last_rows}")


def wait_for_condition(
    fn: Callable[[], T],
    timeout: float = DEFAULT_TIMEOUT,
    *,
    description: str = "condition",
) -> T:
    """Generic predicate poller.  Returns the truthy result on success."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = fn()
        if result:
            return result
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"{description} not met after {timeout}s")

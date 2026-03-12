"""Invocation-level token usage telemetry.

Append-only event recording for every LLM invocation (including retries).
Non-blocking: failures are logged once then silently dropped.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from brain_sync.state import STATE_FILENAME

log = logging.getLogger(__name__)

# Operation type constants — match CHECK constraint in token_events table
OP_REGEN = "regen"
OP_QUERY = "query"
OP_CLASSIFY = "classify"

_failure_logged = False


def _db_path(root: Path) -> Path:
    return root / STATE_FILENAME


def record_token_event(
    root: Path,
    session_id: str,
    operation_type: str,
    resource_type: str | None,
    resource_id: str | None,
    is_chunk: bool,
    model: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    duration_ms: int | None,
    num_turns: int | None,
    success: bool,
) -> None:
    """Record a single LLM invocation event. Never raises."""
    global _failure_logged
    try:
        created_utc = datetime.now(UTC).isoformat(timespec="seconds")
        success_int = 1 if success else 0
        total_tokens = (input_tokens or 0) + (output_tokens or 0)

        conn = sqlite3.connect(str(_db_path(root)), timeout=5)
        try:
            conn.execute(
                "INSERT INTO token_events "
                "(session_id, operation_type, resource_type, resource_id, "
                "is_chunk, model, input_tokens, output_tokens, total_tokens, "
                "duration_ms, num_turns, success, created_utc) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    operation_type,
                    resource_type,
                    resource_id,
                    int(is_chunk),
                    model,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    duration_ms,
                    num_turns,
                    success_int,
                    created_utc,
                ),
            )
            conn.commit()
        finally:
            conn.close()
        _failure_logged = False
    except Exception:
        if not _failure_logged:
            log.warning("Failed to record token event", exc_info=True)
            _failure_logged = True


def get_usage_summary(root: Path, days: int = 7) -> dict:
    """Aggregate token usage over the last N days.

    Returns: total_input, total_output, total_tokens, total_invocations,
    by_operation (list of dicts), by_day (list of dicts).
    """
    conn = sqlite3.connect(str(_db_path(root)), timeout=5)
    try:
        cutoff = f"-{days} days"

        # Totals
        row = conn.execute(
            "SELECT COALESCE(SUM(input_tokens), 0), "
            "COALESCE(SUM(output_tokens), 0), "
            "COALESCE(SUM(total_tokens), 0), "
            "COUNT(*) "
            "FROM token_events "
            "WHERE created_utc >= datetime('now', ?)",
            (cutoff,),
        ).fetchone()
        total_input, total_output, total_tokens, total_invocations = row

        # By operation
        by_op_rows = conn.execute(
            "SELECT operation_type, "
            "COALESCE(SUM(input_tokens), 0), "
            "COALESCE(SUM(output_tokens), 0), "
            "COALESCE(SUM(total_tokens), 0), "
            "COUNT(*) "
            "FROM token_events "
            "WHERE created_utc >= datetime('now', ?) "
            "GROUP BY operation_type ORDER BY operation_type",
            (cutoff,),
        ).fetchall()
        by_operation = [
            {
                "operation": r[0],
                "input_tokens": r[1],
                "output_tokens": r[2],
                "total_tokens": r[3],
                "invocations": r[4],
            }
            for r in by_op_rows
        ]

        # By day
        by_day_rows = conn.execute(
            "SELECT DATE(created_utc) as day, "
            "COALESCE(SUM(input_tokens), 0), "
            "COALESCE(SUM(output_tokens), 0), "
            "COALESCE(SUM(total_tokens), 0), "
            "COUNT(*) "
            "FROM token_events "
            "WHERE created_utc >= datetime('now', ?) "
            "GROUP BY day ORDER BY day",
            (cutoff,),
        ).fetchall()
        by_day = [
            {
                "day": r[0],
                "input_tokens": r[1],
                "output_tokens": r[2],
                "total_tokens": r[3],
                "invocations": r[4],
            }
            for r in by_day_rows
        ]

        return {
            "total_input": total_input,
            "total_output": total_output,
            "total_tokens": total_tokens,
            "total_invocations": total_invocations,
            "by_operation": by_operation,
            "by_day": by_day,
        }
    finally:
        conn.close()

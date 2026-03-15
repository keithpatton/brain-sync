"""Invocation-level token usage telemetry.

Append-only event recording for every LLM invocation (including retries).
Non-blocking: failures are logged once then silently dropped.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from brain_sync.config import RUNTIME_DB_FILE, load_config

log = logging.getLogger(__name__)

# Operation type constants — match CHECK constraint in token_events table
OP_REGEN = "regen"
OP_QUERY = "query"
OP_CLASSIFY = "classify"

# Default retention period for token_events rows
TOKEN_RETENTION_DAYS = 90

_failure_logged = False


def _db_path(root: Path) -> Path:
    return RUNTIME_DB_FILE


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


def load_retention_days() -> int:
    """Read token_events retention period from config, defaulting to 90 days."""
    cfg = load_config()
    return cfg.get("token_events", {}).get("retention_days", TOKEN_RETENTION_DAYS)


def prune_token_events(root: Path, retention_days: int = TOKEN_RETENTION_DAYS) -> int:
    """Delete token_events rows older than *retention_days*. Never raises.

    Returns the number of rows deleted (0 on failure).
    """
    global _failure_logged
    try:
        cutoff = f"-{retention_days} days"
        conn = sqlite3.connect(str(_db_path(root)), timeout=5)
        try:
            cursor = conn.execute(
                "DELETE FROM token_events WHERE created_utc < datetime('now', ?)",
                (cutoff,),
            )
            deleted = cursor.rowcount
            conn.commit()
        finally:
            conn.close()
        if deleted:
            log.info("Pruned %d token_events rows older than %d days", deleted, retention_days)
        _failure_logged = False
        return deleted
    except Exception:
        if not _failure_logged:
            log.warning("Failed to prune token events", exc_info=True)
            _failure_logged = True
        return 0

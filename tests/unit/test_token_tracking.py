from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import brain_sync.runtime.repository as state_module
from brain_sync.runtime.repository import _connect
from brain_sync.runtime.token_tracking import (
    OP_CLASSIFY,
    OP_QUERY,
    OP_REGEN,
    get_usage_summary,
    prune_token_events,
    record_token_event,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def brain(tmp_path: Path) -> Path:
    _connect(tmp_path).close()
    return tmp_path


def _runtime_conn() -> sqlite3.Connection:
    return sqlite3.connect(str(state_module.RUNTIME_DB_FILE))


class TestRecordTokenEvent:
    def test_insert_all_fields(self, brain: Path) -> None:
        record_token_event(
            root=brain,
            session_id="sess-1",
            operation_type=OP_REGEN,
            resource_type="knowledge",
            resource_id="area/foo",
            is_chunk=False,
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=200,
            duration_ms=5000,
            num_turns=3,
            success=True,
        )

        conn = _runtime_conn()
        row = conn.execute("SELECT * FROM token_events WHERE session_id = 'sess-1'").fetchone()
        conn.close()

        assert row is not None
        assert row[1] == "sess-1"
        assert row[2] == "regen"
        assert row[3] == "knowledge"
        assert row[4] == "area/foo"
        assert row[5] == 0
        assert row[6] == "claude-sonnet-4-6"
        assert row[9] == 1200
        assert row[12] == 1

    def test_created_utc_timezone_aware(self, brain: Path) -> None:
        record_token_event(
            root=brain,
            session_id="sess-tz",
            operation_type=OP_REGEN,
            resource_type=None,
            resource_id=None,
            is_chunk=False,
            model=None,
            input_tokens=100,
            output_tokens=50,
            duration_ms=500,
            num_turns=1,
            success=True,
        )

        conn = _runtime_conn()
        row = conn.execute("SELECT created_utc FROM token_events WHERE session_id = 'sess-tz'").fetchone()
        conn.close()

        assert row is not None
        assert row[0].endswith("+00:00")

    def test_check_constraint_rejects_invalid_operation(self, brain: Path) -> None:
        conn = _runtime_conn()
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO token_events "
                "(session_id, operation_type, is_chunk, success, created_utc) "
                "VALUES ('x', 'invalid_op', 0, 1, '2026-01-01T00:00:00+00:00')"
            )
        conn.close()


class TestGetUsageSummary:
    def test_session_grouping(self, brain: Path) -> None:
        for i in range(3):
            record_token_event(
                root=brain,
                session_id="sess-group",
                operation_type=OP_REGEN,
                resource_type="knowledge",
                resource_id=f"area/{i}",
                is_chunk=False,
                model=None,
                input_tokens=100,
                output_tokens=50,
                duration_ms=1000,
                num_turns=1,
                success=True,
            )

        summary = get_usage_summary(brain, days=7)

        assert summary["total_invocations"] == 3
        assert summary["total_input"] == 300
        assert summary["total_output"] == 150
        assert summary["total_tokens"] == 450

    def test_by_operation_breakdown(self, brain: Path) -> None:
        record_token_event(
            root=brain,
            session_id="s1",
            operation_type=OP_REGEN,
            resource_type=None,
            resource_id=None,
            is_chunk=False,
            model=None,
            input_tokens=100,
            output_tokens=50,
            duration_ms=1000,
            num_turns=1,
            success=True,
        )
        record_token_event(
            root=brain,
            session_id="s2",
            operation_type=OP_QUERY,
            resource_type=None,
            resource_id=None,
            is_chunk=False,
            model=None,
            input_tokens=200,
            output_tokens=100,
            duration_ms=2000,
            num_turns=1,
            success=True,
        )
        record_token_event(
            root=brain,
            session_id="s3",
            operation_type=OP_CLASSIFY,
            resource_type="document",
            resource_id="doc-123",
            is_chunk=False,
            model=None,
            input_tokens=50,
            output_tokens=10,
            duration_ms=500,
            num_turns=1,
            success=True,
        )

        summary = get_usage_summary(brain, days=7)
        ops = {row["operation"]: row for row in summary["by_operation"]}

        assert ops["regen"]["invocations"] == 1
        assert ops["query"]["input_tokens"] == 200
        assert ops["classify"]["total_tokens"] == 60

    def test_empty_db(self, brain: Path) -> None:
        summary = get_usage_summary(brain, days=7)

        assert summary["total_invocations"] == 0
        assert summary["by_operation"] == []
        assert summary["by_day"] == []


class TestPruneTokenEvents:
    def test_deletes_old_rows(self, brain: Path) -> None:
        conn = _runtime_conn()
        conn.execute(
            "INSERT INTO token_events "
            "(session_id, operation_type, is_chunk, success, created_utc) "
            "VALUES ('old', 'regen', 0, 1, '2025-01-01T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()

        deleted = prune_token_events(brain, retention_days=90)

        assert deleted == 1

    def test_keeps_recent_rows(self, brain: Path) -> None:
        record_token_event(
            root=brain,
            session_id="recent",
            operation_type=OP_REGEN,
            resource_type=None,
            resource_id=None,
            is_chunk=False,
            model=None,
            input_tokens=100,
            output_tokens=50,
            duration_ms=1000,
            num_turns=1,
            success=True,
        )

        deleted = prune_token_events(brain, retention_days=90)

        assert deleted == 0
        conn = _runtime_conn()
        remaining = conn.execute("SELECT COUNT(*) FROM token_events").fetchone()[0]
        conn.close()
        assert remaining == 1

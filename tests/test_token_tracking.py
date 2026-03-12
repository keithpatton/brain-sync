"""Tests for invocation-level token usage telemetry."""

from __future__ import annotations

import sqlite3

import pytest

from brain_sync.state import _connect
from brain_sync.token_tracking import (
    OP_CLASSIFY,
    OP_QUERY,
    OP_REGEN,
    get_usage_summary,
    record_token_event,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def brain(tmp_path):
    """Create a fresh DB at tmp_path so token_events table exists."""
    _connect(tmp_path).close()
    return tmp_path


class TestRecordTokenEvent:
    def test_insert_all_fields(self, brain):
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
        conn = sqlite3.connect(str(brain / ".sync-state.sqlite"))
        row = conn.execute("SELECT * FROM token_events WHERE session_id = 'sess-1'").fetchone()
        conn.close()
        assert row is not None
        # id, session_id, operation_type, resource_type, resource_id,
        # is_chunk, model, input_tokens, output_tokens, total_tokens,
        # duration_ms, num_turns, success, created_utc
        assert row[1] == "sess-1"
        assert row[2] == "regen"
        assert row[3] == "knowledge"
        assert row[4] == "area/foo"
        assert row[5] == 0  # is_chunk
        assert row[6] == "claude-sonnet-4-6"
        assert row[7] == 1000  # input_tokens
        assert row[8] == 200  # output_tokens
        assert row[9] == 1200  # total_tokens
        assert row[10] == 5000  # duration_ms
        assert row[11] == 3  # num_turns
        assert row[12] == 1  # success

    def test_is_chunk_flag_preserved(self, brain):
        record_token_event(
            root=brain,
            session_id="sess-chunk",
            operation_type=OP_REGEN,
            resource_type="knowledge",
            resource_id="area/big",
            is_chunk=True,
            model=None,
            input_tokens=500,
            output_tokens=100,
            duration_ms=2000,
            num_turns=1,
            success=True,
        )
        conn = sqlite3.connect(str(brain / ".sync-state.sqlite"))
        row = conn.execute("SELECT is_chunk FROM token_events WHERE session_id = 'sess-chunk'").fetchone()
        conn.close()
        assert row[0] == 1

    def test_success_stored_as_integer(self, brain):
        record_token_event(
            root=brain,
            session_id="sess-fail",
            operation_type=OP_REGEN,
            resource_type="knowledge",
            resource_id="area/x",
            is_chunk=False,
            model=None,
            input_tokens=100,
            output_tokens=0,
            duration_ms=1000,
            num_turns=1,
            success=False,
        )
        conn = sqlite3.connect(str(brain / ".sync-state.sqlite"))
        row = conn.execute("SELECT success FROM token_events WHERE session_id = 'sess-fail'").fetchone()
        conn.close()
        assert row[0] == 0

    def test_total_tokens_computed_with_nones(self, brain):
        record_token_event(
            root=brain,
            session_id="sess-none",
            operation_type=OP_REGEN,
            resource_type=None,
            resource_id=None,
            is_chunk=False,
            model=None,
            input_tokens=None,
            output_tokens=None,
            duration_ms=None,
            num_turns=None,
            success=True,
        )
        conn = sqlite3.connect(str(brain / ".sync-state.sqlite"))
        row = conn.execute("SELECT total_tokens FROM token_events WHERE session_id = 'sess-none'").fetchone()
        conn.close()
        assert row[0] == 0

    def test_created_utc_timezone_aware(self, brain):
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
        conn = sqlite3.connect(str(brain / ".sync-state.sqlite"))
        row = conn.execute("SELECT created_utc FROM token_events WHERE session_id = 'sess-tz'").fetchone()
        conn.close()
        assert row[0].endswith("+00:00")

    def test_check_constraint_rejects_invalid_operation(self, brain):
        """CHECK constraint on operation_type prevents invalid values."""
        conn = sqlite3.connect(str(brain / ".sync-state.sqlite"))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO token_events "
                "(session_id, operation_type, is_chunk, success, created_utc) "
                "VALUES ('x', 'invalid_op', 0, 1, '2026-01-01T00:00:00+00:00')"
            )
        conn.close()

    def test_failure_isolation_bad_path(self, tmp_path):
        """Bad DB path logs warning but does not raise."""
        import brain_sync.token_tracking as tt

        tt._failure_logged = False
        # Point at a non-existent nested path where the DB file can't be created
        bad_root = tmp_path / "nonexistent" / "deep" / "path"
        record_token_event(
            root=bad_root,
            session_id="sess-bad",
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
        # Should not raise — that's the test
        assert tt._failure_logged is True

    def test_duration_ms_propagation(self, brain):
        record_token_event(
            root=brain,
            session_id="sess-dur",
            operation_type=OP_REGEN,
            resource_type="knowledge",
            resource_id="area/x",
            is_chunk=False,
            model=None,
            input_tokens=100,
            output_tokens=50,
            duration_ms=12345,
            num_turns=1,
            success=True,
        )
        conn = sqlite3.connect(str(brain / ".sync-state.sqlite"))
        row = conn.execute("SELECT duration_ms FROM token_events WHERE session_id = 'sess-dur'").fetchone()
        conn.close()
        assert row[0] == 12345


class TestGetUsageSummary:
    def test_session_grouping(self, brain):
        """Multiple events in one session aggregate correctly."""
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

    def test_by_operation_breakdown(self, brain):
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
        summary = get_usage_summary(brain, days=7)
        ops = {r["operation"]: r for r in summary["by_operation"]}
        assert "regen" in ops
        assert "query" in ops
        assert ops["regen"]["invocations"] == 1
        assert ops["query"]["input_tokens"] == 200

    def test_by_day_breakdown(self, brain):
        record_token_event(
            root=brain,
            session_id="s-day",
            operation_type=OP_REGEN,
            resource_type=None,
            resource_id=None,
            is_chunk=False,
            model=None,
            input_tokens=500,
            output_tokens=200,
            duration_ms=3000,
            num_turns=1,
            success=True,
        )
        summary = get_usage_summary(brain, days=7)
        assert len(summary["by_day"]) >= 1
        assert summary["by_day"][0]["total_tokens"] == 700

    def test_empty_db(self, brain):
        summary = get_usage_summary(brain, days=7)
        assert summary["total_invocations"] == 0
        assert summary["total_tokens"] == 0
        assert summary["by_operation"] == []
        assert summary["by_day"] == []

    def test_resource_filtering_in_events(self, brain):
        """Events with different resource types/ids are stored correctly."""
        record_token_event(
            root=brain,
            session_id="s-r1",
            operation_type=OP_REGEN,
            resource_type="knowledge",
            resource_id="area/a",
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
            session_id="s-r2",
            operation_type=OP_CLASSIFY,
            resource_type="document",
            resource_id="doc-123",
            is_chunk=False,
            model=None,
            input_tokens=200,
            output_tokens=100,
            duration_ms=2000,
            num_turns=1,
            success=True,
        )
        conn = sqlite3.connect(str(brain / ".sync-state.sqlite"))
        knowledge_rows = conn.execute("SELECT COUNT(*) FROM token_events WHERE resource_type = 'knowledge'").fetchone()
        doc_rows = conn.execute("SELECT COUNT(*) FROM token_events WHERE resource_type = 'document'").fetchone()
        conn.close()
        assert knowledge_rows[0] == 1
        assert doc_rows[0] == 1

"""Database lifecycle, pragma verification, and regen state management tests.

Supplements test_state.py (CRUD, migrations) with infrastructure guarantees
and the untested regen lifecycle functions.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from brain_sync.application.insights import save_insight_state
from brain_sync.runtime.repository import (
    SCHEMA_VERSION,
    InsightState,
    _connect,
    reclaim_stale_running_states,
    release_owned_running_states,
)

pytestmark = pytest.mark.unit


@pytest.fixture()
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    conn = _connect(root)
    conn.close()
    return root


# --- Pragma verification ---


class TestDbPragmas:
    def test_wal_mode_enabled(self, brain: Path):
        conn = _connect(brain)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
        finally:
            conn.close()

    def test_foreign_keys_enabled(self, brain: Path):
        conn = _connect(brain)
        try:
            fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert fk == 1
        finally:
            conn.close()

    def test_synchronous_normal(self, brain: Path):
        conn = _connect(brain)
        try:
            sync = conn.execute("PRAGMA synchronous").fetchone()[0]
            assert sync == 1  # NORMAL
        finally:
            conn.close()

    def test_double_connect_same_schema(self, brain: Path):
        conn1 = _connect(brain)
        conn2 = _connect(brain)
        try:
            v1 = conn1.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
            v2 = conn2.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()[0]
            assert int(v1) == SCHEMA_VERSION
            assert int(v2) == SCHEMA_VERSION
        finally:
            conn1.close()
            conn2.close()


# --- reclaim_stale_running_states ---


class TestReclaimStaleRunningStates:
    def test_resets_old(self, brain: Path):
        old_time = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/topic",
                regen_status="running",
                regen_started_utc=old_time,
                owner_id="old-session",
            ),
        )

        count = reclaim_stale_running_states(brain, stale_threshold_secs=60.0)
        assert count == 1

        conn = _connect(brain)
        try:
            row = conn.execute(
                "SELECT regen_status, owner_id FROM regen_locks WHERE knowledge_path = ?",
                ("area/topic",),
            ).fetchone()
            assert row[0] == "idle"
            assert row[1] is None
        finally:
            conn.close()

    def test_skips_recent(self, brain: Path):
        now = datetime.now(UTC).isoformat()
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/fresh",
                regen_status="running",
                regen_started_utc=now,
                owner_id="active-session",
            ),
        )

        count = reclaim_stale_running_states(brain, stale_threshold_secs=600.0)
        assert count == 0

    def test_malformed_timestamp(self, brain: Path):
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/bad-ts",
                regen_status="running",
                regen_started_utc="not-a-date",
                owner_id="broken-session",
            ),
        )

        count = reclaim_stale_running_states(brain, stale_threshold_secs=60.0)
        assert count == 1


# --- release_owned_running_states ---


class TestReleaseOwnedRunningStates:
    def test_only_own_session(self, brain: Path):
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/mine",
                regen_status="running",
                regen_started_utc=datetime.now(UTC).isoformat(),
                owner_id="session-A",
            ),
        )
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/theirs",
                regen_status="running",
                regen_started_utc=datetime.now(UTC).isoformat(),
                owner_id="session-B",
            ),
        )

        count = release_owned_running_states(brain, owner_id="session-A")
        assert count == 1

        conn = _connect(brain)
        try:
            mine = conn.execute(
                "SELECT regen_status FROM regen_locks WHERE knowledge_path = ?",
                ("area/mine",),
            ).fetchone()
            theirs = conn.execute(
                "SELECT regen_status FROM regen_locks WHERE knowledge_path = ?",
                ("area/theirs",),
            ).fetchone()
            assert mine[0] == "idle"
            assert theirs[0] == "running"
        finally:
            conn.close()

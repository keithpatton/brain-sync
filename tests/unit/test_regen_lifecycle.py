"""Tests for brain_sync.regen.lifecycle — session ownership and cleanup."""

from __future__ import annotations

import asyncio

import pytest

from brain_sync.application.insights import InsightState, load_insight_state, save_insight_state
from brain_sync.application.source_state import SyncState, save_state
from brain_sync.regen.lifecycle import regen_session
from brain_sync.runtime.repository import acquire_regen_ownership

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path):
    save_state(tmp_path, SyncState())  # ensure DB exists
    return tmp_path


class TestRegenSession:
    async def test_yields_session_with_owner_id(self, brain):
        async with regen_session(brain) as session:
            assert session.owner_id
            assert len(session.owner_id) == 32  # uuid4 hex
            assert session.root == brain

    async def test_different_sessions_get_different_ids(self, brain):
        async with regen_session(brain) as s1:
            id1 = s1.owner_id
        async with regen_session(brain) as s2:
            id2 = s2.owner_id
        assert id1 != id2

    async def test_releases_owned_running_states_on_exit(self, brain):
        async with regen_session(brain) as session:
            # Simulate a running insight owned by this session
            save_insight_state(
                brain,
                InsightState(
                    knowledge_path="area/foo",
                    regen_status="idle",
                ),
            )
            assert acquire_regen_ownership(brain, "area/foo", session.owner_id)
            save_insight_state(
                brain,
                InsightState(
                    knowledge_path="area/foo",
                    regen_status="running",
                ),
            )

        # After exit, the running state should be released (set to idle)
        loaded = load_insight_state(brain, "area/foo")
        assert loaded is not None
        assert loaded.regen_status == "idle"

    async def test_does_not_release_other_owners_states(self, brain):
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/bar",
                regen_status="idle",
            ),
        )
        assert acquire_regen_ownership(brain, "area/bar", "other-owner-id")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/bar",
                regen_status="running",
            ),
        )

        async with regen_session(brain):
            pass  # session exits

        # Other owner's state should still be running
        loaded = load_insight_state(brain, "area/bar")
        assert loaded is not None
        assert loaded.regen_status == "running"
        assert loaded.owner_id == "other-owner-id"


class TestReclaim:
    async def test_reclaims_stale_states(self, brain):
        from datetime import UTC, datetime, timedelta

        stale_time = (datetime.now(UTC) - timedelta(seconds=1200)).isoformat()
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/stale",
                regen_status="idle",
            ),
        )
        assert acquire_regen_ownership(brain, "area/stale", "crashed-owner")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/stale",
                regen_status="running",
                regen_started_utc=stale_time,
            ),
        )

        async with regen_session(brain, reclaim_stale=True, stale_threshold_secs=600.0):
            loaded = load_insight_state(brain, "area/stale")
            assert loaded is not None
            assert loaded.regen_status == "idle"

    async def test_does_not_reclaim_recent_states(self, brain):
        from datetime import UTC, datetime

        recent_time = datetime.now(UTC).isoformat()
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/active",
                regen_status="idle",
            ),
        )
        assert acquire_regen_ownership(brain, "area/active", "active-owner")
        save_insight_state(
            brain,
            InsightState(
                knowledge_path="area/active",
                regen_status="running",
                regen_started_utc=recent_time,
            ),
        )

        async with regen_session(brain, reclaim_stale=True, stale_threshold_secs=600.0):
            loaded = load_insight_state(brain, "area/active")
            assert loaded is not None
            assert loaded.regen_status == "running"


class TestCleanupOnException:
    async def test_releases_states_on_exception(self, brain):
        with pytest.raises(ValueError, match="test error"):
            async with regen_session(brain) as session:
                save_insight_state(
                    brain,
                    InsightState(
                        knowledge_path="area/err",
                        regen_status="idle",
                    ),
                )
                assert acquire_regen_ownership(brain, "area/err", session.owner_id)
                save_insight_state(
                    brain,
                    InsightState(
                        knowledge_path="area/err",
                        regen_status="running",
                    ),
                )
                raise ValueError("test error")

        loaded = load_insight_state(brain, "area/err")
        assert loaded is not None
        assert loaded.regen_status == "idle"

    async def test_releases_states_on_cancellation(self, brain):
        released = False

        async def cancellable():
            nonlocal released
            async with regen_session(brain) as session:
                save_insight_state(
                    brain,
                    InsightState(
                        knowledge_path="area/cancel",
                        regen_status="idle",
                    ),
                )
                assert acquire_regen_ownership(brain, "area/cancel", session.owner_id)
                save_insight_state(
                    brain,
                    InsightState(
                        knowledge_path="area/cancel",
                        regen_status="running",
                    ),
                )
                await asyncio.sleep(100)  # will be cancelled

        task = asyncio.create_task(cancellable())
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        loaded = load_insight_state(brain, "area/cancel")
        assert loaded is not None
        assert loaded.regen_status == "idle"

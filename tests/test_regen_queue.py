"""Tests for the regen event queue."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from brain_sync.regen_queue import (
    DEFAULT_COOLDOWN_SECS,
    DEFAULT_DEBOUNCE_SECS,
    DEFAULT_MAX_REGENS_PER_HOUR,
    MAX_RETRIES,
    RegenQueue,
)
from brain_sync.state import InsightState, _connect, save_insight_state


@pytest.fixture
def brain(tmp_path):
    root = tmp_path / "brain"
    root.mkdir()
    (root / "knowledge").mkdir()
    (root / "insights").mkdir()
    conn = _connect(root)
    conn.close()
    return root


class TestEnqueueAndDebounce:
    def test_enqueue_creates_pending(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.1)
        q.enqueue("project")
        assert q.has_pending()

    def test_debounce_delays_processing(self, brain):
        q = RegenQueue(root=brain, debounce_secs=10.0)
        q.enqueue("project")
        ready = q.pop_ready()
        assert ready == []  # Not ready yet, debounce hasn't expired

    def test_ready_after_debounce(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0)
        q.enqueue("project")
        # With 0 debounce, should be ready immediately
        ready = q.pop_ready()
        assert "project" in ready

    def test_debounce_resets_on_new_event(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.05)
        q.enqueue("project")
        time.sleep(0.03)
        q.enqueue("project")  # Reset debounce
        ready = q.pop_ready()
        assert ready == []  # Timer was reset

    def test_multiple_paths_independent(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0)
        q.enqueue("project-a")
        q.enqueue("project-b")
        ready = q.pop_ready()
        assert set(ready) == {"project-a", "project-b"}


class TestCooldown:
    def test_cooldown_blocks_immediate_requeue(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=10.0)
        # Simulate a completed regen
        q._last_regen["project"] = time.monotonic()
        q.enqueue("project")
        ready = q.pop_ready()
        assert ready == []  # On cooldown

    def test_ready_after_cooldown_expires(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=0.0)
        q._last_regen["project"] = time.monotonic() - 1.0
        q.enqueue("project")
        ready = q.pop_ready()
        assert "project" in ready


class TestRateLimiting:
    def test_rate_limit_blocks_excess(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, max_regens_per_hour=2)
        # Fill up the rate limit
        q._regen_times = [time.monotonic(), time.monotonic()]
        q.enqueue("project")
        ready = q.pop_ready()
        assert ready == []  # Rate limited

    def test_old_regens_expire_from_limit(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, max_regens_per_hour=2)
        # Old timestamps (>1 hour ago) shouldn't count
        old = time.monotonic() - 3700
        q._regen_times = [old, old]
        q.enqueue("project")
        ready = q.pop_ready()
        assert "project" in ready


class TestProcessReady:
    def test_process_calls_regen_path(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=0.0)
        q.enqueue("project")

        with patch("brain_sync.regen_queue.regen_path", new_callable=AsyncMock, return_value=1) as mock_regen:
            count = asyncio.run(q.process_ready())

        assert count == 1
        mock_regen.assert_called_once_with(brain, "project")

    def test_process_empty_queue(self, brain):
        q = RegenQueue(root=brain)
        count = asyncio.run(q.process_ready())
        assert count == 0

    def test_process_updates_last_regen(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=0.0)
        q.enqueue("project")

        with patch("brain_sync.regen_queue.regen_path", new_callable=AsyncMock, return_value=1):
            asyncio.run(q.process_ready())

        assert "project" in q._last_regen

    def test_failure_requeues_with_backoff(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=0.0)
        q.enqueue("project")

        async def fail(*args, **kwargs):
            raise RuntimeError("Claude unavailable")

        with patch("brain_sync.regen_queue.regen_path", side_effect=fail):
            asyncio.run(q.process_ready())

        # Should be re-enqueued
        assert q.has_pending()
        assert q._pending["project"].retry_count == 1

    def test_max_retries_drops_event(self, brain):
        """After MAX_RETRIES queue-level failures, event is dropped."""
        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=0.0)

        async def fail(*args, **kwargs):
            raise RuntimeError("Claude unavailable")

        # Simulate MAX_RETRIES failures through the queue
        with patch("brain_sync.regen_queue.regen_path", side_effect=fail):
            for i in range(MAX_RETRIES + 1):
                if i == 0:
                    q.enqueue("project")
                # Process each failure — the queue re-enqueues with backoff
                # Set fire_at to now so it's immediately ready
                if "project" in q._pending:
                    q._pending["project"].fire_at = 0
                asyncio.run(q.process_ready())

        # After MAX_RETRIES re-enqueues, the event should be dropped
        assert not q.has_pending()


    def test_regen_failed_is_caught_and_reenqueued(self, brain):
        """RegenFailed exception is caught by the queue and re-enqueued."""
        from brain_sync.regen import RegenFailed

        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=0.0)
        q.enqueue("project")

        async def fail_regen(*args, **kwargs):
            raise RegenFailed("project", "Claude CLI failed")

        with patch("brain_sync.regen_queue.regen_path", side_effect=fail_regen):
            asyncio.run(q.process_ready())

        # Should be re-enqueued with retry_count=1
        assert q.has_pending()
        assert q._pending["project"].retry_count == 1


class TestNextFireIn:
    def test_none_when_empty(self, brain):
        q = RegenQueue(root=brain)
        assert q.next_fire_in() is None

    def test_returns_seconds(self, brain):
        q = RegenQueue(root=brain, debounce_secs=10.0)
        q.enqueue("project")
        remaining = q.next_fire_in()
        assert remaining is not None
        assert 0 < remaining <= 10.0

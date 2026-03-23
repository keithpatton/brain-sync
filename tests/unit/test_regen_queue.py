"""Tests for the regen event queue."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from brain_sync.application.insights import load_insight_state
from brain_sync.regen.engine import ClaudeResult
from brain_sync.regen.queue import (
    MAX_RETRIES,
    RegenQueue,
)
from brain_sync.runtime.repository import (
    RegenLock,
    _connect,
    acquire_regen_ownership,
    load_operational_events,
    save_regen_lock,
)

pytestmark = pytest.mark.unit


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
        q._regen_times = deque([time.monotonic(), time.monotonic()])
        q.enqueue("project")
        ready = q.pop_ready()
        assert ready == []  # Rate limited

    def test_old_regens_expire_from_limit(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, max_regens_per_hour=2)
        # Old timestamps (>1 hour ago) shouldn't count
        old = time.monotonic() - 3700
        q._regen_times = deque([old, old])
        q.enqueue("project")
        ready = q.pop_ready()
        assert "project" in ready


class TestProcessReady:
    def test_process_single_ready_path_uses_explicit_walk_up(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=0.0)
        q.enqueue("project")

        async def _single_folder(root, knowledge_path, **kwargs):
            del root, kwargs
            if knowledge_path == "project":
                return SimpleNamespace(action="regenerated")
            return SimpleNamespace(action="skipped_unchanged")

        with (
            patch("brain_sync.regen.queue.acquire_regen_ownership", return_value=True),
            patch("brain_sync.regen.queue.regen_single_folder", side_effect=_single_folder) as mock_single,
        ):
            count = asyncio.run(q.process_ready())

        assert count == 1
        assert [call.args[1] for call in mock_single.call_args_list] == ["project", ""]

    def test_process_empty_queue(self, brain):
        q = RegenQueue(root=brain)
        count = asyncio.run(q.process_ready())
        assert count == 0

    def test_process_updates_last_regen(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=0.0)
        q.enqueue("project")

        async def _single_folder(root, knowledge_path, **kwargs):
            del root, kwargs
            return SimpleNamespace(action="regenerated" if knowledge_path == "project" else "skipped_unchanged")

        with (
            patch("brain_sync.regen.queue.acquire_regen_ownership", return_value=True),
            patch("brain_sync.regen.queue.regen_single_folder", side_effect=_single_folder),
        ):
            asyncio.run(q.process_ready())

        assert "project" in q._last_regen

    def test_failure_requeues_with_backoff(self, brain):
        q = RegenQueue(root=brain, debounce_secs=0.0, cooldown_secs=0.0)
        q.enqueue("project")

        async def fail(*args, **kwargs):
            raise RuntimeError("Claude unavailable")

        with (
            patch("brain_sync.regen.queue.acquire_regen_ownership", return_value=True),
            patch("brain_sync.regen.queue.regen_single_folder", side_effect=fail),
        ):
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
        with (
            patch("brain_sync.regen.queue.acquire_regen_ownership", return_value=True),
            patch("brain_sync.regen.queue.regen_single_folder", side_effect=fail),
        ):
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

        with (
            patch("brain_sync.regen.queue.acquire_regen_ownership", return_value=True),
            patch("brain_sync.regen.queue.regen_single_folder", side_effect=fail_regen),
        ):
            asyncio.run(q.process_ready())

        # Should be re-enqueued with retry_count=1
        assert q.has_pending()
        assert q._pending["project"].retry_count == 1

    def test_lock_contention_exhaustion_records_classified_failure(self, brain):
        q = RegenQueue(root=brain, owner_id="owner-1", session_id="session-1", debounce_secs=0.0, cooldown_secs=0.0)
        save_regen_lock(brain, RegenLock(knowledge_path="project", regen_status="idle"))
        q.enqueue("project")

        error = PermissionError(13, "Access is denied", "project")
        error.winerror = 5  # type: ignore[attr-defined]

        async def fail(*args, **kwargs):
            raise error

        with (
            patch("brain_sync.regen.queue.acquire_regen_ownership", return_value=True),
            patch("brain_sync.regen.queue.regen_single_folder", side_effect=fail),
        ):
            for _ in range(MAX_RETRIES + 1):
                if "project" in q._pending:
                    q._pending["project"].fire_at = 0
                asyncio.run(q.process_ready())

        state = load_insight_state(brain, "project")
        assert state is not None
        assert state.regen_status == "failed"
        assert state.owner_id is None
        assert state.error_reason is not None
        assert "lock contention" in state.error_reason.lower()
        assert acquire_regen_ownership(brain, "project", "owner-2")
        failed_events = [
            event
            for event in load_operational_events(brain)
            if event.event_type == "regen.failed" and event.knowledge_path == "project"
        ]
        assert failed_events
        assert '"reason": "queue_lock_contention_deferred"' in (failed_events[-1].details_json or "")


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


class TestWaveProcessing:
    """Tests for wave-based multi-path processing in process_ready."""

    def test_process_ready_wave_deduplicates(self, brain):
        """Multiple siblings processed via waves: parent gets 1 call, not N."""
        # Create sibling knowledge dirs
        for name in ("area/sub1", "area/sub2", "area/sub3"):
            kdir = brain / "knowledge" / name
            kdir.mkdir(parents=True, exist_ok=True)
            (kdir / "doc.md").write_text(f"# {name}", encoding="utf-8")
        # Parent has its own file
        (brain / "knowledge" / "area" / "overview.md").write_text("# Area overview", encoding="utf-8")

        call_paths: list[str] = []

        async def track_invoke(prompt: str, cwd, **kwargs):
            for line in prompt.split("\n"):
                if "regenerating the insight summary for knowledge area:" in line:
                    area = line.split(":")[-1].strip()
                    call_paths.append(area)
                    break
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        q = RegenQueue(root=brain, debounce_secs=0.0)
        q.enqueue("area/sub1")
        q.enqueue("area/sub2")
        q.enqueue("area/sub3")

        with (
            patch("brain_sync.regen.queue.acquire_regen_ownership", return_value=True),
            patch("brain_sync.regen.engine.invoke_claude", side_effect=track_invoke),
        ):
            asyncio.run(q.process_ready())

        # Parent "area" should appear at most once (wave scheduling)
        assert call_paths.count("area") <= 1

    def test_process_ready_ancestor_ownership_required(self, brain):
        """If ancestor ownership fails in wave mode, skip it and don't propagate."""
        # Need 2+ paths to trigger wave mode (single path uses regen_path fast path)
        for name in ("area/sub1", "area/sub2"):
            kdir = brain / "knowledge" / name
            kdir.mkdir(parents=True, exist_ok=True)
            (kdir / "doc.md").write_text(f"# {name}", encoding="utf-8")

        call_paths: list[str] = []

        async def track_invoke(prompt: str, cwd, **kwargs):
            for line in prompt.split("\n"):
                if "regenerating the insight summary for knowledge area:" in line:
                    call_paths.append(line.split(":")[-1].strip())
                    break
            return ClaudeResult(success=True, output="# Summary\n\nGenerated insight summary content.")

        def ownership_fails_for_area(root, path, owner_id, timeout):
            # Fail for "area" ancestor, succeed for everything else
            return path != "area"

        q = RegenQueue(root=brain, debounce_secs=0.0)
        q.enqueue("area/sub1")
        q.enqueue("area/sub2")

        with (
            patch("brain_sync.regen.queue.acquire_regen_ownership", side_effect=ownership_fails_for_area),
            patch("brain_sync.regen.engine.invoke_claude", side_effect=track_invoke),
        ):
            asyncio.run(q.process_ready())

        # Subs should be processed, but area (ownership failed) should not
        assert "area/sub1" in call_paths
        assert "area/sub2" in call_paths
        assert "area" not in call_paths

    def test_process_ready_single_path_does_not_use_hidden_regen_path(self, brain):
        """Single ready path should use the explicit queue walk-up strategy."""
        q = RegenQueue(root=brain, debounce_secs=0.0)
        q.enqueue("project")

        async def _single_folder(root, knowledge_path, **kwargs):
            del root, kwargs
            if knowledge_path == "project":
                return SimpleNamespace(action="skipped_unchanged")
            raise AssertionError("walk-up should stop before parent call")

        with (
            patch("brain_sync.regen.queue.acquire_regen_ownership", return_value=True),
            patch("brain_sync.regen.queue.regen_single_folder", side_effect=_single_folder) as mock_rsf,
        ):
            total = asyncio.run(q.process_ready())

        assert [call.args[1] for call in mock_rsf.call_args_list] == ["project"]
        assert total == 0

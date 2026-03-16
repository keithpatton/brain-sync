from datetime import UTC, datetime, timedelta

import pytest

from brain_sync.scheduler import BASE_INTERVAL, Scheduler, _jittered, compute_interval, compute_next_check_utc

pytestmark = pytest.mark.unit


class TestComputeInterval:
    def test_never_changed_returns_base(self):
        assert compute_interval(None) == BASE_INTERVAL

    def test_recently_changed_returns_base(self):
        now = datetime.now(UTC).isoformat()
        assert compute_interval(now) == BASE_INTERVAL

    def test_unchanged_8_days(self):
        ts = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        assert compute_interval(ts) == 3600  # 1 hour

    def test_unchanged_15_days(self):
        ts = (datetime.now(UTC) - timedelta(days=15)).isoformat()
        assert compute_interval(ts) == 4 * 3600  # 4 hours

    def test_unchanged_22_days(self):
        ts = (datetime.now(UTC) - timedelta(days=22)).isoformat()
        assert compute_interval(ts) == 12 * 3600  # 12 hours

    def test_unchanged_91_days(self):
        ts = (datetime.now(UTC) - timedelta(days=91)).isoformat()
        assert compute_interval(ts) == 24 * 3600  # 24 hours


class TestComputeNextCheckUtc:
    def test_uses_interval_offset_from_now(self):
        now = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)
        assert compute_next_check_utc(1800, now=now) == "2026-03-17T12:30:00+00:00"


class TestScheduler:
    def test_schedule_and_pop_due(self):
        s = Scheduler()
        s.schedule("a", delay_secs=0)
        s.schedule("b", delay_secs=0)
        due = s.pop_due()
        assert set(due) == {"a", "b"}

    def test_not_due_yet(self):
        s = Scheduler()
        s.schedule("a", delay_secs=9999)
        due = s.pop_due()
        assert due == []

    def test_schedule_immediate_overrides(self):
        s = Scheduler()
        s.schedule("a", delay_secs=9999)
        s.schedule_immediate("a")
        due = s.pop_due()
        assert "a" in due

    def test_reschedule(self):
        s = Scheduler()
        s.schedule("a", delay_secs=0)
        s.pop_due()
        s.reschedule("a", interval_secs=0)
        due = s.pop_due()
        assert "a" in due

    def test_remove_prevents_pop(self):
        s = Scheduler()
        s.schedule("a", delay_secs=0)
        s.remove("a")
        due = s.pop_due()
        assert "a" not in due

    def test_next_due_in(self):
        s = Scheduler()
        s.schedule("a", delay_secs=100)
        ndi = s.next_due_in()
        assert ndi is not None
        assert 99 < ndi <= 100

    def test_next_due_in_empty(self):
        s = Scheduler()
        assert s.next_due_in() is None

    def test_no_duplicate_scheduling(self):
        s = Scheduler()
        s.schedule("a", delay_secs=0)
        s.schedule("a", delay_secs=0)  # should be ignored
        due = s.pop_due()
        assert due.count("a") == 1


class TestJitter:
    def test_jitter_within_bounds(self):
        for _ in range(100):
            result = _jittered(1000)
            assert 800 <= result <= 1200

    def test_jitter_spread(self):
        """Verify jitter actually varies (not constant)."""
        results = {_jittered(1000) for _ in range(50)}
        assert len(results) > 1

    def test_reschedule_uses_jitter(self):
        s = Scheduler()
        s.schedule("a", delay_secs=0)
        s.pop_due()
        s.reschedule("a", interval_secs=1000)
        ndi = s.next_due_in()
        assert ndi is not None
        assert 799 < ndi <= 1200


class TestScheduleFromPersisted:
    def test_none_schedules_immediately(self):
        s = Scheduler()
        s.schedule_from_persisted("a", None, None)
        due = s.pop_due()
        assert "a" in due

    def test_past_schedules_immediately(self):
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        s = Scheduler()
        s.schedule_from_persisted("a", past, 3600)
        due = s.pop_due()
        assert "a" in due

    def test_future_schedules_with_delay(self):
        future = (datetime.now(UTC) + timedelta(seconds=100)).isoformat()
        s = Scheduler()
        s.schedule_from_persisted("a", future, 3600)
        due = s.pop_due()
        assert "a" not in due
        ndi = s.next_due_in()
        assert ndi is not None
        assert 98 < ndi <= 101

    def test_far_future_clamped(self):
        far = (datetime.now(UTC) + timedelta(days=60)).isoformat()
        s = Scheduler()
        s.schedule_from_persisted("a", far, 3600)
        ndi = s.next_due_in()
        assert ndi is not None
        # Should be clamped to interval_seconds (3600), not 60 days
        assert ndi <= 3601

    def test_invalid_timestamp_schedules_immediately(self):
        s = Scheduler()
        s.schedule_from_persisted("a", "not-a-date", None)
        due = s.pop_due()
        assert "a" in due

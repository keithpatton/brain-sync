import time
from datetime import datetime, timedelta, timezone

from brain_sync.scheduler import BASE_INTERVAL, Scheduler, compute_interval


class TestComputeInterval:
    def test_never_changed_returns_base(self):
        assert compute_interval(None) == BASE_INTERVAL

    def test_recently_changed_returns_base(self):
        now = datetime.now(timezone.utc).isoformat()
        assert compute_interval(now) == BASE_INTERVAL

    def test_unchanged_8_days(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
        assert compute_interval(ts) == 4 * 3600  # 4 hours

    def test_unchanged_15_days(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=15)).isoformat()
        assert compute_interval(ts) == 12 * 3600  # 12 hours

    def test_unchanged_22_days(self):
        ts = (datetime.now(timezone.utc) - timedelta(days=22)).isoformat()
        assert compute_interval(ts) == 7 * 24 * 3600  # 7 days


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

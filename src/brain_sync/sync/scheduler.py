from __future__ import annotations

import heapq
import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

BASE_INTERVAL = 1800  # 30 minutes
MAX_ERROR_BACKOFF = 86400  # 24 hours
MAX_FUTURE_CLAMP = 30 * 24 * 3600  # 30 days

# (unchanged_days_threshold, interval_seconds)
BACKOFF_TIERS = [
    (90, 24 * 3600),  # 3+ months stable → 24 hours
    (21, 12 * 3600),  # 3+ weeks stable  → 12 hours
    (14, 4 * 3600),  # 2+ weeks stable  → 4 hours
    (7, 3600),  # 1+ week stable   → 1 hour
    (0, BASE_INTERVAL),  # recently changed  → 30 minutes
]


def compute_interval(last_changed_utc: str | None) -> int:
    if last_changed_utc is None:
        return BASE_INTERVAL

    last_changed = datetime.fromisoformat(last_changed_utc)
    days_unchanged = (datetime.now(UTC) - last_changed).days

    for threshold, interval in BACKOFF_TIERS:
        if days_unchanged >= threshold:
            return interval

    return BASE_INTERVAL


def compute_next_check_utc(interval_secs: int, *, now: datetime | None = None) -> str:
    """Return the next due timestamp persisted for restart-safe scheduling."""
    current = now or datetime.now(UTC)
    return (current + timedelta(seconds=interval_secs)).isoformat()


def _jittered(interval_secs: int) -> float:
    """Apply ±20% random jitter to spread out polling."""
    jitter = interval_secs * 0.2
    return interval_secs + random.uniform(-jitter, jitter)


@dataclass(order=True)
class ScheduledCheck:
    next_check: float
    source_key: str = field(compare=False)


class Scheduler:
    def __init__(self) -> None:
        self._heap: list[ScheduledCheck] = []
        self._scheduled_keys: set[str] = set()
        self._scheduled_deadlines: dict[str, float] = {}

    def schedule(self, source_key: str, delay_secs: float = 0) -> None:
        if source_key in self._scheduled_keys:
            return
        next_check = time.monotonic() + delay_secs
        entry = ScheduledCheck(
            next_check=next_check,
            source_key=source_key,
        )
        heapq.heappush(self._heap, entry)
        self._scheduled_keys.add(source_key)
        self._scheduled_deadlines[source_key] = next_check

    def schedule_immediate(self, source_key: str) -> None:
        self.remove(source_key)
        self.schedule(source_key, delay_secs=0)

    def schedule_from_persisted(
        self, source_key: str, next_check_utc: str | None, interval_seconds: int | None
    ) -> None:
        """Schedule a source using persisted timing from DB."""
        if source_key in self._scheduled_keys:
            return
        if next_check_utc is None:
            self.schedule(source_key, delay_secs=0)
            return

        try:
            next_dt = datetime.fromisoformat(next_check_utc)
        except (ValueError, TypeError):
            self.schedule(source_key, delay_secs=0)
            return

        now = datetime.now(UTC)
        delta = (next_dt - now).total_seconds()

        # Clamp: if too far in the future, use interval instead
        if delta > MAX_FUTURE_CLAMP:
            delta = float(interval_seconds) if interval_seconds else 0

        # If in the past, schedule immediately
        if delta < 0:
            delta = 0

        self.schedule(source_key, delay_secs=delta)

    def pop_due(self) -> list[str]:
        now = time.monotonic()
        due: list[str] = []
        while self._heap and self._heap[0].next_check <= now:
            entry = heapq.heappop(self._heap)
            if (
                entry.source_key in self._scheduled_keys
                and self._scheduled_deadlines.get(entry.source_key) == entry.next_check
            ):
                self._scheduled_keys.discard(entry.source_key)
                self._scheduled_deadlines.pop(entry.source_key, None)
                due.append(entry.source_key)
        return due

    def reschedule(self, source_key: str, interval_secs: int) -> None:
        self.remove(source_key)
        self.schedule(source_key, delay_secs=_jittered(interval_secs))

    def remove(self, source_key: str) -> None:
        self._scheduled_keys.discard(source_key)
        self._scheduled_deadlines.pop(source_key, None)

    def next_due_in(self) -> float | None:
        while self._heap:
            head = self._heap[0]
            if (
                head.source_key in self._scheduled_keys
                and self._scheduled_deadlines.get(head.source_key) == head.next_check
            ):
                return max(0, head.next_check - time.monotonic())
            heapq.heappop(self._heap)
        return None

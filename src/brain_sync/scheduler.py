from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

BASE_INTERVAL = 3600          # 1 hour
MAX_ERROR_BACKOFF = 86400     # 24 hours

# (unchanged_days_threshold, interval_seconds)
BACKOFF_TIERS = [
    (21, 7 * 24 * 3600),   # 7 days
    (14, 12 * 3600),        # 12 hours
    (7, 4 * 3600),          # 4 hours
    (0, BASE_INTERVAL),     # 1 hour
]


def compute_interval(last_changed_utc: str | None) -> int:
    if last_changed_utc is None:
        return BASE_INTERVAL

    last_changed = datetime.fromisoformat(last_changed_utc)
    days_unchanged = (datetime.now(timezone.utc) - last_changed).days

    for threshold, interval in BACKOFF_TIERS:
        if days_unchanged >= threshold:
            return interval

    return BASE_INTERVAL


@dataclass(order=True)
class ScheduledCheck:
    next_check: float
    source_key: str = field(compare=False)


class Scheduler:
    def __init__(self) -> None:
        self._heap: list[ScheduledCheck] = []
        self._scheduled_keys: set[str] = set()

    def schedule(self, source_key: str, delay_secs: float = 0) -> None:
        if source_key in self._scheduled_keys:
            return
        entry = ScheduledCheck(
            next_check=time.monotonic() + delay_secs,
            source_key=source_key,
        )
        heapq.heappush(self._heap, entry)
        self._scheduled_keys.add(source_key)

    def schedule_immediate(self, source_key: str) -> None:
        self._scheduled_keys.discard(source_key)
        self.schedule(source_key, delay_secs=0)

    def pop_due(self) -> list[str]:
        now = time.monotonic()
        due: list[str] = []
        while self._heap and self._heap[0].next_check <= now:
            entry = heapq.heappop(self._heap)
            if entry.source_key in self._scheduled_keys:
                self._scheduled_keys.discard(entry.source_key)
                due.append(entry.source_key)
        return due

    def reschedule(self, source_key: str, interval_secs: int) -> None:
        self._scheduled_keys.discard(source_key)
        self.schedule(source_key, delay_secs=interval_secs)

    def remove(self, source_key: str) -> None:
        self._scheduled_keys.discard(source_key)

    def next_due_in(self) -> float | None:
        while self._heap:
            if self._heap[0].source_key in self._scheduled_keys:
                return max(0, self._heap[0].next_check - time.monotonic())
            heapq.heappop(self._heap)
        return None

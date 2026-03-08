"""Regen event queue with debounce, cooldown, and rate limiting.

Events are batched by knowledge path. A path is only processed after its
debounce window elapses (30s from last change). Post-regen cooldown prevents
re-triggering the same path within 5 minutes.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.regen import regen_path
from brain_sync.state import load_insight_state

log = logging.getLogger(__name__)

DEFAULT_DEBOUNCE_SECS = 30.0
DEFAULT_COOLDOWN_SECS = 300.0  # 5 minutes post-regen cooldown per path
DEFAULT_MAX_REGENS_PER_HOUR = 20
MAX_RETRIES = 3
RETRY_BACKOFFS = [30.0, 60.0, 120.0]


@dataclass
class _PendingRegen:
    """A pending regen event for a knowledge path."""
    knowledge_path: str
    fire_at: float  # monotonic time when debounce expires
    retry_count: int = 0


@dataclass
class RegenQueue:
    """Manages regen events with debounce, cooldown, and rate limiting."""

    root: Path
    debounce_secs: float = DEFAULT_DEBOUNCE_SECS
    cooldown_secs: float = DEFAULT_COOLDOWN_SECS
    max_regens_per_hour: int = DEFAULT_MAX_REGENS_PER_HOUR

    _pending: dict[str, _PendingRegen] = field(default_factory=dict)
    _retry_counts: dict[str, int] = field(default_factory=dict)  # queue-level retry tracking
    _last_regen: dict[str, float] = field(default_factory=dict)  # monotonic time
    _regen_times: list[float] = field(default_factory=list)  # timestamps for rate limiting
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def enqueue(self, knowledge_path: str) -> None:
        """Enqueue a regen event for a knowledge path (resets debounce timer)."""
        now = time.monotonic()
        fire_at = now + self.debounce_secs
        existing = self._pending.get(knowledge_path)
        if existing:
            existing.fire_at = fire_at
            log.debug("Reset debounce for %s", knowledge_path)
        else:
            self._pending[knowledge_path] = _PendingRegen(
                knowledge_path=knowledge_path,
                fire_at=fire_at,
            )
            log.debug("Enqueued regen for %s", knowledge_path)

    def _is_rate_limited(self) -> bool:
        """Check if we've exceeded the hourly regen limit."""
        now = time.monotonic()
        cutoff = now - 3600.0
        self._regen_times = [t for t in self._regen_times if t > cutoff]
        return len(self._regen_times) >= self.max_regens_per_hour

    def _is_on_cooldown(self, knowledge_path: str) -> bool:
        """Check if a path is still in post-regen cooldown."""
        last = self._last_regen.get(knowledge_path)
        if last is None:
            return False
        return (time.monotonic() - last) < self.cooldown_secs

    def pop_ready(self) -> list[str]:
        """Return knowledge paths whose debounce has expired and are ready to process.

        Respects rate limiting and cooldown. Returns an empty list if nothing is ready.
        """
        now = time.monotonic()
        ready: list[str] = []
        still_pending: dict[str, _PendingRegen] = {}

        for path, pending in self._pending.items():
            if now < pending.fire_at:
                still_pending[path] = pending
                continue
            if self._is_on_cooldown(path):
                log.debug("Path %s on cooldown, deferring", path)
                still_pending[path] = pending
                continue
            if self._is_rate_limited():
                log.debug("Rate limited, deferring %s", path)
                still_pending[path] = pending
                continue
            ready.append(path)
            # Preserve retry count before removing from pending
            self._retry_counts[path] = pending.retry_count

        self._pending = still_pending
        return ready

    async def process_ready(self) -> int:
        """Process all ready regen events. Returns count of successful regens."""
        ready = self.pop_ready()
        if not ready:
            return 0

        total = 0
        async with self._lock:
            for knowledge_path in ready:
                now = time.monotonic()

                # Check DB state for running status
                istate = load_insight_state(self.root, knowledge_path)
                if istate and istate.regen_status == "running":
                    # Check if it's stale (>5 min)
                    if istate.last_regen_utc:
                        from datetime import datetime, timezone
                        try:
                            started = datetime.fromisoformat(istate.last_regen_utc)
                            age = (datetime.now(timezone.utc) - started).total_seconds()
                            if age < self.cooldown_secs:
                                log.debug("Regen already running for %s, skipping", knowledge_path)
                                continue
                        except (ValueError, TypeError):
                            pass

                # Queue owns retry budgeting via _retry_counts (see re-enqueue below)

                try:
                    count = await regen_path(self.root, knowledge_path)
                    self._last_regen[knowledge_path] = time.monotonic()
                    self._regen_times.append(time.monotonic())
                    self._retry_counts.pop(knowledge_path, None)
                    total += count
                    log.info(
                        "[regen] path=%s summaries_updated=%d",
                        knowledge_path or "(root)", count,
                    )
                except Exception as e:
                    log.warning("Regen failed for %s: %s", knowledge_path, e)
                    # Re-enqueue with backoff (queue owns retry budgeting)
                    retry = self._retry_counts.get(knowledge_path, 0)
                    if retry < MAX_RETRIES:
                        backoff = RETRY_BACKOFFS[min(retry, len(RETRY_BACKOFFS) - 1)]
                        self._pending[knowledge_path] = _PendingRegen(
                            knowledge_path=knowledge_path,
                            fire_at=time.monotonic() + backoff,
                            retry_count=retry + 1,
                        )

        return total

    def has_pending(self) -> bool:
        """Check if there are any pending regen events."""
        return bool(self._pending)

    def next_fire_in(self) -> float | None:
        """Return seconds until the next pending event fires, or None."""
        if not self._pending:
            return None
        now = time.monotonic()
        earliest = min(p.fire_at for p in self._pending.values())
        return max(0, earliest - now)

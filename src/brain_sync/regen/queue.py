"""Regen event queue with debounce, cooldown, and rate limiting.

Events are batched by knowledge path. A path is only processed after its
debounce window elapses (30s from last change). Post-regen cooldown prevents
re-triggering the same path within 5 minutes.

When multiple paths are ready simultaneously, wave-based scheduling processes
them in depth order (deepest first) with dirty propagation, ensuring each
folder is processed at most once.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from brain_sync.regen import (
    _PROPAGATES_UP,
    _parent_path,
    compute_waves,
    regen_path,
    regen_single_folder,
)
from brain_sync.runtime.repository import RegenLock, acquire_regen_ownership, load_regen_lock, save_regen_lock

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
    owner_id: str | None = None
    session_id: str | None = None
    debounce_secs: float = DEFAULT_DEBOUNCE_SECS
    cooldown_secs: float = DEFAULT_COOLDOWN_SECS
    max_regens_per_hour: int = DEFAULT_MAX_REGENS_PER_HOUR

    _pending: dict[str, _PendingRegen] = field(default_factory=dict)
    _retry_counts: dict[str, int] = field(default_factory=dict)  # queue-level retry tracking
    _last_regen: dict[str, float] = field(default_factory=dict)  # monotonic time
    _regen_times: deque[float] = field(default_factory=deque)  # timestamps for rate limiting
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
        cutoff = time.monotonic() - 3600.0
        while self._regen_times and self._regen_times[0] <= cutoff:
            self._regen_times.popleft()
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
        """Process all ready regen events. Returns count of successful regens.

        Single path: uses regen_path() walk-up (fast path).
        Multiple paths: uses wave-based scheduling with dirty propagation.
        All processing runs under self._lock to prevent interleaved batches.
        """
        ready = self.pop_ready()
        if not ready:
            return 0

        total = 0
        async with self._lock:
            if len(ready) == 1:
                # Fast path: single event, use existing regen_path (walk-up)
                total = await self._process_single(ready[0])
            else:
                # Multi-path: wave scheduling
                total = await self._process_wave(ready)

        return total

    async def _process_single(self, knowledge_path: str) -> int:
        """Process a single ready path using regen_path walk-up."""
        if not acquire_regen_ownership(self.root, knowledge_path, self.owner_id or "", self.cooldown_secs * 2):
            log.debug("Could not acquire regen ownership for %s, skipping", knowledge_path)
            return 0

        try:
            count = await regen_path(self.root, knowledge_path, owner_id=self.owner_id, session_id=self.session_id)
            self._last_regen[knowledge_path] = time.monotonic()
            self._regen_times.append(time.monotonic())
            self._retry_counts.pop(knowledge_path, None)
            log.info("[regen] path=%s summaries_updated=%d", knowledge_path or "(root)", count)
            return count
        except Exception as e:
            self._handle_failure(knowledge_path, e)
            return 0

    async def _process_wave(self, ready: list[str]) -> int:
        """Process multiple ready paths using wave-based scheduling."""
        ready_set = set(ready)
        waves = compute_waves(ready)
        dirty: set[str] = set(ready)  # all enqueued paths start dirty
        total = 0

        for wave in waves:
            for path in wave:
                if path not in dirty:
                    continue

                # Acquire ownership for EVERY path (enqueued or ancestor)
                if not acquire_regen_ownership(self.root, path, self.owner_id or "", self.cooldown_secs * 2):
                    log.debug("Could not acquire ownership for %s, skipping branch", path)
                    continue  # don't propagate from this path

                try:
                    result = await regen_single_folder(
                        self.root, path, owner_id=self.owner_id, session_id=self.session_id
                    )
                    if result.action == "regenerated":
                        total += 1
                    if result.action in _PROPAGATES_UP and path:
                        dirty.add(_parent_path(path))

                    # Cooldown/rate tracking only for directly-enqueued paths
                    if path in ready_set:
                        self._last_regen[path] = time.monotonic()
                        self._regen_times.append(time.monotonic())
                        self._retry_counts.pop(path, None)

                    log.info("[regen] path=%s action=%s", path or "(root)", result.action)
                except Exception as e:
                    log.warning("Regen failed for %s: %s", path or "(root)", e)
                    # Retry only for directly-enqueued paths
                    if path in ready_set:
                        self._handle_failure(path, e)
                    # Failed paths do NOT propagate dirtiness

        return total

    def _handle_failure(self, knowledge_path: str, error: Exception) -> None:
        """Handle a regen failure with retry/backoff or exhaustion."""
        retry = self._retry_counts.get(knowledge_path, 0)
        if retry < MAX_RETRIES:
            backoff = RETRY_BACKOFFS[min(retry, len(RETRY_BACKOFFS) - 1)]
            self._pending[knowledge_path] = _PendingRegen(
                knowledge_path=knowledge_path,
                fire_at=time.monotonic() + backoff,
                retry_count=retry + 1,
            )
        else:
            log.error(
                "Regen retries exhausted for %s after %d attempts: %s",
                knowledge_path,
                MAX_RETRIES,
                error,
            )
            try:
                current_lock = load_regen_lock(self.root, knowledge_path)
                save_regen_lock(
                    self.root,
                    RegenLock(
                        knowledge_path=knowledge_path,
                        regen_started_utc=current_lock.regen_started_utc if current_lock else None,
                        regen_status="failed",
                        error_reason=f"Retries exhausted ({MAX_RETRIES}): {error}",
                        owner_id=self.owner_id,
                    ),
                )
            except Exception as db_err:
                log.error(
                    "Failed to persist 'failed' state for %s: %s (original: %s)",
                    knowledge_path,
                    db_err,
                    error,
                )

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

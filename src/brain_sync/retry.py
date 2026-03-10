"""Async retry with circuit breaker for external service calls.

Provides two primitives:
- ``async_retry``: retries an async callable with jittered exponential backoff
- ``CircuitBreaker``: half-open circuit breaker shared across callers

Designed for the two-tier retry model used by brain-sync:

1. **Immediate** (this module): ~1-4s backoff for transient failures
   (network blips, CLI crashes).
2. **Deferred** (regen_queue): 30-120s backoff for persistent failures
   (service down, bad state).

The circuit breaker prevents retry storms during full regeneration.
Worst case per path is 3 queue x 3 immediate = 9 Claude calls, but in
practice the breaker opens after the first path's 3 failures, so
remaining paths get ``CircuitOpenError`` immediately (~3 total calls).

Scope: the ``claude_breaker`` singleton is **global** — one pathological
prompt can trip the breaker for all paths.  Acceptable for v1; future
options include per-prompt-hash or per-operation scoping.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitOpenError(RuntimeError):
    """Raised when a call is rejected because the circuit breaker is open."""


class CircuitBreaker:
    """Simple async-safe circuit breaker for a single dependency.

    States: Closed → Open (after *failure_threshold* consecutive failures)
    → Half-Open (after *cooldown_secs*) → trial call → Success=Closed /
    Failure=Open.

    No lock needed — single-threaded asyncio event loop.
    """

    def __init__(self, failure_threshold: int = 10, cooldown_secs: float = 120.0):
        self.failure_threshold = failure_threshold
        self.cooldown_secs = cooldown_secs

        self._failures = 0
        self._opened_at: float | None = None
        self._half_open_trial = False

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False

        if time.monotonic() - self._opened_at >= self.cooldown_secs:
            # Transition to half-open: allow one trial call
            self._opened_at = None
            self._failures = 0
            self._half_open_trial = True
            log.info("Circuit breaker entering half-open state, allowing trial call")
            return False

        return True

    def record_success(self) -> None:
        if self._half_open_trial:
            log.info("Circuit breaker closed after successful trial")
        self._failures = 0
        self._half_open_trial = False
        self._opened_at = None

    def record_failure(self) -> None:
        if self._half_open_trial:
            # Immediate reopen
            self._opened_at = time.monotonic()
            self._half_open_trial = False
            log.warning("Circuit breaker reopened after failed half-open trial")
            return

        self._failures += 1
        if self._failures >= self.failure_threshold:
            self._opened_at = time.monotonic()
            log.warning(
                "Circuit breaker opened after %d consecutive failures",
                self._failures,
            )

    def reset(self) -> None:
        """Reset breaker to closed state (useful for tests)."""
        self._failures = 0
        self._opened_at = None
        self._half_open_trial = False


async def async_retry(
    fn: Callable[..., Awaitable[T]],
    *args: object,
    max_retries: int = 2,
    backoff_base: float = 2.0,
    timeout: float | None = None,
    is_success: Callable[[T], bool] = lambda r: bool(r),
    breaker: CircuitBreaker | None = None,
    **kwargs: object,
) -> T:
    """Retry an async callable with jittered exponential backoff.

    Returns the result on success.  Raises ``CircuitOpenError`` if the
    breaker is open, or ``RuntimeError`` if all retries are exhausted.
    """
    for attempt in range(max_retries + 1):
        if breaker and breaker.is_open():
            raise CircuitOpenError("Circuit breaker open")

        try:
            coro = fn(*args, **kwargs)
            result: T = await asyncio.wait_for(coro, timeout) if timeout else await coro

            if is_success(result):
                if breaker:
                    breaker.record_success()
                return result

        except CircuitOpenError:
            raise
        except Exception as exc:
            log.debug("Attempt %d/%d failed: %s", attempt + 1, max_retries + 1, exc)

        # Record failure
        if breaker:
            breaker.record_failure()

        if attempt >= max_retries:
            break

        # Jittered backoff: ~1s, ~2s, ~4s
        delay = (backoff_base ** (attempt + 1)) / 2 + random.uniform(0, 0.5)
        log.info("Call failed (attempt %d/%d), retrying in %.1fs", attempt + 1, max_retries + 1, delay)
        await asyncio.sleep(delay)

    raise RuntimeError(
        f"Retry attempts exhausted ({max_retries + 1} attempts)",
    )


# Shared breaker instance for Claude CLI calls
claude_breaker = CircuitBreaker()

"""Tests for the retry module: CircuitBreaker and async_retry."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from brain_sync.retry import (
    CircuitBreaker,
    CircuitOpenError,
    async_retry,
    claude_breaker,
)

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    @staticmethod
    def _wait_until_trial_allowed(cb: CircuitBreaker, timeout: float = 0.5) -> None:
        deadline = time.monotonic() + timeout
        while cb.is_open():
            if time.monotonic() >= deadline:
                pytest.fail("Circuit breaker did not transition to half-open before timeout")
            time.sleep(0.01)

    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert not cb.is_open()

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert not cb.is_open()

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.is_open()

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        assert not cb.is_open()  # Only 1 consecutive failure

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_secs=0.05)
        cb.record_failure()
        assert cb.is_open()
        # After cooldown, transitions to half-open (allows trial)
        self._wait_until_trial_allowed(cb)

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_secs=0.05)
        cb.record_failure()  # Opens
        assert cb.is_open()
        self._wait_until_trial_allowed(cb)  # Transitions to half-open
        cb.record_success()  # Trial succeeds → closed
        assert not cb.is_open()
        # Should be fully closed, need full threshold to reopen
        cb.record_failure()
        assert cb.is_open()

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_secs=0.05)
        cb.record_failure()  # Opens
        self._wait_until_trial_allowed(cb)  # Transitions to half-open
        cb.record_failure()  # Half-open trial fails → reopen
        assert cb.is_open()

    def test_half_open_allows_only_one_trial_call(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_secs=0.05)
        cb.record_failure()
        self._wait_until_trial_allowed(cb)
        assert cb.is_open()

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.is_open()
        cb.reset()
        assert not cb.is_open()

    def test_cooldown_keeps_open(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_secs=60.0)
        cb.record_failure()
        assert cb.is_open()
        # Still within cooldown
        assert cb.is_open()


# ---------------------------------------------------------------------------
# async_retry
# ---------------------------------------------------------------------------


class TestAsyncRetry:
    def test_success_on_first_attempt(self):
        fn = AsyncMock(return_value=42)
        result = asyncio.run(async_retry(fn, is_success=lambda r: True))
        assert result == 42
        fn.assert_called_once()

    def test_retries_on_failure(self):
        fn = AsyncMock(side_effect=[10, 20, 30])

        with patch("brain_sync.retry.asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                async_retry(
                    fn,
                    max_retries=2,
                    is_success=lambda r: r >= 30,
                )
            )

        assert result == 30
        assert fn.call_count == 3

    def test_raises_after_exhaustion(self):
        fn = AsyncMock(return_value="bad")

        with patch("brain_sync.retry.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(RuntimeError, match="Retry attempts exhausted"):
                asyncio.run(
                    async_retry(
                        fn,
                        max_retries=2,
                        is_success=lambda r: False,
                    )
                )

        assert fn.call_count == 3

    def test_no_retries_when_max_zero(self):
        fn = AsyncMock(return_value="bad")

        with pytest.raises(RuntimeError, match="Retry attempts exhausted"):
            asyncio.run(
                async_retry(
                    fn,
                    max_retries=0,
                    is_success=lambda r: False,
                )
            )

        fn.assert_called_once()

    def test_circuit_open_raises_immediately(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()  # Opens the breaker

        fn = AsyncMock(return_value="ok")

        with pytest.raises(CircuitOpenError):
            asyncio.run(async_retry(fn, breaker=cb, is_success=lambda r: True))

        fn.assert_not_called()

    def test_circuit_open_not_retried(self):
        """CircuitOpenError during retry loop exits immediately."""
        call_count = 0

        async def flaky():
            nonlocal call_count
            call_count += 1
            return "bad"

        cb = CircuitBreaker(failure_threshold=1)
        # First call will fail → breaker opens → second attempt raises CircuitOpenError

        with patch("brain_sync.retry.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(CircuitOpenError):
                asyncio.run(
                    async_retry(
                        flaky,
                        max_retries=5,
                        breaker=cb,
                        is_success=lambda r: False,
                    )
                )

        # Called once, then breaker tripped, no more calls
        assert call_count == 1

    def test_breaker_records_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()

        fn = AsyncMock(return_value="ok")
        asyncio.run(async_retry(fn, breaker=cb, is_success=lambda r: True))

        # Success should reset failures
        assert cb._failures == 0

    def test_exception_in_fn_is_treated_as_failure(self):
        fn = AsyncMock(side_effect=[ValueError("boom"), 42])

        with patch("brain_sync.retry.asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                async_retry(
                    fn,
                    max_retries=1,
                    is_success=lambda r: True,
                )
            )

        assert result == 42

    def test_timeout_per_attempt(self):
        """Timeout applies per attempt, not total."""
        call_count = 0
        real_sleep = asyncio.sleep

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                await real_sleep(10)  # Will timeout
                return "done"
            return "fast"

        with patch("brain_sync.retry.asyncio.sleep", new_callable=AsyncMock):
            result = asyncio.run(
                async_retry(
                    fn,
                    max_retries=1,
                    timeout=0.01,
                    is_success=lambda r: True,
                )
            )

        assert result == "fast"
        assert call_count == 2

    def test_backoff_has_jitter(self):
        """Verify backoff delays are non-zero and vary."""
        fn = AsyncMock(return_value="bad")
        sleep_delays = []

        async def track_sleep(delay):
            sleep_delays.append(delay)

        with patch("brain_sync.retry.asyncio.sleep", side_effect=track_sleep):
            with pytest.raises(RuntimeError):
                asyncio.run(
                    async_retry(
                        fn,
                        max_retries=2,
                        is_success=lambda r: False,
                    )
                )

        assert len(sleep_delays) == 2
        # First delay should be around 1.0-1.5s (2^1/2 + jitter)
        assert 0.5 < sleep_delays[0] < 2.5
        # Second delay should be larger than first
        assert sleep_delays[1] > sleep_delays[0]


# ---------------------------------------------------------------------------
# Module singleton
# ---------------------------------------------------------------------------


class TestClaudeBreaker:
    def test_singleton_exists(self):
        assert claude_breaker is not None
        assert isinstance(claude_breaker, CircuitBreaker)

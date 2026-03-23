"""Phase 1 integration tests: FakeBackend modes and determinism."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from brain_sync.llm.fake import FakeBackend

pytestmark = pytest.mark.integration


class TestFakeStable:
    """Deterministic output from stable mode."""

    async def test_same_prompt_same_output(self):
        """Same prompt must produce identical output."""
        backend = FakeBackend(mode="stable")
        r1 = await backend.invoke("hello world", cwd=Path("."))
        r2 = await backend.invoke("hello world", cwd=Path("."))
        assert r1.output == r2.output
        assert r1.success is True

    async def test_different_prompt_different_output(self):
        """Different prompts must produce different output."""
        backend = FakeBackend(mode="stable")
        r1 = await backend.invoke("prompt alpha", cwd=Path("."))
        r2 = await backend.invoke("prompt beta", cwd=Path("."))
        assert r1.output != r2.output

    async def test_output_contains_fingerprint(self):
        """Output should contain the [fake-XXXX] fingerprint."""
        backend = FakeBackend(mode="stable")
        r = await backend.invoke("test prompt", cwd=Path("."))
        assert "[fake-" in r.output
        assert "<summary>" in r.output
        assert "<journal>" in r.output

    async def test_chunk_calls_return_plain_text_merge_input(self):
        """Chunk calls should return plain-text summaries, not final XML envelopes."""
        backend = FakeBackend(mode="stable")
        r = await backend.invoke("test prompt", cwd=Path("."), is_chunk=True)
        assert "[fake-" in r.output
        assert "<summary>" not in r.output
        assert "<journal>" not in r.output

    async def test_token_counts_proportional(self):
        """Token counts should be proportional to content length."""
        backend = FakeBackend(mode="stable")
        short = await backend.invoke("short", cwd=Path("."))
        long_prompt = "x" * 10000
        long_r = await backend.invoke(long_prompt, cwd=Path("."))
        assert short.input_tokens is not None
        assert long_r.input_tokens is not None
        assert long_r.input_tokens > short.input_tokens

    async def test_call_count_tracking(self):
        """Backend tracks call count and prompts."""
        backend = FakeBackend(mode="stable")
        await backend.invoke("first", cwd=Path("."))
        await backend.invoke("second", cwd=Path("."))
        assert backend.call_count == 2
        assert backend.prompts == ["first", "second"]
        assert backend.last_prompt == "second"


class TestFakeRewrite:
    """Rewrite mode produces similar but different output."""

    async def test_rewrite_differs_from_stable(self):
        """Rewrite mode output should differ from stable mode."""
        stable = FakeBackend(mode="stable")
        rewrite = FakeBackend(mode="rewrite")
        prompt = "test prompt for rewrite"
        r1 = await stable.invoke(prompt, cwd=Path("."))
        r2 = await rewrite.invoke(prompt, cwd=Path("."))
        assert r1.output != r2.output
        assert r2.success is True


class TestFakeFail:
    """Fail mode returns unsuccessful results."""

    async def test_returns_failure(self):
        backend = FakeBackend(mode="fail")
        r = await backend.invoke("anything", cwd=Path("."))
        assert r.success is False
        assert r.output == ""


class TestFakeTimeout:
    """Timeout mode exceeds the caller's timeout."""

    async def test_exceeds_timeout(self):
        """Timeout mode should take longer than the specified timeout."""
        backend = FakeBackend(mode="timeout")
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                backend.invoke("test", cwd=Path("."), timeout=1),
                timeout=2,
            )


class TestFakePartialStream:
    """Partial-stream mode returns truncated output."""

    async def test_truncated_output(self):
        backend = FakeBackend(mode="partial-stream")
        r = await backend.invoke("test", cwd=Path("."))
        assert r.success is True
        assert r.output.endswith("th")  # truncated


class TestFakeMalformed:
    """Malformed mode returns invalid structure."""

    async def test_malformed_output(self):
        backend = FakeBackend(mode="malformed")
        r = await backend.invoke("test", cwd=Path("."))
        assert r.success is True
        assert "NOT VALID" in r.output


class TestFakeLargeOutput:
    """Large-output mode returns ~10KB body."""

    async def test_large_output(self):
        backend = FakeBackend(mode="large-output")
        r = await backend.invoke("test", cwd=Path("."))
        assert r.success is True
        assert len(r.output) > 5000


class TestFakeLatency:
    """Latency parameter introduces async delays."""

    async def test_latency_does_not_block(self):
        """Latency uses asyncio.sleep, not time.sleep."""
        backend = FakeBackend(mode="stable", latency_ms=100)
        r = await backend.invoke("test", cwd=Path("."))
        assert r.success is True

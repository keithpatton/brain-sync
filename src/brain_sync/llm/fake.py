"""Deterministic fake LLM backend for testing.

Supports multiple modes to exercise different code paths in the regen
pipeline.  All delays use ``await asyncio.sleep()`` — never blocking.

Prompt capture is handled identically to the real backend: when
``BRAIN_SYNC_CAPTURE_PROMPTS`` is set, prompts are written to disk.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
from pathlib import Path

from brain_sync.llm.base import BackendCapabilities, LlmResult, capabilities_for_model

TOPIC_FRAGMENTS = [
    "cross-functional alignment",
    "iterative refinement cycles",
    "emergent coordination patterns",
    "dependency resolution strategies",
    "knowledge consolidation",
    "structural invariants",
    "information flow topology",
    "progressive summarisation",
]

PHRASES = [
    "Key themes include",
    "Analysis reveals",
    "The core pattern is",
    "Central to this area is",
    "Notable observations include",
    "The primary focus involves",
]


class FakeBackend:
    """Deterministic fake backend with configurable modes.

    Modes:
        stable       — deterministic output derived from prompt hash
        rewrite      — different seed offset, tests similarity guard
        fail         — returns LlmResult(success=False)
        timeout      — exceeds caller's timeout (async, non-blocking)
        large-output — returns ~10KB body
        partial-stream — returns truncated output
        malformed    — returns invalid structure
    """

    def __init__(self, mode: str = "stable", latency_ms: int = 0):
        self.mode = mode
        self.latency_ms = latency_ms
        self.call_count = 0
        self.last_prompt: str | None = None
        self.prompts: list[str] = []

    def get_capabilities(self, *, model: str = "") -> BackendCapabilities:
        return capabilities_for_model(model)

    async def invoke(
        self,
        prompt: str,
        cwd: Path,
        timeout: int = 300,
        model: str = "",
        effort: str = "",
        max_turns: int = 6,
        system_prompt: str | None = None,
        tools: str | None = None,
        is_chunk: bool = False,
    ) -> LlmResult:
        """Generate deterministic output based on mode."""
        self.call_count += 1
        self.last_prompt = prompt
        self.prompts.append(prompt)
        _capture_prompt(prompt)

        t0 = time.monotonic()

        if self.latency_ms > 0:
            await asyncio.sleep(self.latency_ms / 1000)

        if self.mode == "timeout":
            await asyncio.sleep(timeout + 1)
            return LlmResult(success=False, output="", prompt_text=prompt)

        if self.mode == "fail":
            return LlmResult(success=False, output="", prompt_text=prompt)

        if self.mode == "malformed":
            return LlmResult(
                success=True,
                output="{{NOT VALID MARKDOWN OR STRUCTURED OUTPUT}}",
                input_tokens=len(prompt) // 4,
                output_tokens=10,
                prompt_text=prompt,
            )

        if self.mode == "partial-stream":
            # Truncated output — starts a heading but cuts off
            output = "# Summary\n\nThis analysis covers the key th"
            return LlmResult(
                success=True,
                output=output,
                input_tokens=len(prompt) // 4,
                output_tokens=len(output) // 4,
                prompt_text=prompt,
            )

        if self.mode == "large-output":
            output = _generate_large(prompt)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return LlmResult(
                success=True,
                output=output,
                input_tokens=len(prompt) // 4,
                output_tokens=len(output) // 4,
                duration_ms=elapsed_ms,
                prompt_text=prompt,
            )

        # stable / rewrite
        seed_offset = 0 if self.mode == "stable" else 42
        output = _generate(prompt, seed_offset)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return LlmResult(
            success=True,
            output=output,
            input_tokens=len(prompt) // 4,
            output_tokens=len(output) // 4,
            num_turns=1,
            duration_ms=elapsed_ms,
            prompt_text=prompt,
        )


def _generate(prompt: str, seed_offset: int = 0) -> str:
    """Generate deterministic output fingerprinted by prompt hash."""
    h = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    # Combine hash with offset to create a seed
    seed = int(h, 16) + seed_offset
    rng = random.Random(seed)
    phrase = rng.choice(PHRASES)
    topic = rng.choice(TOPIC_FRAGMENTS)
    detail = rng.choice(TOPIC_FRAGMENTS)
    return f"# Summary\n\n[fake-{h}] {phrase} {topic}. Further analysis shows {detail}."


def _generate_large(prompt: str) -> str:
    """Generate ~10KB output for large-output mode."""
    h = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    rng = random.Random(int(h, 16))
    sections: list[str] = ["# Summary\n"]
    for i in range(20):
        phrase = rng.choice(PHRASES)
        topic = rng.choice(TOPIC_FRAGMENTS)
        sections.append(f"\n## Section {i + 1}\n\n[fake-{h}] {phrase} {topic}. " * 5)
    return "\n".join(sections)


def _capture_prompt(prompt: str) -> None:
    """Write prompt to capture directory if BRAIN_SYNC_CAPTURE_PROMPTS is set."""
    capture_dir = os.environ.get("BRAIN_SYNC_CAPTURE_PROMPTS")
    if not capture_dir:
        return
    try:
        d = Path(capture_dir)
        d.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(prompt.encode()).hexdigest()[:12]
        ts = time.strftime("%Y%m%d_%H%M%S")
        (d / f"{ts}_{h}.prompt.txt").write_text(prompt, encoding="utf-8")
    except OSError:
        pass

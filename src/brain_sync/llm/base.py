"""LLM backend protocol and result type.

All LLM invocation in brain-sync goes through ``LlmBackend.invoke()``.
Concrete backends live in sibling modules (``claude_cli``, ``fake``).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class LlmResult:
    """Result from an LLM invocation."""

    success: bool
    output: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    num_turns: int | None = None
    duration_ms: int | None = None
    prompt_text: str | None = None  # captured when prompt capture is enabled


@runtime_checkable
class LlmBackend(Protocol):
    """Protocol that all LLM backends must satisfy."""

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
    ) -> LlmResult: ...

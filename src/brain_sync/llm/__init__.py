"""LLM backend abstraction layer.

Usage::

    from brain_sync.llm import get_backend, LlmBackend, LlmResult

    backend = get_backend()
    result = await backend.invoke(prompt, cwd=root)
"""

from __future__ import annotations

import os

from brain_sync.llm.base import LlmBackend, LlmResult

__all__ = ["LlmBackend", "LlmResult", "get_backend"]


def get_backend() -> LlmBackend:
    """Resolve the active LLM backend from environment.

    - ``BRAIN_SYNC_LLM_BACKEND=fake`` → ``FakeBackend``
    - Otherwise → ``ClaudeCliBackend``
    """
    backend_name = os.environ.get("BRAIN_SYNC_LLM_BACKEND", "claude")
    if backend_name == "fake":
        from brain_sync.llm.fake import FakeBackend

        mode = os.environ.get("BRAIN_SYNC_FAKE_LLM_MODE", "stable")
        return FakeBackend(mode=mode)
    from brain_sync.llm.claude_cli import ClaudeCliBackend

    return ClaudeCliBackend()

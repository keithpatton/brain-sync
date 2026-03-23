"""LLM backend abstraction and backend resolution.

Owns the model/backend protocol, the bounded capability contract, and
concrete backend selection. It does not own regen policy or telemetry
persistence.

Usage::

    from brain_sync.llm import get_backend, LlmBackend, LlmResult

    backend = get_backend()
    result = await backend.invoke(prompt, cwd=root)
"""

from __future__ import annotations

import os

from brain_sync.llm.base import (
    DEFAULT_BACKEND_CAPABILITIES,
    DEFAULT_SYSTEM_PROMPT,
    BackendCapabilities,
    InvocationContract,
    LlmBackend,
    LlmResult,
    StructuredOutputContract,
    capabilities_for_model,
    resolve_backend_capabilities,
    with_backend_traits,
)

__all__ = [
    "DEFAULT_BACKEND_CAPABILITIES",
    "DEFAULT_SYSTEM_PROMPT",
    "BackendCapabilities",
    "InvocationContract",
    "LlmBackend",
    "LlmResult",
    "StructuredOutputContract",
    "capabilities_for_model",
    "get_backend",
    "resolve_backend_capabilities",
    "with_backend_traits",
]


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

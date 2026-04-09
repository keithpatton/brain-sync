from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from brain_sync.llm.claude_cli import ClaudeCliBackend

pytestmark = pytest.mark.unit


class _FakeProc:
    def __init__(self) -> None:
        self.returncode = 0

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        del input
        return (
            b'{"type":"result","usage":{},"num_turns":1,"is_error":false,"result":"# Summary\\n\\nDone."}\n',
            b"",
        )


@pytest.mark.asyncio
async def test_claude_backend_passes_hidden_process_kwargs_to_subprocess(tmp_path: Path) -> None:
    backend = ClaudeCliBackend()
    observed_kwargs: dict[str, object] = {}

    async def _fake_create_subprocess_exec(*args, **kwargs):
        del args
        observed_kwargs.update(kwargs)
        return _FakeProc()

    with (
        patch(
            "brain_sync.llm.claude_cli.windows_hidden_process_kwargs",
            return_value={"creationflags": 123, "startupinfo": "hidden"},
        ),
        patch(
            "brain_sync.llm.claude_cli.asyncio.create_subprocess_exec",
            side_effect=_fake_create_subprocess_exec,
        ),
    ):
        result = await backend.invoke("Summarise this", Path(tmp_path))

    assert result.success is True
    assert observed_kwargs["creationflags"] == 123
    assert observed_kwargs["startupinfo"] == "hidden"

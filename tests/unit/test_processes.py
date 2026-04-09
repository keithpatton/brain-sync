from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from brain_sync.util.processes import windows_hidden_process_kwargs

pytestmark = pytest.mark.unit


def test_windows_hidden_process_kwargs_are_noop_off_windows() -> None:
    with patch("brain_sync.util.processes.os.name", "posix"):
        assert windows_hidden_process_kwargs() == {}


def test_windows_hidden_process_kwargs_set_hidden_console_flags() -> None:
    fake_subprocess = SimpleNamespace(
        CREATE_NO_WINDOW=0x08000000,
        STARTF_USESHOWWINDOW=0x00000001,
        SW_HIDE=0,
        STARTUPINFO=lambda: SimpleNamespace(dwFlags=0, wShowWindow=1),
    )

    with (
        patch("brain_sync.util.processes.os.name", "nt"),
        patch("brain_sync.util.processes.subprocess", fake_subprocess),
    ):
        kwargs = windows_hidden_process_kwargs(creationflags=0x00000200)

    assert kwargs["creationflags"] == 0x08000200
    assert kwargs["startupinfo"].dwFlags == 0x00000001
    assert kwargs["startupinfo"].wShowWindow == 0

"""Process-launch helpers with platform-safe window behavior."""

from __future__ import annotations

import os
import subprocess
from typing import Any


def windows_hidden_process_kwargs(*, creationflags: int = 0) -> dict[str, Any]:
    """Return kwargs that keep console subprocesses headless on Windows.

    On macOS and other non-Windows platforms this intentionally returns an
    empty mapping so callers preserve their normal subprocess behavior.
    """

    if os.name != "nt":
        return {}

    kwargs: dict[str, Any] = {}
    creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if creationflags:
        kwargs["creationflags"] = creationflags

    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    startf_use_showwindow = getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
    sw_hide = getattr(subprocess, "SW_HIDE", 0)
    if startupinfo_factory is not None and startf_use_showwindow:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= startf_use_showwindow
        startupinfo.wShowWindow = sw_hide
        kwargs["startupinfo"] = startupinfo

    return kwargs


__all__ = ["windows_hidden_process_kwargs"]

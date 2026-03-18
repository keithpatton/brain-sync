from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from brain_sync.util import logging as logging_utils

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    yield
    root = logging.getLogger()
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)


def test_setup_logging_writes_to_primary_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log_dir = tmp_path / "logs"
    log_file = log_dir / "brain-sync.log"

    monkeypatch.setattr(logging_utils, "LOG_DIR", log_dir)
    monkeypatch.setattr(logging_utils, "LOG_FILE", log_file)
    monkeypatch.setattr(
        logging_utils,
        "uuid4",
        lambda: SimpleNamespace(hex="abc123deadbeef"),
    )

    logging_utils.setup_logging("INFO")
    logging.getLogger("test").info("hello from test")

    assert log_file.exists()
    contents = log_file.read_text(encoding="utf-8")
    assert "Logging initialised, run_id=abc123" in contents
    assert "INFO abc123 test hello from test" in contents


def test_setup_logging_falls_back_when_rollover_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    log_dir = tmp_path / "logs"
    log_file = log_dir / "brain-sync.log"

    monkeypatch.setattr(logging_utils, "LOG_DIR", log_dir)
    monkeypatch.setattr(logging_utils, "LOG_FILE", log_file)
    monkeypatch.setattr(
        logging_utils,
        "uuid4",
        lambda: SimpleNamespace(hex="abc123deadbeef"),
    )

    logging_utils.setup_logging("INFO")
    root = logging.getLogger()
    file_handler = next(
        handler for handler in root.handlers if isinstance(handler, logging_utils.ResilientRotatingFileHandler)
    )

    monkeypatch.setattr(file_handler, "shouldRollover", lambda record: True)

    def _raise_permission_error() -> None:
        raise PermissionError("used by another process")

    monkeypatch.setattr(file_handler, "doRollover", _raise_permission_error)

    logging.getLogger("test").info("written after fallback")

    fallback_log = log_dir / f"brain-sync-{logging_utils.os.getpid()}-abc123.log"

    assert fallback_log.exists()
    contents = fallback_log.read_text(encoding="utf-8")
    assert "written after fallback" in contents
    assert "shared log rotation was blocked" in capsys.readouterr().err

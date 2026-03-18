from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from uuid import uuid4

LOG_DIR = Path(os.environ.get("BRAIN_SYNC_CONFIG_DIR", Path.home() / ".brain-sync")) / "logs"
LOG_FILE = LOG_DIR / "brain-sync.log"
MAX_BYTES = 10 * 1024 * 1024
BACKUP_COUNT = 5

_run_id: str = ""


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id  # type: ignore[attr-defined]
        return True


class ResilientRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """Rotate normally, but fall back to a per-run log file if rollover is blocked.

    On Windows, renaming an open file fails when another process still holds the
    shared log file open. That can happen when multiple brain-sync processes
    write to the same rotating log. Rather than surfacing a logging traceback
    and dropping the record, switch the current process to its own log file.
    """

    def __init__(
        self,
        filename: str | Path,
        mode: str = "a",
        maxBytes: int = 0,
        backupCount: int = 0,
        encoding: str | None = None,
        delay: bool = False,
        errors: str | None = None,
    ) -> None:
        super().__init__(
            filename,
            mode=mode,
            maxBytes=maxBytes,
            backupCount=backupCount,
            encoding=encoding,
            delay=delay,
            errors=errors,
        )
        self._using_fallback_file = False
        self._rollover_warning_emitted = False

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if self.shouldRollover(record):
                try:
                    self.doRollover()
                except PermissionError:
                    self._switch_to_fallback_file()
            logging.FileHandler.emit(self, record)
        except Exception:
            self.handleError(record)

    def _switch_to_fallback_file(self) -> None:
        if self._using_fallback_file:
            return

        fallback_path = LOG_DIR / f"brain-sync-{os.getpid()}-{_run_id}.log"
        fallback_path.parent.mkdir(parents=True, exist_ok=True)
        if self.stream:
            self.stream.close()
        self.baseFilename = os.fspath(fallback_path.resolve())
        self.stream = self._open()
        self._using_fallback_file = True

        if not self._rollover_warning_emitted:
            sys.stderr.write(
                f"brain-sync: shared log rotation was blocked; continuing this run in {fallback_path.name}\n"
            )
            sys.stderr.flush()
            self._rollover_warning_emitted = True


def setup_logging(level: str = "INFO") -> None:
    global _run_id
    _run_id = uuid4().hex[:6]

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))
    root.handlers.clear()

    run_id_filter = RunIdFilter()

    file_handler = ResilientRotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s %(run_id)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    file_handler.addFilter(run_id_filter)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    console_handler.addFilter(run_id_filter)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    logging.getLogger(__name__).info("Logging initialised, run_id=%s", _run_id)


__all__ = [
    "BACKUP_COUNT",
    "LOG_DIR",
    "LOG_FILE",
    "MAX_BYTES",
    "RunIdFilter",
    "setup_logging",
]

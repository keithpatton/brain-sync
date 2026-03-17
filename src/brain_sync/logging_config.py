from __future__ import annotations

import logging
import logging.handlers
import sys
from uuid import uuid4

from brain_sync.runtime.config import CONFIG_DIR

LOG_DIR = CONFIG_DIR / "logs"
LOG_FILE = LOG_DIR / "brain-sync.log"
MAX_BYTES = 10 * 1024 * 1024  # 10 MB
BACKUP_COUNT = 5

_run_id: str = ""


class RunIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id  # type: ignore[attr-defined]
        return True


def setup_logging(level: str = "INFO") -> None:
    global _run_id
    _run_id = uuid4().hex[:6]

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level, logging.INFO))

    # Clear any existing handlers (e.g. from basicConfig)
    root.handlers.clear()

    run_id_filter = RunIdFilter()

    # File handler — rotating, structured format
    file_handler = logging.handlers.RotatingFileHandler(
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

    # Console handler — human-readable
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

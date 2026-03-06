from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    root: Path
    log_level: str


def parse_args(argv: list[str] | None = None) -> Config:
    parser = argparse.ArgumentParser(
        prog="brain-sync",
        description="Sync external documents into local folders via sync-manifest.yaml",
    )
    parser.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Target root folder to scan for sync-manifest.yaml files",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )
    args = parser.parse_args(argv)

    root = args.root.resolve()
    if not root.is_dir():
        print(f"Error: --root '{root}' is not a directory", file=sys.stderr)
        sys.exit(1)

    return Config(root=root, log_level=args.log_level)

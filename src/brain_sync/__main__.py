from __future__ import annotations

import sys

from brain_sync.logging_config import setup_logging


def main() -> None:
    from brain_sync.cli import build_parser
    from brain_sync.cli.handlers import (
        handle_add,
        handle_add_file,
        handle_config,
        handle_convert,
        handle_doctor,
        handle_init,
        handle_list,
        handle_migrate,
        handle_move,
        handle_reconcile,
        handle_regen,
        handle_remove,
        handle_remove_file,
        handle_run,
        handle_status,
        handle_update,
        handle_update_skill,
    )
    from brain_sync.runtime.config import load_config

    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    log_level = args.log_level
    if log_level is None:
        log_level = load_config().get("log_level")
    setup_logging(log_level or "INFO")

    handlers = {
        "init": handle_init,
        "run": handle_run,
        "add": handle_add,
        "add-file": handle_add_file,
        "remove": handle_remove,
        "remove-file": handle_remove_file,
        "list": handle_list,
        "move": handle_move,
        "update": handle_update,
        "reconcile": handle_reconcile,
        "status": handle_status,
        "regen": handle_regen,
        "migrate": handle_migrate,
        "config": handle_config,
        "convert": handle_convert,
        "update-skill": handle_update_skill,
        "doctor": handle_doctor,
    }

    handler = handlers.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

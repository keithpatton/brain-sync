from __future__ import annotations

import sys
from pathlib import Path

from brain_sync.util.logging import setup_logging


def main() -> None:
    from brain_sync.interfaces.cli import build_parser
    from brain_sync.interfaces.cli.handlers import (
        handle_add,
        handle_add_file,
        handle_attach_root,
        handle_config,
        handle_convert,
        handle_doctor,
        handle_finalize_missing,
        handle_init,
        handle_list,
        handle_migrate,
        handle_move,
        handle_reconcile,
        handle_regen,
        handle_remove,
        handle_remove_file,
        handle_restart,
        handle_run,
        handle_start,
        handle_status,
        handle_stop,
        handle_sync,
        handle_tree,
        handle_update,
        handle_update_skill,
    )
    from brain_sync.runtime.config import load_config
    from brain_sync.runtime.paths import UnsafeMachineLocalRuntimeError, ensure_safe_temp_root_runtime

    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    explicit_root = getattr(args, "root", None)
    if explicit_root is not None:
        try:
            ensure_safe_temp_root_runtime(Path(explicit_root), operation=args.command)
        except UnsafeMachineLocalRuntimeError as exc:
            print(f"brain-sync: {exc}", file=sys.stderr)
            sys.exit(1)

    log_level = args.log_level
    if log_level is None:
        log_level = load_config().get("log_level")
    setup_logging(log_level or "INFO")

    handlers = {
        "init": handle_init,
        "run": handle_run,
        "attach-root": handle_attach_root,
        "start": handle_start,
        "stop": handle_stop,
        "restart": handle_restart,
        "add": handle_add,
        "add-file": handle_add_file,
        "remove": handle_remove,
        "remove-file": handle_remove_file,
        "list": handle_list,
        "move": handle_move,
        "update": handle_update,
        "sync": handle_sync,
        "reconcile": handle_reconcile,
        "finalize-missing": handle_finalize_missing,
        "status": handle_status,
        "tree": handle_tree,
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

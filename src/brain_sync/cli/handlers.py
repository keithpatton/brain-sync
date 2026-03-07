"""CLI command handlers — thin print wrappers around commands/ API."""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from brain_sync.commands.context import BrainNotFoundError

log = logging.getLogger(__name__)


def _get_root(args) -> Path | None:
    """Extract root from args, returning None if not provided."""
    root = getattr(args, "root", None)
    if root is not None:
        return root.resolve()
    return None


def handle_init(args) -> None:
    from brain_sync.commands.init import init_brain

    result = init_brain(args.root, dry_run=args.dry_run)

    prefix = "[dry-run] " if args.dry_run else ""
    print(f"{prefix}Initialising brain at: {result.root}")
    if result.was_existing:
        print("  Existing directory detected, will add missing structure")
    print(f"{prefix}Brain initialised successfully")
    print("  knowledge/       - Add your content here")
    print("  knowledge/_core/ - Always-loaded reference material")
    print("  insights/        - Auto-generated summaries and journal")

    from brain_sync.commands.init import SKILL_INSTALL_DIR
    print(f"  Skill installed to {SKILL_INSTALL_DIR}")


def handle_run(args) -> None:
    root = _get_root(args)
    if root is None:
        try:
            from brain_sync.commands.context import resolve_root
            root = resolve_root()
        except BrainNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    if not root.is_dir():
        print(f"Error: --root '{root}' is not a directory", file=sys.stderr)
        sys.exit(1)

    from brain_sync.__main__ import run

    loop = asyncio.new_event_loop()

    def _shutdown(sig: int, frame: object) -> None:
        log.info("Received signal %s, shutting down...", sig)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, _shutdown)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(run(root))
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        loop.close()


def handle_add(args) -> None:
    from brain_sync.commands.sources import SourceAlreadyExistsError, add_source
    from brain_sync.sources import UnsupportedSourceError

    try:
        result = add_source(
            root=_get_root(args),
            url=args.url,
            target_path=args.target_path,
            include_links=args.include_links,
            include_children=args.include_children,
            include_attachments=args.include_attachments,
        )
    except UnsupportedSourceError as e:
        print(f"Error: {e}")
        return
    except SourceAlreadyExistsError as e:
        print(f"Source already registered: {e.canonical_id}")
        print(f"  URL: {e.source_url}")
        print(f"  Path: {e.target_path}")
        return
    except BrainNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Registered source: {result.canonical_id}")
    print(f"  URL: {result.source_url}")
    print(f"  Path: knowledge/{result.target_path}")
    print(f"  Links: {result.include_links}, Children: {result.include_children}, Attachments: {result.include_attachments}")
    print("  Will sync on next `brain-sync run`")


def handle_remove(args) -> None:
    from brain_sync.commands.sources import SourceNotFoundError, remove_source

    try:
        result = remove_source(
            root=_get_root(args),
            source=args.source,
            delete_files=args.delete_files,
        )
    except SourceNotFoundError as e:
        print(f"Source not found: {e.source}")
        return
    except BrainNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Removing source: {result.canonical_id}")
    print(f"  URL: {result.source_url}")
    print(f"  Path: knowledge/{result.target_path}")
    if result.files_deleted:
        print(f"  Deleted: {args.root.resolve() / 'knowledge' / result.target_path}")
    print("Source removed")


def handle_list(args) -> None:
    from brain_sync.commands.sources import list_sources

    try:
        sources = list_sources(
            root=_get_root(args),
            filter_path=args.filter_path,
        )
    except BrainNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if not sources:
        print("No sources registered. Use `brain-sync add` to register a source.")
        return

    for s in sources:
        print(f"{s.canonical_id}")
        print(f"  URL:  {s.source_url}")
        print(f"  Path: knowledge/{s.target_path}")
        if args.status:
            print(f"  Last checked: {s.last_checked_utc or 'never'}")
            print(f"  Last changed: {s.last_changed_utc or 'never'}")
            print(f"  Interval: {s.current_interval_secs}s")
            flags = []
            if s.include_links:
                flags.append("links")
            if s.include_children:
                flags.append("children")
            if s.include_attachments:
                flags.append("attachments")
            if flags:
                print(f"  Context: {', '.join(flags)}")
        print()


def handle_move(args) -> None:
    from brain_sync.commands.sources import SourceNotFoundError, move_source

    try:
        result = move_source(
            root=_get_root(args),
            source=args.source,
            to_path=args.to_path,
        )
    except SourceNotFoundError as e:
        print(f"Source not found: {e.source}")
        return
    except BrainNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if result.files_moved:
        print(f"Moved files: knowledge/{result.old_path} -> knowledge/{result.new_path}")
    print(f"Source {result.canonical_id} moved to knowledge/{result.new_path}")


def handle_status(args) -> None:
    print("Status not yet implemented")


def handle_regen(args) -> None:
    root = _get_root(args)
    if root is None:
        try:
            from brain_sync.commands.context import resolve_root
            root = resolve_root()
        except BrainNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    knowledge_path = args.knowledge_path or ""

    if knowledge_path:
        from brain_sync.regen import regen_path

        knowledge_dir = root / "knowledge" / knowledge_path
        if not knowledge_dir.is_dir():
            print(f"Error: knowledge path '{knowledge_path}' does not exist", file=sys.stderr)
            sys.exit(1)

        print(f"Regenerating insights for: {knowledge_path}")
        loop = asyncio.new_event_loop()
        try:
            count = loop.run_until_complete(regen_path(root, knowledge_path))
            print(f"Done. {count} insight file{'s' if count != 1 else ''} regenerated.")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            loop.close()
    else:
        from brain_sync.regen import regen_all

        print("Regenerating insights for all knowledge paths...")
        loop = asyncio.new_event_loop()
        try:
            count = loop.run_until_complete(regen_all(root))
            print(f"Done. {count} insight file{'s' if count != 1 else ''} regenerated.")
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        finally:
            loop.close()


def handle_update_skill(args) -> None:
    from brain_sync.commands.init import update_skill

    updated = update_skill()
    print(f"Skill updated ({', '.join(p.name for p in updated)})")

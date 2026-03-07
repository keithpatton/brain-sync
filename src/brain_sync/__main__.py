from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from brain_sync.config import Config
from brain_sync.logging_config import setup_logging
from brain_sync.pipeline import process_source
from brain_sync.regen_queue import RegenQueue
from brain_sync.scheduler import MAX_ERROR_BACKOFF, Scheduler, compute_interval
from brain_sync.sources import SourceType, UnsupportedSourceError, detect_source_type
from brain_sync.state import (
    SourceState,
    SyncState,
    load_state,
    save_state,
)
from brain_sync.watcher import KnowledgeWatcher, mirror_folder_move

log = logging.getLogger(__name__)

RESCAN_INTERVAL = 300  # 5 minutes
TICK_MAX_SLEEP = 10    # max seconds between ticks


def _ensure_source_states(
    state: SyncState,
    scheduler: Scheduler,
) -> None:
    """Ensure every source in state is scheduled."""
    for cid, ss in state.sources.items():
        if cid not in scheduler._scheduled_keys:
            if ss.next_check_utc and ss.interval_seconds:
                scheduler.schedule_from_persisted(
                    cid, ss.next_check_utc, ss.interval_seconds,
                )
            else:
                scheduler.schedule_immediate(cid)


def _knowledge_rel_path(root: Path, folder: Path) -> str:
    """Convert an absolute knowledge folder path to a root-relative knowledge path."""
    knowledge_root = root / "knowledge"
    try:
        rel = folder.relative_to(knowledge_root)
        return str(rel).replace("\\", "/")
    except ValueError:
        return ""


async def run(root: Path) -> None:
    log.info("brain-sync starting, root: %s", root)

    state = load_state(root)
    scheduler = Scheduler()
    watcher = KnowledgeWatcher(root)
    regen_queue = RegenQueue(root=root)

    _ensure_source_states(state, scheduler)
    save_state(root, state)

    watcher.start()

    last_rescan = time.monotonic()

    async with httpx.AsyncClient() as http_client:
        try:
            while True:
                # 1a. Handle folder moves (mirror to insights/)
                for move in watcher.drain_moves():
                    mirror_folder_move(root, move)

                # 1b. Handle watcher events (knowledge/ changes)
                changed_paths = watcher.drain_events()
                if changed_paths:
                    for folder in changed_paths:
                        rel = _knowledge_rel_path(root, folder)
                        log.info("Knowledge change detected: %s", rel or "(root)")
                        regen_queue.enqueue(rel)

                # 2. Periodic state reload (pick up sources added via CLI)
                now = time.monotonic()
                if now - last_rescan >= RESCAN_INTERVAL:
                    state = load_state(root)
                    _ensure_source_states(state, scheduler)
                    save_state(root, state)
                    last_rescan = now

                # 3. Process due sources
                due_keys = scheduler.pop_due()
                for key in due_keys:
                    if key not in state.sources:
                        scheduler.remove(key)
                        continue

                    ss = state.sources[key]

                    try:
                        changed = await process_source(
                            ss, http_client, root=root
                        )
                        interval = compute_interval(ss.last_changed_utc)
                        ss.current_interval_secs = interval
                        # Enqueue regen if content changed
                        if changed and ss.target_path:
                            regen_queue.enqueue(ss.target_path)
                    except Exception as e:
                        log.warning("Error processing %s: %s", key, e)
                        ss.current_interval_secs = min(
                            ss.current_interval_secs * 2,
                            MAX_ERROR_BACKOFF,
                        )
                        interval = ss.current_interval_secs

                    scheduler.reschedule(key, interval)
                    ss.interval_seconds = interval
                    ss.next_check_utc = datetime.now(timezone.utc).isoformat()
                    save_state(root, state)

                # 4. Process regen events
                await regen_queue.process_ready()

                # 5. Sleep until next event
                next_due = scheduler.next_due_in()
                next_regen = regen_queue.next_fire_in()
                candidates = [TICK_MAX_SLEEP]
                if next_due is not None:
                    candidates.append(next_due)
                if next_regen is not None:
                    candidates.append(next_regen)
                sleep_for = min(candidates)
                await asyncio.sleep(max(0.1, sleep_for))

        finally:
            watcher.stop()
            save_state(root, state)
            log.info("brain-sync stopped")


def main() -> None:
    from brain_sync.cli import build_parser

    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    setup_logging(args.log_level)

    if args.command == "init":
        from brain_sync.cli.init import run_init
        run_init(args.root, dry_run=args.dry_run)

    elif args.command == "run":
        root = args.root.resolve()
        if not root.is_dir():
            print(f"Error: --root '{root}' is not a directory", file=sys.stderr)
            sys.exit(1)

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

    elif args.command == "add":
        from brain_sync.cli.sources import run_add
        run_add(
            args.root.resolve(), args.url, args.target_path,
            include_links=args.include_links,
            include_children=args.include_children,
            include_attachments=args.include_attachments,
        )

    elif args.command == "remove":
        from brain_sync.cli.sources import run_remove
        run_remove(args.root.resolve(), args.source, delete_files=args.delete_files)

    elif args.command == "list":
        from brain_sync.cli.sources import run_list
        run_list(args.root.resolve(), filter_path=args.filter_path, show_status=args.status)

    elif args.command == "move":
        from brain_sync.cli.sources import run_move
        run_move(args.root.resolve(), args.source, args.to_path)

    elif args.command == "status":
        print("Status not yet implemented")

    elif args.command == "regen":
        root = args.root.resolve()
        knowledge_path = args.knowledge_path or ""

        if knowledge_path:
            from brain_sync.regen import regen_path as _regen_path

            knowledge_dir = root / "knowledge" / knowledge_path
            if not knowledge_dir.is_dir():
                print(f"Error: knowledge path '{knowledge_path}' does not exist", file=sys.stderr)
                sys.exit(1)

            print(f"Regenerating insights for: {knowledge_path}")
            loop = asyncio.new_event_loop()
            try:
                count = loop.run_until_complete(_regen_path(root, knowledge_path))
                print(f"Done. {count} summary/summaries regenerated.")
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
            finally:
                loop.close()
        else:
            from brain_sync.regen import regen_all as _regen_all

            print("Regenerating insights for all knowledge paths...")
            loop = asyncio.new_event_loop()
            try:
                count = loop.run_until_complete(_regen_all(root))
                print(f"Done. {count} summary/summaries regenerated.")
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
            finally:
                loop.close()

    elif args.command == "update-skill":
        from brain_sync.cli.init import _copy_template, SKILL_INSTALL_DIR
        _copy_template("SKILL.md", SKILL_INSTALL_DIR / "SKILL.md")
        _copy_template("INSTRUCTIONS.md", SKILL_INSTALL_DIR / "INSTRUCTIONS.md")
        print("Skill updated (SKILL.md + INSTRUCTIONS.md)")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

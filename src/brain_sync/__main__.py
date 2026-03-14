from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

from brain_sync.fs_utils import normalize_path
from brain_sync.logging_config import setup_logging
from brain_sync.pipeline import process_source
from brain_sync.regen import classify_folder_change
from brain_sync.regen_queue import RegenQueue
from brain_sync.scheduler import MAX_ERROR_BACKOFF, Scheduler, compute_interval
from brain_sync.state import (
    SyncState,
    load_insight_state,
    load_state,
    save_insight_state,
    save_sync_progress,
    write_daemon_status,
)
from brain_sync.watcher import KnowledgeWatcher, mirror_folder_move

log = logging.getLogger(__name__)

RESCAN_INTERVAL = 300  # 5 minutes
TICK_MAX_SLEEP = 10.0  # max seconds between ticks


def _ensure_source_states(
    state: SyncState,
    scheduler: Scheduler,
) -> None:
    """Ensure every source in state is scheduled."""
    for cid, ss in state.sources.items():
        if cid not in scheduler._scheduled_keys:
            if ss.next_check_utc and ss.interval_seconds:
                scheduler.schedule_from_persisted(
                    cid,
                    ss.next_check_utc,
                    ss.interval_seconds,
                )
            else:
                scheduler.schedule_immediate(cid)


def _knowledge_rel_path(root: Path, folder: Path) -> str:
    """Convert an absolute knowledge folder path to a root-relative knowledge path."""
    knowledge_root = root / "knowledge"
    try:
        rel = folder.relative_to(knowledge_root)
        return normalize_path(rel)
    except ValueError:
        return ""


async def run(root: Path) -> None:
    log.info("brain-sync starting, root: %s", root)

    from brain_sync.commands.sources import reconcile_sources
    from brain_sync.reconcile import reconcile_knowledge_tree
    from brain_sync.regen_lifecycle import regen_session

    # Reconcile target_paths with filesystem before loading state for sync.
    # This handles files moved while the daemon was not running.
    # INVARIANT: reconcile must run before _ensure_source_states() because
    # reconcile mutates sources.target_path in the DB and load_state() must
    # read the corrected values.
    pid = os.getpid()

    reconcile_result = reconcile_sources(root)
    tree_result = reconcile_knowledge_tree(root)
    write_daemon_status(root, pid, "starting")

    if reconcile_result.updated:
        for entry in reconcile_result.updated:
            log.info(
                "Reconciled %s: knowledge/%s -> knowledge/%s",
                entry.canonical_id,
                entry.old_path,
                entry.new_path,
            )

    # Prune old telemetry rows on startup
    from brain_sync.token_tracking import load_retention_days, prune_token_events

    prune_token_events(root, load_retention_days())

    state = load_state(root)
    scheduler = Scheduler()
    watcher = KnowledgeWatcher(root)

    _ensure_source_states(state, scheduler)
    save_sync_progress(root, state)

    last_rescan = time.monotonic()

    async with regen_session(root, reclaim_stale=True) as session:
        regen_queue = RegenQueue(root=root, owner_id=session.owner_id, session_id=session.session_id)

        # Enqueue regen for paths updated by reconcile so insights rebuild
        # automatically after offline moves.
        if reconcile_result.updated:
            for entry in reconcile_result.updated:
                regen_queue.enqueue(entry.new_path)
                # Invalidate global context cache if _core/ involved
                for path in (entry.old_path, entry.new_path):
                    if path == "_core" or path.startswith("_core/"):
                        from brain_sync.regen import invalidate_global_context_cache

                        invalidate_global_context_cache()
                        break

        # Enqueue tree reconcile paths for regen (offline structural changes)
        for path in tree_result.content_changed:
            regen_queue.enqueue(path)
        for path in tree_result.enqueued_paths:
            regen_queue.enqueue(path)

        # Start watcher after reconcile + enqueue to avoid spurious events
        watcher.start()
        write_daemon_status(root, pid, "ready")

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
                            change, _, new_structure_hash = classify_folder_change(root, rel)
                            if change.change_type == "none":
                                log.debug("Watcher event for %s ignored (content hash unchanged)", rel or "(root)")
                                continue
                            if change.structural:
                                # Rename only — persist updated structure_hash, no regen
                                log.info(
                                    "Watcher event for %s: structure-only change (rename), skipping regen",
                                    rel or "(root)",
                                )
                                istate = load_insight_state(root, rel)
                                if istate:
                                    istate.structure_hash = new_structure_hash
                                    save_insight_state(root, istate)
                                continue
                            log.info("Knowledge change detected: %s", rel or "(root)")
                            regen_queue.enqueue(rel)

                    # 2. Periodic state reload (pick up sources added via CLI)
                    now = time.monotonic()
                    if now - last_rescan >= RESCAN_INTERVAL:
                        state = load_state(root)
                        _ensure_source_states(state, scheduler)
                        save_sync_progress(root, state)
                        last_rescan = now

                    # 3. Process due sources
                    due_keys = scheduler.pop_due()
                    for key in due_keys:
                        if key not in state.sources:
                            scheduler.remove(key)
                            continue

                        ss = state.sources[key]

                        try:
                            changed, discovered_children = await process_source(ss, http_client, root=root)
                            interval = compute_interval(ss.last_changed_utc)
                            ss.current_interval_secs = interval
                            # Enqueue regen if content changed
                            if changed and ss.target_path:
                                regen_queue.enqueue(ss.target_path)
                                # Invalidate global context cache if source targets _core/
                                if ss.target_path == "_core" or ss.target_path.startswith("_core/"):
                                    from brain_sync.regen import invalidate_global_context_cache

                                    invalidate_global_context_cache()

                            # Process discovered children (one-shot pattern)
                            if discovered_children:
                                from brain_sync.commands.sources import SourceAlreadyExistsError, add_source
                                from brain_sync.sources import slugify
                                from brain_sync.state import clear_children_flag

                                parent_target = ss.target_path

                                # Compute child target path
                                if ss.child_path == ".":
                                    child_target_base = parent_target
                                elif ss.child_path:
                                    child_target_base = (
                                        f"{parent_target}/{ss.child_path}" if parent_target else ss.child_path
                                    )
                                else:
                                    # Default: {parent_target}/{parent_canonical_slug}/
                                    parent_id = key.split(":", 1)[1]
                                    slug = slugify(ss.source_url.rstrip("/").split("/")[-1] or parent_id)
                                    suffix = f"c{parent_id}-{slug}"
                                    child_target_base = f"{parent_target}/{suffix}" if parent_target else suffix

                                for child in discovered_children:
                                    try:
                                        child_result = add_source(
                                            root=root,
                                            url=child.url,
                                            target_path=child_target_base,
                                            sync_attachments=ss.sync_attachments,
                                        )
                                        # Update in-memory state and schedule immediate sync
                                        child_ss = load_state(root).sources.get(child_result.canonical_id)
                                        if child_ss:
                                            state.sources[child_result.canonical_id] = child_ss
                                        scheduler.schedule_immediate(child_result.canonical_id)
                                        log.info(
                                            "Added child source %s → knowledge/%s",
                                            child_result.canonical_id,
                                            child_result.target_path,
                                        )
                                    except SourceAlreadyExistsError:
                                        log.debug("Child %s already registered, skipping", child.canonical_id)
                                    except Exception as child_err:
                                        log.warning("Failed to add child %s: %s", child.canonical_id, child_err)

                                # Clear the one-shot flag AFTER all children processed
                                clear_children_flag(root, key)
                                ss.fetch_children = False
                                ss.child_path = None
                        except Exception as e:
                            log.warning("Error processing %s: %s", key, e)
                            ss.current_interval_secs = min(
                                ss.current_interval_secs * 2,
                                MAX_ERROR_BACKOFF,
                            )
                            interval = ss.current_interval_secs

                        scheduler.reschedule(key, interval)
                        ss.interval_seconds = interval
                        ss.next_check_utc = datetime.now(UTC).isoformat()
                        try:
                            save_sync_progress(root, state)
                        except Exception:
                            log.warning("Failed to save state (will retry next tick)", exc_info=True)

                    # 4. Process regen events
                    try:
                        await regen_queue.process_ready()
                    except Exception:
                        log.exception("Unexpected error in regen queue processing")

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
                try:
                    write_daemon_status(root, pid, "stopped")
                except Exception:
                    log.warning("Failed to write daemon stopped status", exc_info=True)
                try:
                    save_sync_progress(root, state)
                except Exception:
                    log.error("Failed to save state on shutdown", exc_info=True)
                log.info("brain-sync stopped")


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

    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Resolve log level: CLI arg > config.json > default "INFO"
    log_level = args.log_level
    if log_level is None:
        from brain_sync.config import load_config

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

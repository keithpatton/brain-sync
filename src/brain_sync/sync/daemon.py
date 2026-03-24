from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

import httpx

from brain_sync.brain.tree import normalize_path
from brain_sync.regen.lifecycle import regen_session
from brain_sync.regen.queue import RegenQueue
from brain_sync.runtime.operational_events import load_retention_days as load_operational_event_retention_days
from brain_sync.runtime.paths import ensure_safe_temp_root_runtime
from brain_sync.runtime.repository import (
    DaemonAlreadyRunningError,
    acquire_daemon_start_guard,
    ensure_lifecycle_session,
    load_child_discovery_request,
    prune_operational_events,
    prune_token_events,
    release_daemon_start_guard,
    write_daemon_status,
)
from brain_sync.runtime.token_tracking import load_retention_days
from brain_sync.sources.base import RemoteSourceMissingError
from brain_sync.sync.lifecycle import (
    apply_folder_move,
    enqueue_regen_path,
    handle_watcher_folder_change,
    observe_missing_source,
    process_discovered_children,
    reconcile_sources,
)
from brain_sync.sync.pipeline import SourceLifecycleLeaseConflictError, process_source
from brain_sync.sync.reconcile import reconcile_knowledge_tree
from brain_sync.sync.scheduler import (
    MAX_ERROR_BACKOFF,
    Scheduler,
    compute_interval,
    compute_next_check_utc,
)
from brain_sync.sync.source_state import (
    SyncState,
    load_active_sync_state,
    save_active_sync_state,
)
from brain_sync.sync.watcher import KnowledgeWatcher

log = logging.getLogger(__name__)

__all__ = ["DaemonAlreadyRunningError", "run"]

RESCAN_INTERVAL = 300  # 5 minutes
TICK_MAX_SLEEP = 10.0  # max seconds between ticks
LEASE_CONFLICT_RETRY_SECS = 5


def _source_lease_owner_id() -> str:
    return f"daemon-sync:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _sync_scheduler_state(
    state: SyncState,
    scheduler: Scheduler,
) -> None:
    """Make the in-memory scheduler match the active source projection."""
    active_keys = set(state.sources)
    for stale_key in set(scheduler._scheduled_keys) - active_keys:
        scheduler.remove(stale_key)

    for cid, ss in state.sources.items():
        if ss.next_check_utc and ss.interval_seconds:
            if cid not in scheduler._scheduled_keys:
                scheduler.schedule_from_persisted(
                    cid,
                    ss.next_check_utc,
                    ss.interval_seconds,
                )
        else:
            # Sources that just became active again (for example after leaving
            # missing) should be polled promptly rather than inheriting a stale
            # in-memory schedule from a prior lifecycle.
            scheduler.schedule_immediate(cid)


def _knowledge_rel_path(root: Path, folder: Path) -> str:
    """Convert an absolute knowledge folder path to a root-relative knowledge path."""
    knowledge_root = root / "knowledge"
    try:
        rel = folder.relative_to(knowledge_root)
        return normalize_path(rel)
    except ValueError:
        return ""


def _log_reconcile_result(result) -> None:
    for entry in result.updated:
        log.info(
            "Reconciled %s: knowledge/%s -> knowledge/%s",
            entry.canonical_id,
            entry.old_path,
            entry.new_path,
        )
    for canonical_id in result.marked_missing:
        log.info("Marked %s missing after local filesystem reconcile", canonical_id)
    for canonical_id in result.reappeared:
        log.info("Rediscovered missing source %s during reconcile", canonical_id)
    for canonical_id in result.deleted:
        log.info("Deregistered still-missing source %s during reconcile", canonical_id)


async def run(root: Path) -> None:
    ensure_safe_temp_root_runtime(root, operation="run daemon")
    log.info("brain-sync starting, root: %s", root)
    pid = os.getpid()
    guard = acquire_daemon_start_guard(root)
    try:
        write_daemon_status(root=root, pid=pid, status="starting", daemon_id=guard.daemon_id)
        lifecycle_session_id = ensure_lifecycle_session(root, owner_kind="daemon")

        # Reconcile target_paths with filesystem before loading state for sync.
        # This handles files moved while the daemon was not running.
        # INVARIANT: reconcile must run before _sync_scheduler_state() because
        # reconcile repairs manifest-backed placement before the scheduler loads
        # source state for the sync loop.
        reconcile_result = reconcile_sources(root, finalize_missing=False, lifecycle_session_id=lifecycle_session_id)
        tree_result = reconcile_knowledge_tree(root)

        _log_reconcile_result(reconcile_result)

        prune_token_events(retention_days=load_retention_days())
        prune_operational_events(retention_days=load_operational_event_retention_days())

        state = load_active_sync_state(root)
        scheduler = Scheduler()
        watcher = KnowledgeWatcher(root)

        _sync_scheduler_state(state, scheduler)
        save_active_sync_state(root, state)

        last_rescan = time.monotonic()

        async with regen_session(root, reclaim_stale=True) as session:
            regen_queue = RegenQueue(root=root, owner_id=session.owner_id, session_id=session.session_id)

            # Enqueue regen for paths updated by reconcile so insights rebuild
            # automatically after offline moves.
            if reconcile_result.updated:
                for entry in reconcile_result.updated:
                    enqueue_regen_path(
                        root,
                        knowledge_path=entry.new_path,
                        enqueue=regen_queue.enqueue,
                        reason="reconcile",
                    )

            # Enqueue tree reconcile paths for regen (offline structural changes)
            for path in tree_result.content_changed:
                enqueue_regen_path(root, knowledge_path=path, enqueue=regen_queue.enqueue, reason="reconcile")
            for path in tree_result.enqueued_paths:
                enqueue_regen_path(root, knowledge_path=path, enqueue=regen_queue.enqueue, reason="reconcile")

            # Start watcher after reconcile + enqueue to avoid spurious events
            watcher.start()
            write_daemon_status(root=root, pid=pid, status="ready", daemon_id=guard.daemon_id)

            async with httpx.AsyncClient() as http_client:
                try:
                    while True:
                        # 1a. Handle folder moves (co-located managed state moves with the folder)
                        for move in watcher.drain_moves():
                            apply_folder_move(root, move=move, enqueue=regen_queue.enqueue)

                        # 1b. Handle watcher events (knowledge/ changes)
                        changed_paths = watcher.drain_events()
                        if changed_paths:
                            for folder in changed_paths:
                                rel = _knowledge_rel_path(root, folder)
                                outcome = handle_watcher_folder_change(
                                    root,
                                    knowledge_path=rel,
                                    enqueue=regen_queue.enqueue,
                                )
                                if outcome.action == "enqueued":
                                    log.info("Knowledge change detected: %s", rel or "(root)")
                                elif outcome.action == "structure_enqueued":
                                    log.info("Watcher structure-only change enqueued for %s", rel or "(root)")
                                else:
                                    log.debug("Watcher event for %s ignored", rel or "(root)")
                            # Live watcher churn may mark first-stage missing or
                            # repair stale paths, but it must not collapse the
                            # grace period into second-stage deregistration.
                            reconcile_result = reconcile_sources(
                                root,
                                finalize_missing=False,
                                lifecycle_session_id=lifecycle_session_id,
                            )
                            _log_reconcile_result(reconcile_result)
                            if (
                                reconcile_result.updated
                                or reconcile_result.marked_missing
                                or reconcile_result.deleted
                                or reconcile_result.reappeared
                            ):
                                state = load_active_sync_state(root)
                                _sync_scheduler_state(state, scheduler)
                                save_active_sync_state(root, state)

                        # 2. Periodic state reload (pick up sources added via CLI)
                        now = time.monotonic()
                        if now - last_rescan >= RESCAN_INTERVAL:
                            state = load_active_sync_state(root)
                            _sync_scheduler_state(state, scheduler)
                            save_active_sync_state(root, state)
                            last_rescan = now

                        # 3. Process due sources
                        due_keys = scheduler.pop_due()
                        for key in due_keys:
                            if key not in state.sources:
                                scheduler.remove(key)
                                continue

                            ss = state.sources[key]

                            try:
                                child_request = load_child_discovery_request(root, key)
                                changed, discovered_children = await process_source(
                                    ss,
                                    http_client,
                                    root=root,
                                    fetch_children=child_request.fetch_children if child_request is not None else False,
                                    lifecycle_owner_id=_source_lease_owner_id(),
                                )
                                processed_last_checked_utc = ss.last_checked_utc
                                refreshed = load_active_sync_state(root).sources.get(key)
                                if refreshed is not None:
                                    refreshed.last_checked_utc = processed_last_checked_utc
                                    ss = refreshed
                                state.sources[key] = ss
                                interval = compute_interval(ss.last_changed_utc)
                                ss.current_interval_secs = interval
                                # Enqueue regen if content changed
                                if changed and ss.target_path:
                                    enqueue_regen_path(
                                        root,
                                        knowledge_path=ss.target_path,
                                        enqueue=regen_queue.enqueue,
                                        reason="source_changed",
                                        canonical_id=key,
                                    )

                                state = process_discovered_children(
                                    root,
                                    parent_canonical_id=key,
                                    parent_source_url=ss.source_url,
                                    parent_target=ss.target_path,
                                    sync_attachments=ss.sync_attachments,
                                    request=child_request,
                                    discovered_children=discovered_children,
                                    schedule_immediate=scheduler.schedule_immediate,
                                    state=state,
                                )
                            except RemoteSourceMissingError as e:
                                marked = observe_missing_source(
                                    root,
                                    canonical_id=key,
                                    outcome="remote_missing",
                                    lifecycle_session_id=lifecycle_session_id,
                                )
                                scheduler.remove(key)
                                state.sources.pop(key, None)
                                if marked:
                                    log.warning("Marked %s as missing after upstream 404: %s", key, e)
                                else:
                                    log.warning("Upstream 404 for unregistered source %s: %s", key, e)
                                continue
                            except SourceLifecycleLeaseConflictError as e:
                                log.info(
                                    "Skipping %s due to active lifecycle lease held by %s",
                                    key,
                                    e.lease_owner or "unknown",
                                )
                                scheduler.reschedule(key, LEASE_CONFLICT_RETRY_SECS)
                                continue
                            except Exception as e:
                                log.warning("Error processing %s: %s", key, e)
                                ss.current_interval_secs = min(
                                    ss.current_interval_secs * 2,
                                    MAX_ERROR_BACKOFF,
                                )
                                interval = ss.current_interval_secs

                            scheduler.reschedule(key, interval)
                            ss.interval_seconds = interval
                            ss.next_check_utc = compute_next_check_utc(interval)
                            try:
                                save_active_sync_state(root, state)
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
                    try:
                        # Flush any queued folder moves before shutting down. This
                        # keeps runtime state consistent when SIGINT lands while the
                        # main loop is asleep and the filesystem move has already
                        # happened on disk.
                        for move in watcher.drain_moves():
                            apply_folder_move(root, move=move, enqueue=regen_queue.enqueue)
                    except Exception:
                        log.warning("Failed to flush pending watcher moves on shutdown", exc_info=True)

                    watcher.stop()
                    try:
                        for move in watcher.drain_moves():
                            apply_folder_move(root, move=move, enqueue=regen_queue.enqueue)
                    except Exception:
                        log.warning("Failed to flush watcher moves after stop", exc_info=True)
                    try:
                        # Final shutdown reconcile keeps runtime state consistent
                        # even if a filesystem rename landed on disk without the
                        # watcher loop processing the corresponding move event.
                        reconcile_knowledge_tree(root)
                    except Exception:
                        log.warning("Failed shutdown reconcile", exc_info=True)
                    try:
                        write_daemon_status(root=root, pid=pid, status="stopped", daemon_id=guard.daemon_id)
                    except Exception:
                        log.warning("Failed to write daemon stopped status", exc_info=True)
                    try:
                        save_active_sync_state(root, state)
                    except Exception:
                        log.error("Failed to save state on shutdown", exc_info=True)
                    log.info("brain-sync stopped")
    finally:
        try:
            release_daemon_start_guard(guard)
        except Exception:
            log.warning("Failed to release daemon start guard", exc_info=True)

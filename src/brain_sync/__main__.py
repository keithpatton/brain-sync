from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from pathlib import Path

import httpx

from brain_sync.config import parse_args
from brain_sync.logging_config import setup_logging
from brain_sync.manifest import Manifest, ManifestError, discover_manifests, load_manifest
from brain_sync.pipeline import process_source
from brain_sync.scheduler import MAX_ERROR_BACKOFF, Scheduler, compute_interval
from brain_sync.sources import UnsupportedSourceError, detect_source_type
from brain_sync.state import (
    SourceState,
    SyncState,
    load_state,
    prune_state,
    save_state,
    source_key,
)
from brain_sync.watcher import ManifestWatcher

log = logging.getLogger(__name__)

RESCAN_INTERVAL = 300  # 5 minutes
TICK_MAX_SLEEP = 10    # max seconds between ticks


def _build_source_map(
    manifests: dict[Path, Manifest],
) -> dict[str, tuple[Manifest, int]]:
    """Map source_key -> (manifest, source_index)."""
    result: dict[str, tuple[Manifest, int]] = {}
    for manifest in manifests.values():
        for i, entry in enumerate(manifest.sources):
            key = source_key(
                str(manifest.path),
                entry.url,
            )
            result[key] = (manifest, i)
    return result


def _ensure_source_states(
    manifests: dict[Path, Manifest],
    state: SyncState,
    scheduler: Scheduler,
) -> dict[str, tuple[Manifest, int]]:
    """Ensure every source in every manifest has state and is scheduled."""
    source_map = _build_source_map(manifests)

    for key, (manifest, idx) in source_map.items():
        entry = manifest.sources[idx]
        if key not in state.sources:
            try:
                stype = detect_source_type(entry.url)
            except UnsupportedSourceError:
                stype = None
            state.sources[key] = SourceState(
                manifest_path=str(manifest.path),
                source_url=entry.url,
                target_file=entry.file,
                source_type=stype.value if stype else "unknown",
            )
            scheduler.schedule_immediate(key)
        elif key not in scheduler._scheduled_keys:
            interval = compute_interval(state.sources[key].last_changed_utc)
            scheduler.schedule(key, delay_secs=0)

    # Prune state for sources no longer in any manifest
    prune_state(state, set(source_map.keys()))

    return source_map


async def run(root: Path) -> None:
    log.info("brain-sync starting, root: %s", root)

    state = load_state(root)
    scheduler = Scheduler()
    watcher = ManifestWatcher(root)

    # Initial scan
    manifests = discover_manifests(root)
    log.info("Found %d manifest(s) on startup", len(manifests))
    source_map = _ensure_source_states(manifests, state, scheduler)
    save_state(root, state)

    watcher.start()

    last_rescan = time.monotonic()

    async with httpx.AsyncClient() as http_client:
        try:
            while True:
                # 1. Handle watcher events
                changed_paths = watcher.drain_events()
                if changed_paths:
                    for path in changed_paths:
                        if path.exists():
                            try:
                                manifests[path] = load_manifest(path)
                                log.info("Manifest loaded/updated: %s", path)
                            except ManifestError as e:
                                log.warning("Invalid manifest: %s", e)
                                manifests.pop(path, None)
                        else:
                            manifests.pop(path, None)
                            log.info("Manifest removed: %s", path)
                    source_map = _ensure_source_states(manifests, state, scheduler)
                    save_state(root, state)

                # 2. Periodic full rescan
                now = time.monotonic()
                if now - last_rescan >= RESCAN_INTERVAL:
                    manifests = discover_manifests(root)
                    source_map = _ensure_source_states(manifests, state, scheduler)
                    save_state(root, state)
                    last_rescan = now

                # 3. Process due sources
                due_keys = scheduler.pop_due()
                for key in due_keys:
                    if key not in source_map:
                        scheduler.remove(key)
                        continue

                    manifest, idx = source_map[key]
                    entry = manifest.sources[idx]
                    ss = state.sources[key]

                    try:
                        changed = await process_source(
                            manifest, entry, ss, http_client
                        )
                        interval = compute_interval(ss.last_changed_utc)
                        ss.current_interval_secs = interval
                    except Exception as e:
                        log.warning("Error processing %s: %s", key, e)
                        ss.current_interval_secs = min(
                            ss.current_interval_secs * 2,
                            MAX_ERROR_BACKOFF,
                        )
                        interval = ss.current_interval_secs

                    scheduler.reschedule(key, interval)
                    save_state(root, state)

                # 4. Sleep until next event
                next_due = scheduler.next_due_in()
                sleep_for = min(next_due if next_due is not None else TICK_MAX_SLEEP, TICK_MAX_SLEEP)
                await asyncio.sleep(max(0.1, sleep_for))

        finally:
            watcher.stop()
            save_state(root, state)
            log.info("brain-sync stopped")


def main() -> None:
    config = parse_args()
    setup_logging(config.log_level)

    loop = asyncio.new_event_loop()

    def _shutdown(sig: int, frame: object) -> None:
        log.info("Received signal %s, shutting down...", sig)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, _shutdown)
    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(run(config.root))
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()

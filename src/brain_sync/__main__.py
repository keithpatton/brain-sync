from __future__ import annotations

import asyncio
import logging
import shutil
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from brain_sync.config import parse_args
from brain_sync.logging_config import setup_logging
from brain_sync.manifest import Manifest, ManifestError, discover_manifests, load_manifest
from brain_sync.pipeline import process_source
from brain_sync.scheduler import MAX_ERROR_BACKOFF, Scheduler, compute_interval
from brain_sync.sources import UnsupportedSourceError, canonical_id, detect_source_type
from brain_sync.state import (
    OutputBinding,
    SourceState,
    SyncState,
    load_state,
    prune_bindings,
    prune_db,
    prune_state,
    save_bindings,
    save_state,
    source_key_for_entry,
)
from brain_sync.watcher import ManifestWatcher

log = logging.getLogger(__name__)

RESCAN_INTERVAL = 300  # 5 minutes
TICK_MAX_SLEEP = 10    # max seconds between ticks


def _build_source_map(
    manifests: dict[Path, Manifest],
) -> tuple[dict[str, list[tuple[Manifest, int]]], list[OutputBinding]]:
    """Map canonical_id -> list of (manifest, source_index) pairs.

    Returns (source_map, all_bindings).
    """
    source_map: dict[str, list[tuple[Manifest, int]]] = {}
    all_bindings: list[OutputBinding] = []

    for manifest in manifests.values():
        for i, entry in enumerate(manifest.sources):
            try:
                cid = source_key_for_entry(entry.url)
            except UnsupportedSourceError:
                continue
            source_map.setdefault(cid, []).append((manifest, i))
            all_bindings.append(OutputBinding(
                canonical_id=cid,
                manifest_path=str(manifest.path),
                target_file=entry.file,
                include_links=entry.include_links,
                include_children=entry.include_children,
                include_attachments=entry.include_attachments,
                link_depth=entry.link_depth,
            ))

    return source_map, all_bindings


def _ensure_source_states(
    manifests: dict[Path, Manifest],
    state: SyncState,
    scheduler: Scheduler,
    root: Path,
) -> tuple[dict[str, list[tuple[Manifest, int]]], dict[str, list[OutputBinding]]]:
    """Ensure every source in every manifest has state and is scheduled.

    Returns (source_map, bindings_by_cid).
    """
    source_map, all_bindings = _build_source_map(manifests)

    # Build bindings lookup
    bindings_by_cid: dict[str, list[OutputBinding]] = {}
    for b in all_bindings:
        bindings_by_cid.setdefault(b.canonical_id, []).append(b)

    for cid, manifest_entries in source_map.items():
        manifest, idx = manifest_entries[0]
        entry = manifest.sources[idx]

        if cid not in state.sources:
            try:
                stype = detect_source_type(entry.url)
            except UnsupportedSourceError:
                stype = None
            state.sources[cid] = SourceState(
                canonical_id=cid,
                source_url=entry.url,
                source_type=stype.value if stype else "unknown",
            )
            scheduler.schedule_immediate(cid)
        elif cid not in scheduler._scheduled_keys:
            ss = state.sources[cid]
            scheduler.schedule_from_persisted(
                cid, ss.next_check_utc, ss.interval_seconds,
            )

    # Prune state for sources no longer in any manifest
    active_cids = set(source_map.keys())
    prune_state(state, active_cids)
    prune_db(root, active_cids)

    # Persist bindings
    save_bindings(root, all_bindings)
    prune_bindings(root, active_cids)

    return source_map, bindings_by_cid


def _resolve_target_file(entry_file: str, ss: SourceState) -> str:
    """Get the target filename, using the previously resolved auto name if available."""
    if entry_file != "auto":
        return entry_file
    # If we've resolved the auto filename before and it's stored, we don't know it here.
    # The pipeline will resolve it.
    return entry_file


def _project_to_additional_bindings(
    primary_manifest: Manifest,
    primary_target: Path,
    bindings: list[OutputBinding],
    resolved_filename: str,
) -> None:
    """Copy the primary output file and context to additional binding directories."""
    primary_dir = primary_manifest.path.parent
    primary_context = primary_dir / "_sync-context"

    for binding in bindings[1:]:
        binding_dir = Path(binding.manifest_path).parent
        if binding_dir.resolve() == primary_dir.resolve():
            continue

        # Copy primary file
        target = binding_dir / resolved_filename
        target.parent.mkdir(parents=True, exist_ok=True)
        if primary_target.exists():
            shutil.copy2(str(primary_target), str(target))

        # Copy _sync-context subtree if it exists
        if primary_context.exists():
            binding_context = binding_dir / "_sync-context"
            # Selective copy based on binding flags
            for subdir in ["linked", "children", "attachments"]:
                src = primary_context / subdir
                if not src.exists():
                    continue
                # Check if this binding wants this type
                if subdir == "linked" and not binding.include_links:
                    continue
                if subdir == "children" and not binding.include_children:
                    continue
                if subdir == "attachments" and not binding.include_attachments:
                    continue
                dst = binding_context / subdir
                dst.mkdir(parents=True, exist_ok=True)
                for f in src.iterdir():
                    if f.is_file():
                        shutil.copy2(str(f), str(dst / f.name))

            # Copy _index.md
            index_src = primary_context / "_index.md"
            if index_src.exists():
                binding_context.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(index_src), str(binding_context / "_index.md"))

        # Touch dirty marker for this binding
        from brain_sync.fileops import touch_dirty
        if binding.manifest_path:
            # Build a minimal manifest-like path to resolve dirty
            dirty_path = binding_dir / ".dirty"
            touch_dirty(dirty_path)


async def run(root: Path) -> None:
    log.info("brain-sync starting, root: %s", root)

    state = load_state(root)
    scheduler = Scheduler()
    watcher = ManifestWatcher(root)

    # Initial scan
    manifests = discover_manifests(root)
    log.info("Found %d manifest(s) on startup", len(manifests))
    source_map, bindings_by_cid = _ensure_source_states(manifests, state, scheduler, root)
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
                    source_map, bindings_by_cid = _ensure_source_states(
                        manifests, state, scheduler, root,
                    )
                    save_state(root, state)

                # 2. Periodic full rescan
                now = time.monotonic()
                if now - last_rescan >= RESCAN_INTERVAL:
                    manifests = discover_manifests(root)
                    source_map, bindings_by_cid = _ensure_source_states(
                        manifests, state, scheduler, root,
                    )
                    save_state(root, state)
                    last_rescan = now

                # 3. Process due sources
                due_keys = scheduler.pop_due()
                for key in due_keys:
                    if key not in source_map:
                        scheduler.remove(key)
                        continue

                    # Use first binding for fetching
                    manifest, idx = source_map[key][0]
                    entry = manifest.sources[idx]
                    ss = state.sources[key]

                    try:
                        changed = await process_source(
                            manifest, entry, ss, http_client, root=root
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

                    # Project to additional bindings if content changed
                    if changed and key in bindings_by_cid:
                        bindings = bindings_by_cid[key]
                        if len(bindings) > 1:
                            # Determine the resolved filename
                            resolved_filename = entry.file
                            if resolved_filename == "auto":
                                # Try to find the file that was written
                                from brain_sync.sources import canonical_filename, extract_confluence_page_id, SourceType
                                try:
                                    stype = detect_source_type(entry.url)
                                    if stype == SourceType.CONFLUENCE:
                                        page_id = extract_confluence_page_id(entry.url)
                                        # Look for the file in the manifest dir
                                        for f in manifest.path.parent.iterdir():
                                            if f.name.startswith(f"c{page_id}") and f.name.endswith(".md"):
                                                resolved_filename = f.name
                                                break
                                except Exception:
                                    pass

                            if resolved_filename != "auto":
                                primary_target = manifest.path.parent / resolved_filename
                                _project_to_additional_bindings(
                                    manifest, primary_target, bindings, resolved_filename,
                                )

                    scheduler.reschedule(key, interval)
                    ss.interval_seconds = interval
                    ss.next_check_utc = datetime.now(timezone.utc).isoformat()
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

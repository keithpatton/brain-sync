from __future__ import annotations

import logging
from pathlib import Path

from brain_sync.sources import UnsupportedSourceError, canonical_id, detect_source_type
from brain_sync.state import SourceState, load_state, save_state, _connect

log = logging.getLogger(__name__)


def run_add(
    root: Path,
    url: str,
    target_path: str,
    include_links: bool = False,
    include_children: bool = False,
    include_attachments: bool = False,
) -> None:
    """Register a source URL for syncing."""
    root = root.resolve()

    try:
        stype = detect_source_type(url)
        cid = canonical_id(stype, url)
    except UnsupportedSourceError as e:
        print(f"Error: {e}")
        return

    # Check if already registered
    state = load_state(root)
    if cid in state.sources:
        existing = state.sources[cid]
        print(f"Source already registered: {cid}")
        print(f"  URL: {existing.source_url}")
        print(f"  Path: {existing.target_path}")
        return

    # Register
    state.sources[cid] = SourceState(
        canonical_id=cid,
        source_url=url,
        source_type=stype.value,
        target_path=target_path,
        include_links=include_links,
        include_children=include_children,
        include_attachments=include_attachments,
    )
    save_state(root, state)

    # Ensure target directory exists
    knowledge_dir = root / "knowledge" / target_path
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    print(f"Registered source: {cid}")
    print(f"  URL: {url}")
    print(f"  Path: knowledge/{target_path}")
    print(f"  Links: {include_links}, Children: {include_children}, Attachments: {include_attachments}")
    print(f"  Will sync on next `brain-sync run`")


def run_remove(root: Path, source: str, delete_files: bool = False) -> None:
    """Unregister a sync source."""
    root = root.resolve()
    state = load_state(root)

    # Find by canonical ID or URL
    cid = _resolve_source(state, source)
    if cid is None:
        print(f"Source not found: {source}")
        return

    ss = state.sources[cid]
    print(f"Removing source: {cid}")
    print(f"  URL: {ss.source_url}")
    print(f"  Path: knowledge/{ss.target_path}")

    if delete_files:
        target_dir = root / "knowledge" / ss.target_path
        if target_dir.exists():
            import shutil
            shutil.rmtree(str(target_dir))
            print(f"  Deleted: {target_dir}")

    del state.sources[cid]
    save_state(root, state)

    # Also clean from DB
    conn = _connect(root)
    try:
        conn.execute("DELETE FROM sources WHERE canonical_id = ?", (cid,))
        conn.commit()
    finally:
        conn.close()

    print("Source removed")


def run_list(root: Path, filter_path: str | None = None, show_status: bool = False) -> None:
    """List registered sync sources."""
    root = root.resolve()
    state = load_state(root)

    if not state.sources:
        print("No sources registered. Use `brain-sync add` to register a source.")
        return

    for cid, ss in sorted(state.sources.items()):
        target = getattr(ss, "target_path", "")
        if filter_path and not target.startswith(filter_path):
            continue

        print(f"{cid}")
        print(f"  URL:  {ss.source_url}")
        print(f"  Path: knowledge/{target}")
        if show_status:
            print(f"  Last checked: {ss.last_checked_utc or 'never'}")
            print(f"  Last changed: {ss.last_changed_utc or 'never'}")
            print(f"  Interval: {ss.current_interval_secs}s")
            flags = []
            if getattr(ss, "include_links", False):
                flags.append("links")
            if getattr(ss, "include_children", False):
                flags.append("children")
            if getattr(ss, "include_attachments", False):
                flags.append("attachments")
            if flags:
                print(f"  Context: {', '.join(flags)}")
        print()


def run_move(root: Path, source: str, to_path: str) -> None:
    """Move a sync source to a new knowledge path."""
    root = root.resolve()
    state = load_state(root)

    cid = _resolve_source(state, source)
    if cid is None:
        print(f"Source not found: {source}")
        return

    ss = state.sources[cid]
    old_path = getattr(ss, "target_path", "")
    ss.target_path = to_path
    save_state(root, state)

    # Move files on disk if they exist
    old_dir = root / "knowledge" / old_path
    new_dir = root / "knowledge" / to_path
    if old_dir.exists() and old_dir != new_dir:
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        import shutil
        shutil.move(str(old_dir), str(new_dir))
        print(f"Moved files: knowledge/{old_path} -> knowledge/{to_path}")

    print(f"Source {cid} moved to knowledge/{to_path}")


def _resolve_source(state, source: str) -> str | None:
    """Find a source by canonical ID or URL."""
    if source in state.sources:
        return source
    for cid, ss in state.sources.items():
        if ss.source_url == source:
            return cid
    return None

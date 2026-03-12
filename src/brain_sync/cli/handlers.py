"""CLI command handlers — logging-based wrappers around commands/ API."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from pathlib import Path

from brain_sync.commands.context import BrainNotFoundError
from brain_sync.commands.placement import PlacementSelection

log = logging.getLogger(__name__)


def _get_root(args) -> Path | None:
    """Extract root from args, returning None if not provided."""
    root = getattr(args, "root", None)
    if root is not None:
        return root.resolve()
    return None


def handle_init(args) -> None:
    from brain_sync.commands.init import init_brain

    result = init_brain(args.root, model=args.model, dry_run=args.dry_run)

    prefix = "[dry-run] " if args.dry_run else ""
    log.info("%sInitialising brain at: %s", prefix, result.root)
    if result.was_existing:
        log.info("  Existing directory detected, will add missing structure")
    log.info("%sBrain initialised successfully", prefix)
    log.info("  knowledge/       - Add your content here")
    log.info("  knowledge/_core/ - Always-loaded reference material")
    log.info("  insights/        - Auto-generated summaries and journal")

    from brain_sync.commands.init import SKILL_INSTALL_DIR

    log.info("  Skill installed to %s", SKILL_INSTALL_DIR)


def handle_run(args) -> None:
    root = _get_root(args)
    if root is None:
        try:
            from brain_sync.commands.context import resolve_root

            root = resolve_root()
        except BrainNotFoundError:
            log.exception("Cannot resolve brain root")
            sys.exit(1)

    if not root.is_dir():
        log.error("--root '%s' is not a directory", root)
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


def _resolve_root_or_exit(args) -> Path:
    """Resolve brain root from args or config, exiting on failure."""
    root = _get_root(args)
    if root is None:
        try:
            from brain_sync.commands.context import resolve_root

            root = resolve_root()
        except BrainNotFoundError:
            log.exception("Cannot resolve brain root")
            sys.exit(1)
    return root


def _interactive_placement(
    root: Path,
    title: str,
    excerpt: str,
    filename: str,
    source: str | None,
    subtree: str | None,
    dry_run: bool,
) -> PlacementSelection:
    """Show interactive placement suggestions and return user's choice."""
    from brain_sync.area_index import AreaIndex
    from brain_sync.commands.placement import suggest_placement

    index = AreaIndex.build(root)
    result = suggest_placement(
        index,
        document_title=title,
        document_excerpt=excerpt,
        source=source,
        subtree=subtree,
    )

    if not result.candidates:
        log.info("No matching areas found for '%s'.", title)
        log.info("Consider creating a new area in knowledge/.")
        if dry_run:
            return PlacementSelection(path="", cancelled=True)
        choice = input("Enter (c) for custom path, or (n) to cancel: ").strip().lower()
        if choice == "c":
            custom = input("Enter path relative to knowledge/: ").strip()
            if not custom:
                log.info("Cancelled.")
                return PlacementSelection(path="", cancelled=True)
            return PlacementSelection(path=custom.rstrip("/") + "/" + filename)
        log.info("Cancelled.")
        return PlacementSelection(path="", cancelled=True)

    log.info("Suggested placement for '%s':", title)
    log.info("")
    for i, c in enumerate(result.candidates, 1):
        log.info("  %d  %-40s score %d", i, c.path + "/" + filename, c.score)
    log.info("")

    if dry_run:
        log.info("(dry-run) No changes made.")
        return PlacementSelection(path="", cancelled=True)

    prompt = f"Select [1-{len(result.candidates)}], (c)ustom path, or (n) to cancel: "
    choice = input(prompt).strip().lower()

    if choice == "n":
        log.info("Cancelled.")
        return PlacementSelection(path="", cancelled=True)
    elif choice == "c":
        custom = input("Enter path relative to knowledge/: ").strip()
        if not custom:
            log.info("Cancelled.")
            return PlacementSelection(path="", cancelled=True)
        return PlacementSelection(path=custom.rstrip("/") + "/" + filename)
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(result.candidates):
                return PlacementSelection(
                    path=result.candidates[idx].path + "/" + filename,
                )
            log.error("Invalid selection.")
            return PlacementSelection(path="", cancelled=True)
        except ValueError:
            log.error("Invalid input.")
            return PlacementSelection(path="", cancelled=True)


def _resolve_collision(dest: Path, max_suffix: int = 10) -> Path | None:
    """If dest exists, try numeric suffixes (-2, -3, ...). Returns None if all taken."""
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    for i in range(2, max_suffix + 1):
        candidate = parent / f"{stem}-{i}{suffix}"
        if not candidate.exists():
            return candidate
    return None


def handle_add(args) -> None:
    import shutil

    from brain_sync.commands.placement import (
        SourceKind,
        classify_source,
        extract_file_excerpt,
        extract_title_from_url,
    )
    from brain_sync.commands.sources import SourceAlreadyExistsError, add_source
    from brain_sync.sources import UnsupportedSourceError

    try:
        source_kind = classify_source(args.source)
    except UnsupportedSourceError:
        log.error("Not a URL or existing file: %s", args.source)
        sys.exit(1)

    # Flag validation
    if source_kind == SourceKind.FILE:
        if args.fetch_children or args.sync_attachments:
            log.error("--fetch-children/--sync-attachments can only be used with URLs")
            sys.exit(1)
        file_path = Path(args.source).resolve()
        if not file_path.exists():
            log.error("File not found: %s", file_path)
            sys.exit(1)
        supported = {".md", ".txt"}
        if file_path.suffix.lower() in {".pdf", ".docx"}:
            log.error("Unsupported: %s — use brain-sync convert to produce markdown first", file_path.suffix)
            sys.exit(1)
        if file_path.suffix.lower() not in supported:
            log.error("Unsupported file type: %s (supported: %s)", file_path.suffix, ", ".join(sorted(supported)))
            sys.exit(1)

    if source_kind == SourceKind.URL and getattr(args, "copy", False):
        log.error("--copy can only be used with local files")
        sys.exit(1)

    root = _resolve_root_or_exit(args)

    # Early duplicate check — before interactive placement to avoid wasted effort
    if source_kind == SourceKind.URL:
        from brain_sync.commands.sources import check_source_exists

        existing = check_source_exists(root, args.source)
        if existing is not None:
            log.warning("Source already registered: %s", existing.canonical_id)
            log.warning("  URL: %s", existing.source_url)
            log.warning("  Path: %s", existing.target_path)
            return

    # --- URL branch ---
    if source_kind == SourceKind.URL:
        if args.target_path is None:
            # Interactive placement for URLs — resolve real title for Google Docs
            from brain_sync.sources import canonical_filename, detect_source_type, extract_id
            from brain_sync.sources.title_resolution import resolve_source_title_sync

            title = resolve_source_title_sync(args.source) or extract_title_from_url(args.source) or "Untitled"
            source_type = detect_source_type(args.source)
            doc_id = extract_id(source_type, args.source)
            filename = canonical_filename(source_type, doc_id, title)
            subtree = args.subtree
            if subtree is None:
                subtree = _detect_subtree(root)

            selection = _interactive_placement(
                root,
                title,
                "",
                filename,
                args.source,
                subtree,
                getattr(args, "dry_run", False),
            )
            if selection.cancelled:
                return
            # Extract directory portion from selection path
            target_path = str(Path(selection.path).parent)
        else:
            target_path = args.target_path

        try:
            result = add_source(
                root=root,
                url=args.source,
                target_path=target_path,
                fetch_children=args.fetch_children,
                sync_attachments=args.sync_attachments,
                child_path=getattr(args, "child_path", None),
            )
        except UnsupportedSourceError:
            log.exception("Unsupported source")
            return
        except SourceAlreadyExistsError as e:
            log.warning("Source already registered: %s", e.canonical_id)
            log.warning("  URL: %s", e.source_url)
            log.warning("  Path: %s", e.target_path)
            return
        except BrainNotFoundError:
            log.exception("Cannot resolve brain root")
            sys.exit(1)

        log.info("Registered source: %s", result.canonical_id)
        log.info("  URL: %s", result.source_url)
        log.info("  Path: knowledge/%s", result.target_path)
        log.info(
            "  Children: %s, Attachments: %s",
            result.fetch_children,
            result.sync_attachments,
        )
        log.info("  Will sync on next `brain-sync run`")
        return

    # --- File branch ---
    file_path = Path(args.source).resolve()
    title = file_path.stem
    excerpt = extract_file_excerpt(file_path)

    if args.target_path is not None:
        target_dir = root / "knowledge" / args.target_path
    else:
        filename = file_path.name
        subtree = args.subtree
        if subtree is None:
            subtree = _detect_subtree(root)

        selection = _interactive_placement(
            root,
            title,
            excerpt,
            filename,
            args.source,
            subtree,
            getattr(args, "dry_run", False),
        )
        if selection.cancelled:
            return
        # selection.path is "area/subarea/filename.ext"
        target_dir = root / "knowledge" / str(Path(selection.path).parent)

    dest = _resolve_collision(target_dir / file_path.name)
    if dest is None:
        log.error("File already exists and all numeric suffixes taken: %s", target_dir / file_path.name)
        return

    target_dir.mkdir(parents=True, exist_ok=True)
    if getattr(args, "copy", False):
        shutil.copy2(str(file_path), str(dest))
        log.info("Copied to %s", dest.relative_to(root))
    else:
        shutil.move(str(file_path), str(dest))
        log.info("Moved to %s", dest.relative_to(root))


def _detect_subtree(root: Path) -> str | None:
    """Auto-detect subtree from current working directory."""
    knowledge_root = root / "knowledge"
    cwd = Path.cwd().resolve()
    try:
        if cwd.is_relative_to(knowledge_root):
            from brain_sync.fs_utils import normalize_path

            rel = normalize_path(cwd.relative_to(knowledge_root))
            if rel:
                log.info("Auto-detected subtree: %s", rel)
                return rel
    except (ValueError, OSError):
        pass
    return None


def handle_remove(args) -> None:
    from brain_sync.commands.sources import SourceNotFoundError, remove_source

    try:
        result = remove_source(
            root=_get_root(args),
            source=args.source,
            delete_files=args.delete_files,
        )
    except SourceNotFoundError as e:
        log.warning("Source not found: %s", e.source)
        return
    except BrainNotFoundError:
        log.exception("Cannot resolve brain root")
        sys.exit(1)

    log.info("Removing source: %s", result.canonical_id)
    log.info("  URL: %s", result.source_url)
    log.info("  Path: knowledge/%s", result.target_path)
    if result.files_deleted:
        log.info("  Deleted: %s", args.root.resolve() / "knowledge" / result.target_path)
    log.info("Source removed")


def handle_list(args) -> None:
    from brain_sync.commands.sources import list_sources

    try:
        sources = list_sources(
            root=_get_root(args),
            filter_path=args.filter_path,
        )
    except BrainNotFoundError:
        log.exception("Cannot resolve brain root")
        sys.exit(1)

    if not sources:
        log.info("No sources registered. Use `brain-sync add` to register a source.")
        return

    for s in sources:
        log.info("%s", s.canonical_id)
        log.info("  URL:  %s", s.source_url)
        log.info("  Path: knowledge/%s", s.target_path)
        if args.status:
            log.info("  Last checked: %s", s.last_checked_utc or "never")
            log.info("  Last changed: %s", s.last_changed_utc or "never")
            log.info("  Interval: %ss", s.current_interval_secs)
            flags = []
            if s.fetch_children:
                flags.append("children")
            if s.sync_attachments:
                flags.append("attachments")
            if flags:
                log.info("  Context: %s", ", ".join(flags))


def handle_move(args) -> None:
    from brain_sync.commands.sources import SourceNotFoundError, move_source

    try:
        result = move_source(
            root=_get_root(args),
            source=args.source,
            to_path=args.to_path,
        )
    except SourceNotFoundError as e:
        log.warning("Source not found: %s", e.source)
        return
    except BrainNotFoundError:
        log.exception("Cannot resolve brain root")
        sys.exit(1)

    if result.files_moved:
        log.info("Moved files: knowledge/%s -> knowledge/%s", result.old_path, result.new_path)
    log.info("Source %s moved to knowledge/%s", result.canonical_id, result.new_path)


def handle_update(args) -> None:
    from brain_sync.commands.sources import SourceNotFoundError, update_source

    try:
        child_path_val = getattr(args, "child_path", None)
        result = update_source(
            root=_get_root(args),
            source=args.source,
            fetch_children=args.fetch_children,
            sync_attachments=args.sync_attachments,
            child_path=child_path_val if child_path_val is not None else ...,  # type: ignore[arg-type]
        )
    except SourceNotFoundError as e:
        log.warning("Source not found: %s", e.source)
        return
    except BrainNotFoundError:
        log.exception("Cannot resolve brain root")
        sys.exit(1)

    log.info("Updated source: %s", result.canonical_id)
    log.info(
        "  Children: %s, Attachments: %s",
        result.fetch_children,
        result.sync_attachments,
    )


def handle_reconcile(args) -> None:
    from brain_sync.commands.sources import reconcile_sources

    try:
        result = reconcile_sources(root=_get_root(args))
    except BrainNotFoundError:
        log.exception("Cannot resolve brain root")
        sys.exit(1)

    if not result.updated and not result.not_found:
        log.info("All sources are at their expected paths. Nothing to reconcile.")
        return

    for entry in result.updated:
        log.info("Updated %s: knowledge/%s -> knowledge/%s", entry.canonical_id, entry.old_path, entry.new_path)

    if result.not_found:
        log.warning("%d source(s) could not be found on disk:", len(result.not_found))
        for cid in result.not_found:
            log.warning("  %s", cid)

    log.info("Reconciled %d source(s). %d unchanged.", len(result.updated), result.unchanged)


def handle_status(args) -> None:
    from brain_sync.commands.sources import list_sources
    from brain_sync.state import load_all_insight_states
    from brain_sync.token_tracking import get_usage_summary

    root = _resolve_root_or_exit(args)

    # Source count
    try:
        sources = list_sources(root=root)
        log.info("Sources: %d registered", len(sources))
    except Exception:
        log.exception("Failed to load sources")

    # Regen health
    try:
        states = load_all_insight_states(root)
        by_status: dict[str, int] = {}
        for s in states:
            by_status[s.regen_status] = by_status.get(s.regen_status, 0) + 1
        parts = [f"{status}={count}" for status, count in sorted(by_status.items())]
        log.info("Insight states: %s", ", ".join(parts) if parts else "none")
    except Exception:
        log.exception("Failed to load insight states")

    # Token usage
    try:
        usage = get_usage_summary(root, days=7)
        log.info(
            "Token usage (7d): %d invocations, %d input, %d output, %d total",
            usage["total_invocations"],
            usage["total_input"],
            usage["total_output"],
            usage["total_tokens"],
        )
    except Exception:
        log.exception("Failed to load token usage")


def handle_regen(args) -> None:
    root = _get_root(args)
    if root is None:
        try:
            from brain_sync.commands.context import resolve_root

            root = resolve_root()
        except BrainNotFoundError:
            log.exception("Cannot resolve brain root")
            sys.exit(1)

    knowledge_path = args.knowledge_path or ""

    if knowledge_path:
        knowledge_dir = root / "knowledge" / knowledge_path
        if not knowledge_dir.is_dir():
            log.error("Knowledge path '%s' does not exist", knowledge_path)
            sys.exit(1)

    log.info(
        "Regenerating insights for: %s",
        knowledge_path or "all knowledge paths",
    )

    async def _do_regen() -> int:
        from brain_sync.regen import regen_all, regen_path
        from brain_sync.regen_lifecycle import regen_session

        # reclaim_stale only for full regen — single-path callers should not
        # implicitly clean up unrelated stale rows from prior crashes.
        async with regen_session(root, reclaim_stale=not knowledge_path) as session:
            if knowledge_path:
                return await regen_path(root, knowledge_path, owner_id=session.owner_id, session_id=session.session_id)
            else:
                return await regen_all(root, owner_id=session.owner_id, session_id=session.session_id)

    loop = asyncio.new_event_loop()
    try:
        count = loop.run_until_complete(_do_regen())
        log.info("Done. %d insight file%s regenerated.", count, "s" if count != 1 else "")
    except Exception:
        log.exception("Regen failed for %s", knowledge_path or "all")
        sys.exit(1)
    finally:
        loop.close()


def handle_convert(args) -> None:
    file_path = args.file.resolve()
    if not file_path.exists():
        log.error("File not found: %s", file_path)
        sys.exit(1)

    if args.comments_from:
        # Mode 1: .md body + .docx comments
        docx_path = args.comments_from.resolve()
        if not docx_path.exists():
            log.error("Comments file not found: %s", docx_path)
            sys.exit(1)

        from brain_sync.docx_converter import append_comments_to_markdown

        output_path = args.output or file_path
        if output_path != file_path:
            import shutil

            shutil.copy2(file_path, output_path)
            added = append_comments_to_markdown(output_path, docx_path)
        else:
            added = append_comments_to_markdown(file_path, docx_path)

        if added:
            log.info("Comments appended to %s", output_path)
        else:
            log.info("No comments found in %s", docx_path.name)
    else:
        # Mode 2: .docx only (body + comments)
        if file_path.suffix.lower() != ".docx":
            log.error("Expected .docx file, or use --comments-from with a .md file")
            sys.exit(1)

        from brain_sync.docx_converter import docx_to_markdown

        output_path = args.output or file_path.with_suffix(".md")
        markdown = docx_to_markdown(file_path)
        output_path.write_text(markdown, encoding="utf-8")
        log.info("Converted %s -> %s", file_path.name, output_path)


def handle_config(args) -> None:
    if not args.config_source:
        log.error("Specify a source to configure. Available: confluence, google")
        sys.exit(1)

    if args.config_source == "confluence":
        from brain_sync.commands.config import configure_confluence

        configure_confluence(
            domain=args.domain,
            email=args.email,
            token=args.token,
        )
    elif args.config_source == "google":
        from brain_sync.commands.config import configure_google

        try:
            if not configure_google(
                reauth=getattr(args, "reauth", False),
            ):
                sys.exit(1)
        except ImportError as exc:
            log.debug("Google import failed", exc_info=True)
            log.error("%s", exc)
            sys.exit(1)


def handle_migrate(args) -> None:
    from brain_sync.commands.sources import migrate_sources

    try:
        result = migrate_sources(root=_get_root(args))
    except BrainNotFoundError:
        log.exception("Cannot resolve brain root")
        sys.exit(1)

    if result.sources_migrated == 0 and result.dirs_cleaned == 0:
        log.info("Nothing to migrate. All sources already use the new layout.")
        return

    if result.files_migrated:
        log.info(
            "Migrated %d attachment(s) across %d source(s).",
            result.files_migrated,
            result.sources_migrated,
        )
    if result.dirs_cleaned:
        suffix = "y" if result.dirs_cleaned == 1 else "ies"
        log.info("Cleaned up %d stale _sync-context/ director%s.", result.dirs_cleaned, suffix)


def handle_update_skill(args) -> None:
    from brain_sync.commands.init import update_skill

    updated = update_skill()
    log.info("Skill updated (%s)", ", ".join(p.name for p in updated))

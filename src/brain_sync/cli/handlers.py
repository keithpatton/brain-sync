"""CLI command handlers — logging-based wrappers around commands/ API."""

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

    result = init_brain(
        args.root,
        model=args.model,
        confluence_domain=args.confluence_domain,
        confluence_email=args.confluence_email,
        confluence_token=args.confluence_token,
        dry_run=args.dry_run,
    )

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
        "  Links: %s, Children: %s, Attachments: %s",
        result.include_links,
        result.include_children,
        result.include_attachments,
    )
    log.info("  Will sync on next `brain-sync run`")


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
            if s.include_links:
                flags.append("links")
            if s.include_children:
                flags.append("children")
            if s.include_attachments:
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


def handle_status(args) -> None:
    log.info("Status not yet implemented")


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
        from brain_sync.regen import regen_path

        knowledge_dir = root / "knowledge" / knowledge_path
        if not knowledge_dir.is_dir():
            log.error("Knowledge path '%s' does not exist", knowledge_path)
            sys.exit(1)

        log.info("Regenerating insights for: %s", knowledge_path)
        loop = asyncio.new_event_loop()
        try:
            count = loop.run_until_complete(regen_path(root, knowledge_path))
            log.info("Done. %d insight file%s regenerated.", count, "s" if count != 1 else "")
        except Exception:
            log.exception("Regen failed for %s", knowledge_path)
            sys.exit(1)
        finally:
            loop.close()
    else:
        from brain_sync.regen import regen_all

        log.info("Regenerating insights for all knowledge paths...")
        loop = asyncio.new_event_loop()
        try:
            count = loop.run_until_complete(regen_all(root))
            log.info("Done. %d insight file%s regenerated.", count, "s" if count != 1 else "")
        except Exception:
            log.exception("Regen failed")
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


def handle_update_skill(args) -> None:
    from brain_sync.commands.init import update_skill

    updated = update_skill()
    log.info("Skill updated (%s)", ", ".join(p.name for p in updated))

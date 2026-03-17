"""CLI command handlers — logging-based wrappers around commands/ API."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from brain_sync.application.placement import PlacementCandidateView
from brain_sync.application.roots import BrainNotFoundError, InvalidBrainRootError
from brain_sync.brain.fileops import path_is_dir

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlacementSelection:
    path: str
    cancelled: bool = False


def _get_root(args) -> Path | None:
    """Extract root from args, returning None if not provided."""
    root = getattr(args, "root", None)
    if root is not None:
        return root.resolve()
    return None


def _root_resolution_hint() -> str:
    return "Use --root <brain> or run `brain-sync init <path>` to create/register a brain."


def _resolve_cli_root() -> Path:
    """Resolve a brain root for CLI use.

    Order:
    1. current working directory if it is a valid brain root
    2. configured root from runtime config
    """
    from brain_sync.application.roots import resolve_active_root, validate_brain_root

    cwd = Path.cwd().resolve()
    try:
        validate_brain_root(cwd)
        return cwd
    except InvalidBrainRootError:
        pass

    return resolve_active_root()


def handle_init(args) -> None:
    from brain_sync.application.init import init_brain

    result = init_brain(args.root, model=args.model, dry_run=args.dry_run)

    prefix = "[dry-run] " if args.dry_run else ""
    log.info("%sInitialising brain at: %s", prefix, result.root)
    if result.was_existing:
        log.info("  Existing directory detected, will add missing structure")
    log.info("%sBrain initialised successfully", prefix)
    log.info("  knowledge/       - Add your content here")
    log.info("  knowledge/_core/ - Always-loaded reference material")
    log.info("  knowledge/**/.brain-sync/insights/ - Auto-generated summaries")

    from brain_sync.application.init import skill_install_dir

    log.info("  Skill installed to %s", skill_install_dir())


def handle_run(args) -> None:
    root = _get_root(args)
    if root is None:
        try:
            root = _resolve_cli_root()
        except BrainNotFoundError as e:
            log.error("Cannot resolve brain root: %s. %s", e, _root_resolution_hint())
            sys.exit(1)

    if not path_is_dir(root):
        log.error("--root '%s' is not a directory", root)
        sys.exit(1)

    from brain_sync.sync.daemon import run

    loop = asyncio.new_event_loop()

    def _shutdown(sig: int, frame: object) -> None:
        log.info("Received signal %s, shutting down...", sig)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    signal.signal(signal.SIGINT, _shutdown)
    if sys.platform == "win32" and hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _shutdown)
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
            root = _resolve_cli_root()
        except BrainNotFoundError as e:
            log.error("Cannot resolve brain root: %s. %s", e, _root_resolution_hint())
            sys.exit(1)
    return root


def _prompt_for_placement(
    title: str,
    filename: str,
    candidates: list[PlacementCandidateView],
    dry_run: bool,
) -> PlacementSelection:
    """Show interactive placement suggestions and return the user's choice."""
    if not candidates:
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
    for i, c in enumerate(candidates, 1):
        log.info("  %d  %-40s score %d", i, c.path + "/" + filename, c.score)
    log.info("")

    if dry_run:
        log.info("(dry-run) No changes made.")
        return PlacementSelection(path="", cancelled=True)

    prompt = f"Select [1-{len(candidates)}], (c)ustom path, or (n) to cancel: "
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
            if 0 <= idx < len(candidates):
                return PlacementSelection(
                    path=candidates[idx].path + "/" + filename,
                )
            log.error("Invalid selection.")
            return PlacementSelection(path="", cancelled=True)
        except ValueError:
            log.error("Invalid input.")
            return PlacementSelection(path="", cancelled=True)


def handle_add(args) -> None:
    from brain_sync.application.placement import (
        DocumentTitleRequiredError,
        detect_subtree,
        suggest_document_placement,
    )
    from brain_sync.application.sources import (
        InvalidChildDiscoveryRequestError,
        SourceAlreadyExistsError,
        UnsupportedSourceUrlError,
        add_source,
        check_source_exists,
    )

    # URL-only: reject non-URLs with helpful hint
    parsed = urlparse(args.source)
    if parsed.scheme not in ("http", "https", "test"):
        log.error("Not a URL. Use `brain-sync add-file <path>` for local files.")
        sys.exit(1)

    root = _resolve_root_or_exit(args)

    try:
        existing = check_source_exists(root, args.source)
        if existing is not None:
            log.warning("Source already registered: %s", existing.canonical_id)
            log.warning("  URL: %s", existing.source_url)
            log.warning("  Path: %s", existing.target_path)
            return
    except UnsupportedSourceUrlError:
        log.exception("Unsupported source")
        return

    if args.target_path is None:
        subtree = args.subtree
        if subtree is None:
            subtree = detect_subtree(root, cwd=Path.cwd())
            if subtree:
                log.info("Auto-detected subtree: %s", subtree)

        try:
            placement, _ = suggest_document_placement(
                root,
                source_url=args.source,
                subtree=subtree,
                allow_url_title_fallback=True,
                fallback_title="Untitled",
            )
        except DocumentTitleRequiredError as e:
            log.warning("%s", e)
            return

        filename = placement.suggested_filename or "document.md"
        selection = _prompt_for_placement(
            placement.document_title,
            filename,
            placement.candidates,
            getattr(args, "dry_run", False),
        )
        if selection.cancelled:
            return
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
    except UnsupportedSourceUrlError:
        log.exception("Unsupported source")
        return
    except SourceAlreadyExistsError as e:
        log.warning("Source already registered: %s", e.canonical_id)
        log.warning("  URL: %s", e.source_url)
        log.warning("  Path: %s", e.target_path)
        return
    except InvalidChildDiscoveryRequestError as e:
        log.warning("%s", e)
        return
    except BrainNotFoundError as e:
        log.error("Cannot resolve brain root: %s", e)
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


def handle_add_file(args) -> None:
    from brain_sync.application.local_files import (
        InvalidKnowledgePathError,
        LocalFileCollisionError,
        LocalFileNotFoundError,
        UnsupportedLocalFileTypeError,
        add_local_file,
    )
    from brain_sync.application.placement import (
        detect_subtree,
        extract_file_excerpt,
        suggest_document_placement,
    )
    from brain_sync.brain.fileops import ADDFILE_EXTENSIONS

    file_path = Path(args.file).resolve()
    if not file_path.exists():
        log.error("File not found: %s", file_path)
        sys.exit(1)
    if file_path.suffix.lower() not in ADDFILE_EXTENSIONS:
        log.error(
            "Unsupported file type: %s. add-file supports: %s",
            file_path.suffix.lower(),
            ", ".join(sorted(ADDFILE_EXTENSIONS)),
        )
        sys.exit(1)

    root = _resolve_root_or_exit(args)

    if args.target_path is not None:
        target_path = args.target_path
    else:
        title = file_path.stem
        excerpt = extract_file_excerpt(file_path)
        subtree = args.subtree
        if subtree is None:
            subtree = detect_subtree(root, cwd=Path.cwd())
            if subtree:
                log.info("Auto-detected subtree: %s", subtree)

        placement, _ = suggest_document_placement(
            root,
            document_title=title,
            document_excerpt=excerpt,
            subtree=subtree,
        )
        selection = _prompt_for_placement(title, file_path.name, placement.candidates, getattr(args, "dry_run", False))
        if selection.cancelled:
            return
        target_path = str(Path(selection.path).parent)

    try:
        result = add_local_file(
            root,
            source=file_path,
            target_path=target_path,
            copy=not getattr(args, "move", False),
        )
    except LocalFileNotFoundError as e:
        log.error("File not found: %s", e.source)
        sys.exit(1)
    except UnsupportedLocalFileTypeError as e:
        log.error("%s", e)
        sys.exit(1)
    except LocalFileCollisionError as e:
        log.error("%s", e)
        return
    except InvalidKnowledgePathError as e:
        log.error("%s", e)
        sys.exit(1)

    verb = "Moved" if result.action == "moved" else "Copied"
    log.info("%s to %s", verb, result.path)


def handle_remove_file(args) -> None:
    from brain_sync.application import (
        InvalidKnowledgePathError,
        KnowledgeFileNotFoundError,
        KnowledgePathIsDirectoryError,
        remove_local_file,
    )

    root = _resolve_root_or_exit(args)
    try:
        result = remove_local_file(root, path=args.file)
    except InvalidKnowledgePathError:
        log.error("Path must be within knowledge/: %s", args.file)
        sys.exit(1)
    except KnowledgeFileNotFoundError:
        log.error("File not found: knowledge/%s", args.file)
        sys.exit(1)
    except KnowledgePathIsDirectoryError:
        log.error("Not a file: knowledge/%s", args.file)
        sys.exit(1)

    log.info("Removed knowledge/%s. %s", result.path, result.hint)


def handle_remove(args) -> None:
    from brain_sync.application.sources import SourceNotFoundError, remove_source

    try:
        result = remove_source(
            root=_get_root(args),
            source=args.source,
            delete_files=args.delete_files,
        )
    except SourceNotFoundError as e:
        log.warning("Source not found: %s", e.source)
        return
    except BrainNotFoundError as e:
        log.error("Cannot resolve brain root: %s", e)
        sys.exit(1)

    log.info("Removing source: %s", result.canonical_id)
    log.info("  URL: %s", result.source_url)
    log.info("  Path: knowledge/%s", result.target_path)
    if result.files_deleted:
        log.info("  Deleted: %s", args.root.resolve() / "knowledge" / result.target_path)
    log.info("Source removed")


def handle_list(args) -> None:
    from brain_sync.application.sources import list_sources

    try:
        sources = list_sources(
            root=_get_root(args),
            filter_path=args.filter_path,
        )
    except BrainNotFoundError as e:
        log.error("Cannot resolve brain root: %s", e)
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
    from brain_sync.application.sources import SourceNotFoundError, move_source

    try:
        result = move_source(
            root=_get_root(args),
            source=args.source,
            to_path=args.to_path,
        )
    except SourceNotFoundError as e:
        log.warning("Source not found: %s", e.source)
        return
    except BrainNotFoundError as e:
        log.error("Cannot resolve brain root: %s", e)
        sys.exit(1)

    if result.files_moved:
        log.info("Moved files: knowledge/%s -> knowledge/%s", result.old_path, result.new_path)
    log.info("Source %s moved to knowledge/%s", result.canonical_id, result.new_path)


def handle_update(args) -> None:
    from brain_sync.application.sources import InvalidChildDiscoveryRequestError, SourceNotFoundError, update_source

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
    except InvalidChildDiscoveryRequestError as e:
        log.warning("%s", e)
        return
    except BrainNotFoundError as e:
        log.error("Cannot resolve brain root: %s", e)
        sys.exit(1)

    log.info("Updated source: %s", result.canonical_id)
    log.info(
        "  Children: %s, Attachments: %s",
        result.fetch_children,
        result.sync_attachments,
    )


def handle_reconcile(args) -> None:
    from brain_sync.application.reconcile import reconcile_brain

    root = _resolve_root_or_exit(args)

    try:
        report = reconcile_brain(root, include_knowledge_tree=True)
    except BrainNotFoundError as e:
        log.error("Cannot resolve brain root: %s", e)
        sys.exit(1)

    if not report.has_changes:
        log.info("All sources are at their expected paths. Nothing to reconcile.")
        return

    for entry in report.updated:
        log.info("Updated %s: knowledge/%s -> knowledge/%s", entry.canonical_id, entry.old_path, entry.new_path)

    if report.not_found:
        log.warning("%d source(s) could not be found on disk:", len(report.not_found))
        for cid in report.not_found:
            log.warning("  %s", cid)

    if report.reappeared:
        log.info("%d missing source(s) reappeared during reconcile.", len(report.reappeared))

    if report.deleted:
        log.info("%d missing source(s) were deregistered after the grace period.", len(report.deleted))

    if report.orphan_rows_pruned:
        log.info("Pruned %d orphan runtime row(s).", report.orphan_rows_pruned)

    if report.orphans_cleaned:
        log.info("Cleaned %d orphan insight state(s).", len(report.orphans_cleaned))

    if report.content_changed:
        log.info("Detected offline changes in %d tracked knowledge area(s).", len(report.content_changed))

    if report.enqueued_paths:
        log.info("Discovered %d new knowledge area(s) needing regen.", len(report.enqueued_paths))

    log.info("Reconciled %d source(s). %d unchanged.", len(report.updated), report.unchanged)


def handle_status(args) -> None:
    from brain_sync.application.status import build_status_summary

    root = _resolve_root_or_exit(args)

    try:
        summary = build_status_summary(root, usage_days=7)
        log.info("Sources: %d registered", summary.source_count)
        parts = [f"{status}={count}" for status, count in sorted(summary.insight_states_by_status.items())]
        log.info("Insight states: %s", ", ".join(parts) if parts else "none")
        usage = summary.usage
        if summary.usage_available:
            log.info(
                "Token usage (7d): %d invocations, %d input, %d output, %d total",
                usage.total_invocations,
                usage.total_input,
                usage.total_output,
                usage.total_tokens,
            )
        else:
            log.info("Token usage (7d): unavailable for a non-active brain root")
    except Exception:
        log.exception("Failed to load status")


def handle_regen(args) -> None:
    root = _get_root(args)
    if root is None:
        try:
            from brain_sync.application.roots import resolve_active_root

            root = resolve_active_root()
        except BrainNotFoundError as e:
            log.error("Cannot resolve brain root: %s", e)
            sys.exit(1)

    knowledge_path = args.knowledge_path or ""

    if knowledge_path:
        knowledge_dir = root / "knowledge" / knowledge_path
        if not path_is_dir(knowledge_dir):
            log.error("Knowledge path '%s' does not exist", knowledge_path)
            sys.exit(1)

    log.info(
        "Regenerating insights for: %s",
        knowledge_path or "all knowledge paths",
    )

    async def _do_regen() -> int:
        from brain_sync.application.regen import run_regen

        return await run_regen(root, knowledge_path or None)

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

        from brain_sync.sources.docx import append_comments_to_markdown

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

        from brain_sync.sources.docx import docx_to_markdown

        output_path = args.output or file_path.with_suffix(".md")
        markdown = docx_to_markdown(file_path)
        output_path.write_text(markdown, encoding="utf-8")
        log.info("Converted %s -> %s", file_path.name, output_path)


def handle_config(args) -> None:
    if not args.config_source:
        log.error("Specify a source to configure. Available: confluence, google")
        sys.exit(1)

    if args.config_source == "confluence":
        from brain_sync.application.config import configure_confluence

        configure_confluence(
            domain=args.domain,
            email=args.email,
            token=args.token,
        )
    elif args.config_source == "google":
        from brain_sync.application.config import configure_google

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
    from brain_sync.application.sources import migrate_sources

    try:
        result = migrate_sources(root=_get_root(args))
    except BrainNotFoundError as e:
        log.error("Cannot resolve brain root: %s", e)
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
    from brain_sync.application.init import update_skill

    updated = update_skill()
    log.info("Skill updated (%s)", ", ".join(p.name for p in updated))


def handle_doctor(args) -> None:
    from brain_sync.application.doctor import Severity, adopt_baseline, deregister_missing, doctor, rebuild_db

    # Mutual exclusivity check
    flags = [args.fix, args.rebuild_db, args.deregister_missing, args.adopt_baseline]
    if sum(bool(f) for f in flags) > 1:
        log.error("--fix, --rebuild-db, --deregister-missing, and --adopt-baseline are mutually exclusive")
        sys.exit(1)

    root = _resolve_root_or_exit(args)

    if args.rebuild_db:
        result = rebuild_db(root)
    elif args.deregister_missing:
        result = deregister_missing(root)
    elif args.adopt_baseline:
        result = adopt_baseline(root)
    else:
        result = doctor(root, fix=args.fix)

    # Log findings grouped by severity
    by_severity: dict[Severity, list] = {}
    for f in result.findings:
        by_severity.setdefault(f.severity, []).append(f)

    for severity in Severity:
        items = by_severity.get(severity, [])
        if not items:
            continue
        if severity == Severity.OK:
            log.info("%d check(s) OK", len(items))
        else:
            # Human-readable severity labels
            labels = {
                Severity.DRIFT: "DRIFT",
                Severity.CORRUPTION: "CORRUPTION",
                Severity.WOULD_TRIGGER_REGEN: "NEEDS REGEN",
                Severity.WOULD_TRIGGER_FETCH: "NEEDS FETCH",
            }
            label = labels.get(severity, severity.value)
            for item in items:
                level = logging.WARNING if severity in (Severity.DRIFT, Severity.CORRUPTION) else logging.INFO
                suffix = " [FIXED]" if item.fix_applied else ""
                log.log(level, "[%s] %s%s", label, item.message, suffix)

    if result.is_healthy:
        log.info("Brain is healthy.")
    else:
        # Build a context-aware exit message
        unfixed = [f for f in result.findings if f.severity != Severity.OK and not f.fix_applied]
        has_fixable = any(f.severity in (Severity.DRIFT, Severity.CORRUPTION) for f in unfixed)
        has_run = any(f.severity in (Severity.WOULD_TRIGGER_REGEN, Severity.WOULD_TRIGGER_FETCH) for f in unfixed)

        hints: list[str] = []
        if has_fixable:
            hints.append("run 'brain-sync doctor --fix' to repair")
        if has_run:
            hints.append("run 'brain-sync run' to sync and regenerate")

        if hints:
            log.warning("Brain has issues: %s.", "; ".join(hints))
        else:
            log.warning("Brain has issues.")
        sys.exit(1)

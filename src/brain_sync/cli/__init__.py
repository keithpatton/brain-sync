from __future__ import annotations

import argparse
from argparse import BooleanOptionalAction
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brain-sync",
        description="Brain engine: sync, watch, and maintain AI-generated insights",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO, or from config.json)",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # --- init ---
    p_init = sub.add_parser("init", help="Initialise a new brain or migrate an existing one")
    p_init.add_argument("root", type=Path, help="Brain root directory to create/initialise")
    p_init.add_argument("--model", default=None, help="Default model for insight generation (e.g. claude-sonnet-4-6)")
    p_init.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")

    # --- run ---
    p_run = sub.add_parser("run", help="Start the daemon (sync + watch + regen)")
    p_run.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )

    # --- add ---
    p_add = sub.add_parser("add", help="Add a URL or local file to the brain")
    p_add.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )
    p_add.add_argument("source", help="Source URL or local file path")
    p_add.add_argument("--path", dest="target_path", default=None, help="Target path relative to knowledge/")
    p_add.add_argument("--fetch-children", action="store_true", help="Discover and add child pages (one-shot)")
    p_add.add_argument("--sync-attachments", action="store_true", help="Discover and sync attachments")
    p_add.add_argument(
        "--child-path", default=None, help="Override target path for children ('.' = same level as parent)"
    )
    p_add.add_argument("--copy", action="store_true", help="Copy instead of move (local files only)")
    p_add.add_argument("--dry-run", action="store_true", help="Show suggestions without making changes")
    p_add.add_argument("--subtree", default=None, help="Restrict placement suggestions to this subtree")

    # --- remove ---
    p_remove = sub.add_parser("remove", help="Unregister a sync source")
    p_remove.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )
    p_remove.add_argument("source", help="Canonical ID or URL of the source to remove")
    p_remove.add_argument("--delete-files", action="store_true", help="Also delete synced files from disk")

    # --- list ---
    p_list = sub.add_parser("list", help="List registered sync sources")
    p_list.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )
    p_list.add_argument("--path", dest="filter_path", help="Filter by target path prefix")
    p_list.add_argument("--status", action="store_true", help="Show sync status details")

    # --- move ---
    p_move = sub.add_parser("move", help="Move a sync source to a new knowledge path")
    p_move.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )
    p_move.add_argument("source", help="Canonical ID of the source to move")
    p_move.add_argument("--to", dest="to_path", required=True, help="New target path relative to knowledge/")

    # --- update ---
    p_update = sub.add_parser("update", help="Update settings for a registered source")
    p_update.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )
    p_update.add_argument("source", help="Canonical ID or URL of the source to update")
    p_update.add_argument(
        "--fetch-children",
        action="store_true",
        default=None,
        help="Discover and add child pages as independent sources (one-shot)",
    )
    p_update.add_argument(
        "--sync-attachments",
        action=BooleanOptionalAction,
        default=None,
        help="Discover and sync attachments",
    )
    p_update.add_argument(
        "--child-path",
        default=None,
        help="Override target path for discovered children (use '.' for same level as parent)",
    )

    # --- reconcile ---
    p_reconcile = sub.add_parser(
        "reconcile",
        help="Update DB target paths to match where files actually are on disk",
    )
    p_reconcile.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )

    # --- status ---
    p_status = sub.add_parser("status", help="Show daemon and sync status")
    p_status.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )

    # --- regen ---
    p_regen = sub.add_parser("regen", help="Manually trigger insight regeneration")
    p_regen.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )
    p_regen.add_argument("knowledge_path", nargs="?", help="Knowledge path to regenerate (all if omitted)")

    # --- convert ---
    p_convert = sub.add_parser("convert", help="Convert .docx to markdown with comments")
    p_convert.add_argument("file", type=Path, help=".md or .docx file to process")
    p_convert.add_argument(
        "--comments-from",
        type=Path,
        dest="comments_from",
        help=".docx file to extract comments from (when file is .md)",
    )
    p_convert.add_argument("--output", "-o", type=Path, help="Output path (default: in-place or .md extension)")

    # --- config ---
    p_config = sub.add_parser("config", help="Configure source credentials")
    config_sub = p_config.add_subparsers(dest="config_source", help="Source to configure")

    p_config_confluence = config_sub.add_parser("confluence", help="Configure Confluence credentials")
    p_config_confluence.add_argument(
        "--domain", required=True, help="Confluence domain (e.g. yourcompany.atlassian.net)"
    )
    p_config_confluence.add_argument("--email", required=True, help="Confluence account email")
    p_config_confluence.add_argument("--token", required=True, help="Confluence API token")

    p_config_google = config_sub.add_parser("google", help="Authenticate with Google for Google Docs syncing")
    p_config_google.add_argument("--reauth", action="store_true", help="Force re-authentication")

    # --- migrate ---
    p_migrate = sub.add_parser(
        "migrate",
        help="Migrate legacy _sync-context/ to _attachments/ layout",
    )
    p_migrate.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )

    # --- update-skill ---
    p_skill = sub.add_parser("update-skill", help="Update the installed skill and instructions")
    p_skill.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Brain root directory (auto-detected from config if omitted)",
    )

    return parser

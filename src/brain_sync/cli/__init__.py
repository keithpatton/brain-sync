from __future__ import annotations

import argparse
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="brain-sync",
        description="Brain engine: sync, watch, and maintain AI-generated insights",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)",
    )

    sub = parser.add_subparsers(dest="command", help="Available commands")

    # --- init ---
    p_init = sub.add_parser("init", help="Initialise a new brain or migrate an existing one")
    p_init.add_argument("root", type=Path, help="Brain root directory to create/initialise")
    p_init.add_argument("--model", default=None, help="Default model for insight generation (e.g. claude-sonnet-4-6)")
    p_init.add_argument("--dry-run", action="store_true", help="Show what would happen without making changes")

    # --- run ---
    p_run = sub.add_parser("run", help="Start the daemon (sync + watch + regen)")
    p_run.add_argument("--root", type=Path, default=None, help="Brain root directory (auto-detected from config if omitted)")

    # --- add ---
    p_add = sub.add_parser("add", help="Register a source URL for syncing")
    p_add.add_argument("--root", type=Path, default=None, help="Brain root directory (auto-detected from config if omitted)")
    p_add.add_argument("url", help="Source URL (Confluence page, Google Doc)")
    p_add.add_argument("--path", dest="target_path", required=True, help="Target path relative to knowledge/")
    p_add.add_argument("--include-links", action="store_true", help="Discover and sync linked pages")
    p_add.add_argument("--include-children", action="store_true", help="Discover and sync child pages")
    p_add.add_argument("--include-attachments", action="store_true", help="Discover and sync attachments")

    # --- remove ---
    p_remove = sub.add_parser("remove", help="Unregister a sync source")
    p_remove.add_argument("--root", type=Path, default=None, help="Brain root directory (auto-detected from config if omitted)")
    p_remove.add_argument("source", help="Canonical ID or URL of the source to remove")
    p_remove.add_argument("--delete-files", action="store_true", help="Also delete synced files from disk")

    # --- list ---
    p_list = sub.add_parser("list", help="List registered sync sources")
    p_list.add_argument("--root", type=Path, default=None, help="Brain root directory (auto-detected from config if omitted)")
    p_list.add_argument("--path", dest="filter_path", help="Filter by target path prefix")
    p_list.add_argument("--status", action="store_true", help="Show sync status details")

    # --- move ---
    p_move = sub.add_parser("move", help="Move a sync source to a new knowledge path")
    p_move.add_argument("--root", type=Path, default=None, help="Brain root directory (auto-detected from config if omitted)")
    p_move.add_argument("source", help="Canonical ID of the source to move")
    p_move.add_argument("--to", dest="to_path", required=True, help="New target path relative to knowledge/")

    # --- status ---
    p_status = sub.add_parser("status", help="Show daemon and sync status")
    p_status.add_argument("--root", type=Path, default=None, help="Brain root directory (auto-detected from config if omitted)")

    # --- regen ---
    p_regen = sub.add_parser("regen", help="Manually trigger insight regeneration")
    p_regen.add_argument("--root", type=Path, default=None, help="Brain root directory (auto-detected from config if omitted)")
    p_regen.add_argument("knowledge_path", nargs="?", help="Knowledge path to regenerate (all if omitted)")

    # --- convert ---
    p_convert = sub.add_parser("convert", help="Convert .docx to markdown with comments")
    p_convert.add_argument("file", type=Path, help=".md or .docx file to process")
    p_convert.add_argument("--comments-from", type=Path, dest="comments_from",
                           help=".docx file to extract comments from (when file is .md)")
    p_convert.add_argument("--output", "-o", type=Path, help="Output path (default: in-place or .md extension)")

    # --- update-skill ---
    p_skill = sub.add_parser("update-skill", help="Update the installed skill and instructions")
    p_skill.add_argument("--root", type=Path, default=None, help="Brain root directory (auto-detected from config if omitted)")

    return parser

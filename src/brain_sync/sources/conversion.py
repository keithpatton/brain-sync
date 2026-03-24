from __future__ import annotations

import re
from typing import TYPE_CHECKING

from markdownify import markdownify as md

if TYPE_CHECKING:
    from brain_sync.sources.base import Comment


def html_to_markdown(html: str) -> str:
    # Remove script/style tags and their content before conversion
    cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    result = md(
        cleaned,
        heading_style="ATX",
        bullets="-",
    )
    lines = result.split("\n")
    lines = [line.rstrip() for line in lines]
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip() + "\n"


def format_comments(comments: list[Comment]) -> str:
    """Convert structured Comment list to agent-friendly markdown."""
    parts: list[str] = []
    for c in comments:
        parts.append(_thread_header(c))
        parts.extend(_thread_metadata(c))
        _append_body(parts, c.content)
        if c.replies:
            parts.append("")
            parts.append("Replies:")
            for index, reply in enumerate(c.replies, start=1):
                parts.append(f"{index}. Reply `{reply.id or 'unknown'}`")
                parts.append(f"   Author: {_escape_md(reply.author)}")
                if reply.created:
                    parts.append(f"   Created: {reply.created}")
                _append_body(parts, reply.content, prefix="   ")
        parts.append("")
    return "\n".join(parts).strip()


def _comment_badges(comment: Comment) -> list[str]:
    badges: list[str] = []
    if comment.comment_type:
        badges.append(comment.comment_type)
    resolution = comment.resolution_status
    if resolution:
        badges.append(resolution)
    elif comment.resolved:
        badges.append("resolved")
    if comment.status and comment.status != "current":
        badges.append(comment.status)
    return badges


def _thread_header(comment: Comment) -> str:
    thread_id = comment.id or "unknown"
    badges = "".join(f" [{badge}]" for badge in _comment_badges(comment))
    return f"### Comment Thread `{thread_id}`{badges}"


def _thread_metadata(comment: Comment) -> list[str]:
    lines = [f"Author: {_escape_md(comment.author)}"]
    if comment.created:
        lines.append(f"Created: {comment.created}")
    if comment.anchor_text:
        lines.append(f'Anchor Text: "{_escape_md(comment.anchor_text)}"')
    if comment.webui_link:
        lines.append(f"Web UI: {comment.webui_link}")
    return lines


def _append_body(parts: list[str], html: str, *, prefix: str = "") -> None:
    body_md = html_to_markdown(html).strip()
    if body_md:
        parts.append(f"{prefix}Body:")
        for line in body_md.splitlines():
            parts.append(f"{prefix}{line}")


def _escape_md(text: str) -> str:
    """Escape markdown special characters that could start lists or headings.

    Preserves indentation — inserts backslash before the special char, not at position 0.
    Does not escape '>' because blockquotes are used intentionally in replies.
    """
    lines = []
    for line in text.split("\n"):
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]
        if stripped and stripped[0] in ("#", "*", "-", "+"):
            lines.append(indent + "\\" + stripped)
        else:
            lines.append(line)
    return "\n".join(lines)


__all__ = ["_escape_md", "format_comments", "html_to_markdown"]

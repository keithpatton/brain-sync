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
    """Convert structured Comment list to markdown section content."""
    parts: list[str] = []
    for c in comments:
        header = f"**{_escape_md(c.author)}**"
        if c.created:
            header += f" ({c.created})"
        if c.resolved:
            header += " [resolved]"
        parts.append(header)
        body_md = html_to_markdown(c.content).strip()
        if body_md:
            parts.append(body_md)
        for reply in c.replies:
            parts.append(f"> **{_escape_md(reply.author)}** ({reply.created})")
            reply_md = html_to_markdown(reply.content).strip()
            if reply_md:
                parts.append(f"> {reply_md}")
        parts.append("")
    return "\n".join(parts).strip()


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

from __future__ import annotations

import re

from markdownify import markdownify as md


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

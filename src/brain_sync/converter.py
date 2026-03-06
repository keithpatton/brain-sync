from __future__ import annotations

import re

from markdownify import markdownify as md


def html_to_markdown(html: str) -> str:
    result = md(
        html,
        heading_style="ATX",
        bullets="-",
        strip=["script", "style"],
    )
    lines = result.split("\n")
    lines = [line.rstrip() for line in lines]
    result = "\n".join(lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip() + "\n"

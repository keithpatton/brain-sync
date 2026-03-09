from __future__ import annotations

import re

from brain_sync.sources import try_extract_confluence_page_id


def rewrite_links(markdown: str, canonical_id_to_path: dict[str, str]) -> str:
    """Rewrite Confluence URLs in markdown to local relative paths.

    Only rewrites links whose canonical_id exists in the map.
    All other links are left intact.
    """

    def _replace(match: re.Match) -> str:
        text = match.group(1)
        url = match.group(2)

        page_id = try_extract_confluence_page_id(url)
        if page_id is None:
            return match.group(0)

        cid = f"confluence:{page_id}"
        local_path = canonical_id_to_path.get(cid)
        if local_path is None:
            return match.group(0)

        return f"[{text}]({local_path})"

    # Match markdown links: [text](url)
    return re.sub(r"\[([^\]]*)\]\(([^)]+)\)", _replace, markdown)

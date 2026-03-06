from __future__ import annotations

import logging
from pathlib import Path

from brain_sync.context import CONTEXT_DIR, RELTYPE_FOLDER, RelType
from brain_sync.fileops import atomic_write_bytes
from brain_sync.state import load_relationships_for_primary

log = logging.getLogger(__name__)

INDEX_FILENAME = "_index.md"

# Section ordering and display names
_SECTIONS: list[tuple[str, str]] = [
    (RelType.LINK.value, "Linked Documents"),
    (RelType.CHILD.value, "Child Pages"),
    (RelType.ATTACHMENT.value, "Attachments"),
]


def generate_context_index(
    parent_canonical_id: str,
    manifest_dir: Path,
    root: Path,
) -> None:
    """Generate _sync-context/_index.md from the relationships table."""
    rels = load_relationships_for_primary(root, parent_canonical_id)

    if not rels:
        # Remove index if it exists and there are no relationships
        index_path = manifest_dir / CONTEXT_DIR / INDEX_FILENAME
        if index_path.exists():
            index_path.unlink()
        return

    # Group by relationship_type
    grouped: dict[str, list[tuple[str, str]]] = {}
    for rel in rels:
        rt = rel.relationship_type
        if rt not in grouped:
            grouped[rt] = []
        # local_path is relative from manifest_dir, make it relative from _sync-context/
        lp = rel.local_path
        if lp.startswith(f"{CONTEXT_DIR}/"):
            lp = lp[len(f"{CONTEXT_DIR}/"):]
        grouped[rt].append((lp, rel.canonical_id))

    # Sort entries alphabetically within each group
    for entries in grouped.values():
        entries.sort(key=lambda x: x[0])

    # Build markdown
    lines: list[str] = ["# Context Index", ""]
    lines.append(f"Primary: {parent_canonical_id}")
    lines.append("")

    for rel_type_value, section_title in _SECTIONS:
        entries = grouped.get(rel_type_value)
        if not entries:
            continue
        lines.append(f"## {section_title}")
        lines.append("")
        for path, cid in entries:
            lines.append(f"- {path} ({cid})")
        lines.append("")

    content = "\n".join(lines)
    index_path = manifest_dir / CONTEXT_DIR / INDEX_FILENAME
    index_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(index_path, content.encode("utf-8"))
    log.debug("Generated context index at %s", index_path)

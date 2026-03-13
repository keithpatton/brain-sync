"""Brain root factory for E2E tests."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from brain_sync.commands.init import init_brain


@dataclass
class BrainFixture:
    """A test brain with convenience accessors."""

    root: Path

    @property
    def db_path(self) -> Path:
        return self.root / ".sync-state.sqlite"

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def insights(self) -> Path:
        return self.root / "insights"


def create_brain(tmp_path: Path) -> BrainFixture:
    """Create a fresh brain using ``init_brain()``."""
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    return BrainFixture(root=root)


def seed_knowledge_tree(root: Path, structure: dict) -> None:
    """Create a folder/file hierarchy from a nested dict.

    Keys ending with ``/`` create directories (value is a nested dict).
    Other keys create files (value is the file content string).

    Example::

        seed_knowledge_tree(brain.root, {
            "knowledge/": {
                "project/": {
                    "overview.md": "# Overview\\nContent here.",
                    "decisions.md": "# Decisions\\nMore content.",
                },
            },
        })
    """
    for name, value in structure.items():
        path = root / name.rstrip("/")
        if isinstance(value, dict):
            path.mkdir(parents=True, exist_ok=True)
            seed_knowledge_tree(path, value)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(value), encoding="utf-8")


def seed_sources(root: Path, sources: list[dict]) -> None:
    """Insert source rows directly into the brain's SQLite database."""
    import sqlite3

    db = root / ".sync-state.sqlite"
    conn = sqlite3.connect(str(db))
    for src in sources:
        conn.execute(
            """INSERT OR REPLACE INTO sources
            (canonical_id, source_type, source_url, target_path)
            VALUES (?, ?, ?, ?)""",
            (
                src["canonical_id"],
                src.get("source_type", "confluence"),
                src.get("source_url", "https://acme.atlassian.net/wiki/spaces/ENG/pages/123"),
                src.get("target_path", ""),
            ),
        )
    conn.commit()
    conn.close()


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def create_brain_from_fixture(tmp_path: Path, fixture_name: str) -> BrainFixture:
    """Copy a canonical fixture to tmp_path and return a BrainFixture."""
    src = FIXTURE_DIR / fixture_name
    dest = tmp_path / "brain"
    shutil.copytree(src, dest)
    return BrainFixture(root=dest)

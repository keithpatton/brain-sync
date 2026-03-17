"""Brain root factory for E2E tests."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from brain_sync.application.init import init_brain
from brain_sync.brain.layout import INSIGHT_STATE_FILENAME, area_insights_dir


@dataclass(frozen=True)
class ManagedInsightsAccessor:
    """Path-like accessor for co-located managed insights."""

    root: Path
    knowledge_path: str = ""

    def _resolved_dir(self) -> Path:
        return area_insights_dir(self.root, self.knowledge_path)

    def __truediv__(self, key: str) -> Path | ManagedInsightsAccessor:
        if key in {"summary.md", INSIGHT_STATE_FILENAME, "journal"}:
            return self._resolved_dir() / key
        next_path = f"{self.knowledge_path}/{key}" if self.knowledge_path else key
        return ManagedInsightsAccessor(self.root, next_path)

    def __getattr__(self, name: str):
        return getattr(self._resolved_dir(), name)

    def __fspath__(self) -> str:
        return str(self._resolved_dir())

    def __str__(self) -> str:
        return str(self._resolved_dir())


@dataclass
class BrainFixture:
    """A test brain with convenience accessors."""

    root: Path

    @property
    def db_path(self) -> Path:
        from brain_sync.runtime import config as runtime_config

        return runtime_config.RUNTIME_DB_FILE

    @property
    def knowledge(self) -> Path:
        return self.root / "knowledge"

    @property
    def insights(self) -> ManagedInsightsAccessor:
        return ManagedInsightsAccessor(self.root)

    def insights_dir(self, knowledge_path: str = "") -> Path:
        return area_insights_dir(self.root, knowledge_path)


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
    """Register sources via manifests + sync_cache rows."""
    from brain_sync.brain.manifest import (
        SOURCE_MANIFEST_VERSION,
        SourceManifest,
        ensure_manifest_dir,
        write_source_manifest,
    )
    from brain_sync.runtime.repository import _connect

    ensure_manifest_dir(root)
    conn = _connect(root)
    for src in sources:
        cid = src["canonical_id"]
        url = src.get("source_url", "https://acme.atlassian.net/wiki/spaces/ENG/pages/123")
        stype = src.get("source_type", "confluence")
        tp = src.get("target_path", "")
        write_source_manifest(
            root,
            SourceManifest(
                version=SOURCE_MANIFEST_VERSION,
                canonical_id=cid,
                source_url=url,
                source_type=stype,
                materialized_path="",
                sync_attachments=False,
                target_path=tp,
            ),
        )
        conn.execute(
            "INSERT OR REPLACE INTO sync_cache (canonical_id) VALUES (?)",
            (cid,),
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

from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.query_index import invalidate_area_index, load_area_index

pytestmark = pytest.mark.unit


def test_invalidated_area_index_rebuilds_on_next_load(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    init_brain(root)
    (root / "knowledge" / "initiatives" / "alpha" / "notes.md").parent.mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "alpha" / "notes.md").write_text("alpha", encoding="utf-8")

    current = load_area_index(root)
    assert any(entry.path == "initiatives/alpha" for entry in current.entries)

    invalidate_area_index(current)
    (root / "knowledge" / "initiatives" / "beta" / "notes.md").parent.mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "beta" / "notes.md").write_text("beta", encoding="utf-8")

    rebuilt = load_area_index(root, current=current)

    assert rebuilt is not current
    assert any(entry.path == "initiatives/beta" for entry in rebuilt.entries)

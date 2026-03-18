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

    invalidate_area_index(root, current, knowledge_paths=["initiatives/alpha"], reason="test")
    (root / "knowledge" / "initiatives" / "beta" / "notes.md").parent.mkdir(parents=True)
    (root / "knowledge" / "initiatives" / "beta" / "notes.md").write_text("beta", encoding="utf-8")

    rebuilt = load_area_index(root, current=current)

    assert rebuilt is not current
    assert any(entry.path == "initiatives/beta" for entry in rebuilt.entries)


def test_area_index_rebuilds_when_portable_structure_changes(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    init_brain(root)
    alpha = root / "knowledge" / "initiatives" / "alpha"
    alpha.mkdir(parents=True)
    (alpha / "notes.md").write_text("alpha", encoding="utf-8")

    current = load_area_index(root)

    beta = root / "knowledge" / "initiatives" / "beta"
    beta.mkdir(parents=True)
    (beta / "notes.md").write_text("beta", encoding="utf-8")

    rebuilt = load_area_index(root, current=current)

    assert rebuilt is not current
    assert any(entry.path == "initiatives/beta" for entry in rebuilt.entries)


def test_area_index_rebuilds_when_portable_summary_changes(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    init_brain(root)
    area = root / "knowledge" / "initiatives" / "alpha"
    area.mkdir(parents=True)
    (area / "notes.md").write_text("alpha", encoding="utf-8")
    summary = area / ".brain-sync" / "insights" / "summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("first summary", encoding="utf-8")

    current = load_area_index(root)
    current_alpha = next(entry for entry in current.entries if entry.path == "initiatives/alpha")
    assert current_alpha.summary_body == "first summary"

    summary.write_text("updated summary", encoding="utf-8")

    rebuilt = load_area_index(root, current=current)
    rebuilt_alpha = next(entry for entry in rebuilt.entries if entry.path == "initiatives/alpha")

    assert rebuilt is not current
    assert rebuilt_alpha.summary_body == "updated summary"


def test_area_index_portable_freshness_holds_across_different_config_dirs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import brain_sync.runtime.config as runtime_config
    import brain_sync.runtime.repository as runtime_repository

    root = tmp_path / "brain"
    init_brain(root)
    area = root / "knowledge" / "initiatives" / "alpha"
    area.mkdir(parents=True)
    (area / "notes.md").write_text("alpha", encoding="utf-8")
    summary = area / ".brain-sync" / "insights" / "summary.md"
    summary.parent.mkdir(parents=True)
    summary.write_text("summary-a", encoding="utf-8")

    config_a = tmp_path / "config-a" / "db" / "brain-sync.sqlite"
    config_b = tmp_path / "config-b" / "db" / "brain-sync.sqlite"
    config_a.parent.mkdir(parents=True)
    config_b.parent.mkdir(parents=True)

    monkeypatch.setattr(runtime_config, "RUNTIME_DB_FILE", config_a)
    monkeypatch.setattr(runtime_repository, "RUNTIME_DB_FILE", config_a)
    runtime_repository.ensure_db(root)
    current = load_area_index(root)

    monkeypatch.setattr(runtime_config, "RUNTIME_DB_FILE", config_b)
    monkeypatch.setattr(runtime_repository, "RUNTIME_DB_FILE", config_b)
    runtime_repository.ensure_db(root)
    summary.write_text("summary-b", encoding="utf-8")

    monkeypatch.setattr(runtime_config, "RUNTIME_DB_FILE", config_a)
    monkeypatch.setattr(runtime_repository, "RUNTIME_DB_FILE", config_a)
    rebuilt = load_area_index(root, current=current)

    rebuilt_alpha = next(entry for entry in rebuilt.entries if entry.path == "initiatives/alpha")
    assert rebuilt is not current
    assert rebuilt_alpha.summary_body == "summary-b"

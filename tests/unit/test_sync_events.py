from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.insights import InsightState, load_insight_state, save_insight_state
from brain_sync.application.regen import classify_folder_change
from brain_sync.application.sources import add_source
from brain_sync.application.sync_events import apply_folder_move, handle_watcher_folder_change
from brain_sync.brain.manifest import read_source_manifest
from brain_sync.runtime.repository import (
    load_dirty_knowledge_paths,
    load_invalidation_token,
    load_operational_events,
    load_path_observations,
    save_path_observations,
)
from brain_sync.sync.watcher import FolderMove

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    init_brain(root)
    return root


def _write_area_doc(
    root: Path,
    knowledge_path: str,
    filename: str = "doc.md",
    content: str = "# Doc\n\nContent",
) -> Path:
    area_dir = root / "knowledge" / knowledge_path
    area_dir.mkdir(parents=True, exist_ok=True)
    path = area_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def test_handle_watcher_folder_change_enqueues_structure_only_change_for_walk_up(brain: Path) -> None:
    doc = _write_area_doc(brain, "area", "old-name.md")
    _, content_hash, structure_hash = classify_folder_change(brain, "area")
    save_insight_state(
        brain,
        InsightState(knowledge_path="area", content_hash=content_hash, structure_hash=structure_hash),
    )
    doc.rename(doc.with_name("new-name.md"))
    enqueued: list[str] = []

    outcome = handle_watcher_folder_change(brain, knowledge_path="area", enqueue=enqueued.append)

    assert outcome.action == "structure_enqueued"
    assert enqueued == ["area"]
    assert "area" in load_dirty_knowledge_paths(brain)
    assert load_invalidation_token(brain, "area_index").dirty is True
    assert load_insight_state(brain, "area") is not None

    events = load_operational_events(brain, event_type="watcher.structure_observed")
    assert len(events) == 1
    assert events[0].knowledge_path == "area"
    assert events[0].outcome == "enqueued"


def test_apply_folder_move_updates_runtime_state_and_emits_events(brain: Path) -> None:
    result = add_source(root=brain, url="test://doc/source-1", target_path="old-dir")
    old_dir = brain / "knowledge" / "old-dir"
    old_dir.mkdir(parents=True, exist_ok=True)
    save_path_observations(brain, {"old-dir": 123}, active_paths={"old-dir"})

    new_dir = brain / "knowledge" / "new-dir"
    shutil.move(str(old_dir), str(new_dir))

    apply_folder_move(brain, move=FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()))

    manifest = read_source_manifest(brain, result.canonical_id)
    assert manifest is not None
    assert manifest.target_path == "new-dir"
    assert load_path_observations(brain) == {"new-dir": 123}

    event_types = [event.event_type for event in load_operational_events(brain)]
    assert "watcher.move_observed" in event_types
    assert "watcher.move_applied" in event_types
    assert "query.index.invalidated" in event_types


def test_apply_folder_move_enqueues_old_parent_on_cross_branch_move(brain: Path) -> None:
    old_dir = brain / "knowledge" / "alpha" / "child"
    old_dir.mkdir(parents=True, exist_ok=True)
    new_dir = brain / "knowledge" / "beta" / "child"
    enqueued: list[str] = []

    shutil.move(str(old_dir), str(new_dir))

    apply_folder_move(
        brain,
        move=FolderMove(src=old_dir.resolve(), dest=new_dir.resolve()),
        enqueue=enqueued.append,
    )

    assert enqueued == ["beta/child", "alpha"]


def test_handle_watcher_folder_change_invalidates_core_context(brain: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_area_doc(brain, "_core", "notes.md")
    calls: list[str] = []

    monkeypatch.setattr("brain_sync.application.sync_events.invalidate_global_context_cache", lambda: calls.append("x"))

    handle_watcher_folder_change(brain, knowledge_path="_core", enqueue=lambda _path: None)

    assert calls == ["x"]

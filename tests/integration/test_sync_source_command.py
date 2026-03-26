from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.sources import add_source, sync_source
from brain_sync.brain.manifest import mark_manifest_missing
from brain_sync.runtime.repository import load_sync_progress
from brain_sync.sources.test import reset_test_adapter

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset_test_adapter() -> Iterator[None]:
    reset_test_adapter()
    yield
    reset_test_adapter()


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    return root


def test_sync_source_requests_selected_active_source_without_materializing(brain: Path) -> None:
    result = add_source(root=brain, url="test://doc/sync-requested", target_path="area")

    sync_result = sync_source(root=brain, sources=[result.canonical_id])

    assert sync_result.result_state == "requested"
    assert sync_result.requested_sources == (result.canonical_id,)
    assert sync_result.requested_all is False
    assert sync_result.message == "Priority sync scheduled for 1 active source(s)."
    progress = load_sync_progress(brain)[result.canonical_id]
    assert progress.last_checked_utc is None
    assert progress.next_check_utc is not None
    assert not list((brain / "knowledge" / "area").glob("*.md"))


def test_sync_source_with_no_selectors_requests_all_active_sources(brain: Path) -> None:
    first = add_source(root=brain, url="test://doc/sync-all-1", target_path="area")
    second = add_source(root=brain, url="test://doc/sync-all-2", target_path="area")

    sync_result = sync_source(root=brain, sources=[])

    assert sync_result.result_state == "requested"
    assert sync_result.requested_all is True
    assert sync_result.requested_sources == tuple(sorted((first.canonical_id, second.canonical_id)))
    progress = load_sync_progress(brain)
    assert progress[first.canonical_id].next_check_utc is not None
    assert progress[second.canonical_id].next_check_utc is not None


def test_sync_source_by_url_requests_selected_active_source(brain: Path) -> None:
    source_url = "test://doc/sync-url"
    result = add_source(root=brain, url=source_url, target_path="area")

    sync_result = sync_source(root=brain, sources=[source_url])

    assert sync_result.result_state == "requested"
    assert sync_result.requested_sources == (result.canonical_id,)


def test_sync_source_returns_not_found_for_inactive_selector(brain: Path) -> None:
    result = add_source(root=brain, url="test://doc/sync-missing", target_path="area")
    mark_manifest_missing(brain, result.canonical_id, "2026-03-26T00:00:00+00:00")

    sync_result = sync_source(root=brain, sources=[result.canonical_id])

    assert sync_result.result_state == "not_found"
    assert sync_result.unresolved_sources == (result.canonical_id,)
    assert "active registered sources" in (sync_result.message or "")


def test_sync_source_requests_selected_source_without_extra_runtime_side_effects(brain: Path) -> None:
    result = add_source(root=brain, url="test://doc/sync-rescan", target_path="area")

    sync_result = sync_source(root=brain, sources=[result.canonical_id])

    assert sync_result.result_state == "requested"
    assert sync_result.message == "Priority sync scheduled for 1 active source(s)."

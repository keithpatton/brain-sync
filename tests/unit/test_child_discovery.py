from __future__ import annotations

from pathlib import Path

import pytest

from brain_sync.application.child_discovery import compute_child_target_base, process_discovered_children
from brain_sync.application.init import init_brain
from brain_sync.application.source_state import load_state
from brain_sync.runtime.repository import (
    ChildDiscoveryRequest,
    load_child_discovery_request,
    load_operational_events,
    save_child_discovery_request,
)
from brain_sync.sync.pipeline import ChildDiscoveryResult

pytestmark = pytest.mark.unit


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    init_brain(root)
    return root


def test_compute_child_target_base_uses_explicit_child_path() -> None:
    base = compute_child_target_base(
        parent_target="area",
        parent_canonical_id="confluence:123",
        parent_source_url="https://example.com/pages/123",
        request=ChildDiscoveryRequest(canonical_id="confluence:123", fetch_children=True, child_path="children"),
    )

    assert base == "area/children"


def test_compute_child_target_base_defaults_to_slugged_parent_suffix() -> None:
    base = compute_child_target_base(
        parent_target="area",
        parent_canonical_id="confluence:123",
        parent_source_url="https://example.com/pages/Parent-Page",
        request=ChildDiscoveryRequest(canonical_id="confluence:123", fetch_children=True),
    )

    assert base == "area/c123-parent-page"


def test_process_discovered_children_registers_child_and_clears_request(brain: Path) -> None:
    save_child_discovery_request(brain, "confluence:123", fetch_children=True, child_path="children")
    request = load_child_discovery_request(brain, "confluence:123")
    state = load_state(brain)
    scheduled: list[str] = []

    updated = process_discovered_children(
        brain,
        parent_canonical_id="confluence:123",
        parent_source_url="https://example.com/pages/123",
        parent_target="area",
        sync_attachments=True,
        request=request,
        discovered_children=[
            ChildDiscoveryResult(
                canonical_id="ignored-by-registration",
                url="test://doc/child-1",
                title="Child 1",
            )
        ],
        schedule_immediate=scheduled.append,
        state=state,
    )

    assert scheduled
    child = updated.sources[scheduled[0]]
    assert child.target_path == "area/children"
    assert child.sync_attachments is True
    assert load_child_discovery_request(brain, "confluence:123") is None

    events = load_operational_events(brain, event_type="source.child_registered")
    assert len(events) == 1
    assert events[0].canonical_id == scheduled[0]
    assert events[0].knowledge_path == "area/children"
    assert events[0].outcome == "registered"


def test_process_discovered_children_skips_duplicates_and_clears_request(brain: Path) -> None:
    save_child_discovery_request(brain, "confluence:123", fetch_children=True, child_path="children")
    state = load_state(brain)
    scheduled: list[str] = []

    first = process_discovered_children(
        brain,
        parent_canonical_id="confluence:123",
        parent_source_url="https://example.com/pages/123",
        parent_target="area",
        sync_attachments=False,
        request=load_child_discovery_request(brain, "confluence:123"),
        discovered_children=[ChildDiscoveryResult(canonical_id="ignored", url="test://doc/child-dup", title="Child")],
        schedule_immediate=scheduled.append,
        state=state,
    )

    assert scheduled

    save_child_discovery_request(brain, "confluence:123", fetch_children=True, child_path="children")
    scheduled.clear()

    second = process_discovered_children(
        brain,
        parent_canonical_id="confluence:123",
        parent_source_url="https://example.com/pages/123",
        parent_target="area",
        sync_attachments=False,
        request=load_child_discovery_request(brain, "confluence:123"),
        discovered_children=[ChildDiscoveryResult(canonical_id="ignored", url="test://doc/child-dup", title="Child")],
        schedule_immediate=scheduled.append,
        state=first,
    )

    assert second.sources == first.sources
    assert scheduled == []
    assert load_child_discovery_request(brain, "confluence:123") is None

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.sources import add_source, finalize_missing, reconcile_sources
from brain_sync.brain.fileops import canonical_prefix
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import mark_manifest_missing, read_source_manifest, write_source_manifest
from brain_sync.brain.repository import BrainRepository
from brain_sync.runtime.operational_events import FIELD_LOCKED_EVENT_FIELDS, OperationalEventType
from brain_sync.runtime.repository import (
    OperationalEvent,
    acquire_source_lifecycle_lease,
    clear_source_lifecycle_lease,
    load_child_discovery_request,
    load_operational_events,
    load_source_lifecycle_runtime,
    load_sync_progress,
    record_source_missing_confirmation,
    save_child_discovery_request,
)

pytestmark = pytest.mark.integration

TEST_URL = "test://doc/finalize-123"
TEST_CID = "test:finalize-123"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    init_brain(root)
    return root


def _set_materialized_manifest(root: Path, knowledge_path: str) -> None:
    manifest = read_source_manifest(root, TEST_CID)
    assert manifest is not None
    manifest.knowledge_state = "materialized"
    manifest.knowledge_path = knowledge_path
    manifest.content_hash = "sha256:abc"
    manifest.remote_fingerprint = "rev-1"
    manifest.materialized_utc = "2026-03-20T00:00:00+00:00"
    write_source_manifest(root, manifest)


def _write_materialized_file(root: Path, knowledge_path: str) -> None:
    path = root / "knowledge" / knowledge_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(prepend_managed_header(TEST_CID, "# Test doc\n"), encoding="utf-8")


def _register_materialized_source(
    root: Path,
    *,
    knowledge_path: str = f"area/{canonical_prefix(TEST_CID)}doc.md",
    create_file: bool,
) -> None:
    add_source(root=root, url=TEST_URL, target_path="area", sync_attachments=True)
    _set_materialized_manifest(root, knowledge_path)
    if create_file:
        _write_materialized_file(root, knowledge_path)


def _event_details(event: OperationalEvent) -> dict[str, object]:
    return json.loads(event.details_json or "{}")


def _assert_locked_fields(event: OperationalEvent) -> None:
    required_fields = FIELD_LOCKED_EVENT_FIELDS[OperationalEventType(event.event_type)]
    details = _event_details(event)

    for field in required_fields:
        if field.startswith("details."):
            assert field.split(".", 1)[1] in details
            continue
        assert getattr(event, field) is not None


class TestSourceFinalization:
    def test_finalize_missing_finalizes_missing_source_in_one_call(self, brain: Path) -> None:
        _register_materialized_source(brain, create_file=False)

        reconcile_sources(root=brain)

        result = finalize_missing(brain, canonical_id=TEST_CID)

        assert result.result_state == "finalized"
        assert result.finalized is True
        assert read_source_manifest(brain, TEST_CID) is None
        assert load_source_lifecycle_runtime(brain, TEST_CID) is None
        assert TEST_CID not in load_sync_progress(brain)

        finalized_events = load_operational_events(brain, event_type="source.finalized")
        assert finalized_events
        assert finalized_events[-1].canonical_id == TEST_CID
        assert finalized_events[-1].outcome == "finalized"
        assert json.loads(finalized_events[-1].details_json or "{}") == {"revalidation_basis": "finalization_commit"}

    def test_finalize_missing_deletes_registration_and_source_owned_artifacts(self, brain: Path) -> None:
        _register_materialized_source(brain, create_file=False)
        attachment_dir = (
            brain / "knowledge" / "area" / ".brain-sync" / "attachments" / canonical_prefix(TEST_CID).rstrip("-")
        )
        attachment_dir.mkdir(parents=True, exist_ok=True)
        (attachment_dir / "asset.bin").write_bytes(b"asset")
        save_child_discovery_request(brain, TEST_CID, fetch_children=True, child_path="children")

        reconcile_sources(root=brain)

        result = finalize_missing(brain, canonical_id=TEST_CID)

        assert result.result_state == "finalized"
        assert result.finalized is True
        assert read_source_manifest(brain, TEST_CID) is None
        assert load_source_lifecycle_runtime(brain, TEST_CID) is None
        assert TEST_CID not in load_sync_progress(brain)
        assert load_child_discovery_request(brain, TEST_CID) is None
        assert not attachment_dir.exists()

    def test_finalize_missing_leaves_legacy_sync_context_leftovers_untouched(self, brain: Path) -> None:
        _register_materialized_source(brain, create_file=False)
        attachment_dir = (
            brain / "knowledge" / "area" / ".brain-sync" / "attachments" / canonical_prefix(TEST_CID).rstrip("-")
        )
        attachment_dir.mkdir(parents=True, exist_ok=True)
        (attachment_dir / "asset.bin").write_bytes(b"asset")
        legacy_dir = brain / "knowledge" / "area" / "_sync-context" / "attachments"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_file = legacy_dir / "other-source.bin"
        legacy_file.write_bytes(b"legacy")

        reconcile_sources(root=brain)

        result = finalize_missing(brain, canonical_id=TEST_CID)

        assert result.result_state == "finalized"
        assert read_source_manifest(brain, TEST_CID) is None
        assert not attachment_dir.exists()
        assert legacy_file.exists()
        assert legacy_file.read_bytes() == b"legacy"

    def test_finalize_missing_rediscovery_returns_not_missing_and_clears_runtime_coordination(
        self,
        brain: Path,
    ) -> None:
        _register_materialized_source(brain, create_file=True)
        mark_manifest_missing(brain, TEST_CID, "2026-03-20T00:00:00+00:00")
        record_source_missing_confirmation(brain, TEST_CID)

        result = finalize_missing(brain, canonical_id=TEST_CID)

        assert result.result_state == "not_missing"
        assert result.finalized is False
        assert result.knowledge_state == "stale"
        assert load_source_lifecycle_runtime(brain, TEST_CID) is None
        assert TEST_CID in load_sync_progress(brain)

        manifest = read_source_manifest(brain, TEST_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "stale"

        rediscovered_events = load_operational_events(brain, event_type="source.rediscovered")
        assert rediscovered_events
        assert _event_details(rediscovered_events[-1]) == {"revalidation_basis": "finalization_preflight"}
        _assert_locked_fields(rediscovered_events[-1])

        not_missing_events = load_operational_events(brain, event_type="source.finalization_not_missing")
        assert not_missing_events
        assert json.loads(not_missing_events[-1].details_json or "{}") == {"revalidation_basis": "rediscovered"}

    def test_finalize_missing_midflight_rediscovery_returns_not_missing_without_deleting_restored_file(
        self,
        brain: Path,
    ) -> None:
        _register_materialized_source(brain, create_file=False)
        reconcile_sources(root=brain)

        original_resolve = BrainRepository.resolve_source_file
        resolve_calls = 0

        def resolve_with_midflight_rediscovery(self: BrainRepository, manifest, *, identity_index=None):
            nonlocal resolve_calls
            resolve_calls += 1
            if resolve_calls == 2:
                _write_materialized_file(brain, manifest.knowledge_path)
            return original_resolve(self, manifest, identity_index=identity_index)

        with patch.object(
            BrainRepository,
            "resolve_source_file",
            autospec=True,
            side_effect=resolve_with_midflight_rediscovery,
        ):
            result = finalize_missing(brain, canonical_id=TEST_CID)

        assert result.result_state == "not_missing"
        assert result.finalized is False
        assert resolve_calls >= 2

        manifest = read_source_manifest(brain, TEST_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "stale"
        assert load_source_lifecycle_runtime(brain, TEST_CID) is None
        assert (brain / "knowledge" / manifest.knowledge_path).exists()

        rediscovered_events = load_operational_events(brain, event_type="source.rediscovered")
        assert rediscovered_events
        assert _event_details(rediscovered_events[-1]) == {"revalidation_basis": "finalization_commit"}
        _assert_locked_fields(rediscovered_events[-1])

    def test_finalize_missing_reports_lease_conflict(self, brain: Path) -> None:
        _register_materialized_source(brain, create_file=False)
        mark_manifest_missing(brain, TEST_CID, "2026-03-20T00:00:00+00:00")
        record_source_missing_confirmation(brain, TEST_CID)

        acquired, _ = acquire_source_lifecycle_lease(
            brain,
            TEST_CID,
            "other-owner",
            lease_expires_utc="2099-01-01T00:00:00+00:00",
        )
        assert acquired is True

        try:
            result = finalize_missing(brain, canonical_id=TEST_CID)
        finally:
            clear_source_lifecycle_lease(brain, TEST_CID, owner_id="other-owner")

        assert result.result_state == "lease_conflict"
        assert result.finalized is False
        assert result.lease_owner == "other-owner"

        conflict_events = load_operational_events(brain, event_type="source.finalization_lease_conflict")
        assert conflict_events
        assert json.loads(conflict_events[-1].details_json or "{}") == {"lease_owner": "other-owner"}

    def test_finalize_missing_returns_not_found_for_unknown_source(self, brain: Path) -> None:
        result = finalize_missing(brain, canonical_id="test:missing")

        assert result.result_state == "not_found"
        assert result.finalized is False
        assert result.error == "not_found"

        events = load_operational_events(brain, event_type="source.finalization_not_found")
        assert events
        assert events[-1].canonical_id == "test:missing"

    def test_finalize_missing_returns_not_missing_for_registered_non_missing_source(self, brain: Path) -> None:
        add_source(root=brain, url=TEST_URL, target_path="area")

        result = finalize_missing(brain, canonical_id=TEST_CID)

        assert result.result_state == "not_missing"
        assert result.finalized is False
        assert result.knowledge_state == "awaiting"
        assert load_source_lifecycle_runtime(brain, TEST_CID) is None

        events = load_operational_events(brain, event_type="source.finalization_not_missing")
        assert events
        assert events[-1].canonical_id == TEST_CID
        assert events[-1].outcome == "not_missing"

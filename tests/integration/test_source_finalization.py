from __future__ import annotations

import json
from pathlib import Path

import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.sources import add_source, finalize_missing, reconcile_sources
from brain_sync.brain.fileops import canonical_prefix
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import mark_manifest_missing, read_source_manifest, write_source_manifest
from brain_sync.runtime.repository import (
    acquire_source_lifecycle_lease,
    clear_source_lifecycle_lease,
    ensure_lifecycle_session,
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


class TestSourceFinalization:
    def test_finalize_missing_requires_a_fresh_confirmation_before_cleanup(self, brain: Path) -> None:
        _register_materialized_source(brain, create_file=False)

        reconcile_sources(root=brain)

        result = finalize_missing(brain, canonical_id=TEST_CID)

        assert result.result_state == "pending_confirmation"
        assert result.finalized is False
        assert result.knowledge_state == "missing"
        assert result.missing_confirmation_count == 2

        manifest = read_source_manifest(brain, TEST_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "missing"

        runtime_state = load_source_lifecycle_runtime(brain, TEST_CID)
        assert runtime_state is not None
        assert runtime_state.missing_confirmation_count == 2

        pending_events = load_operational_events(brain, event_type="source.finalization_pending_confirmation")
        assert pending_events
        assert pending_events[-1].canonical_id == TEST_CID
        assert json.loads(pending_events[-1].details_json or "{}") == {
            "missing_confirmation_count": 2,
            "revalidation_basis": "finalization_preflight",
        }

    def test_finalize_missing_deletes_registration_and_emits_terminal_event(self, brain: Path) -> None:
        _register_materialized_source(brain, create_file=False)
        attachment_dir = (
            brain / "knowledge" / "area" / ".brain-sync" / "attachments" / canonical_prefix(TEST_CID).rstrip("-")
        )
        attachment_dir.mkdir(parents=True, exist_ok=True)
        (attachment_dir / "asset.bin").write_bytes(b"asset")
        save_child_discovery_request(brain, TEST_CID, fetch_children=True, child_path="children")

        reconcile_sources(root=brain)
        reconcile_sources(root=brain)
        lifecycle_session_id = ensure_lifecycle_session(brain, owner_kind="cli")

        pending = finalize_missing(brain, canonical_id=TEST_CID, lifecycle_session_id=lifecycle_session_id)
        assert pending.result_state == "pending_confirmation"
        result = finalize_missing(brain, canonical_id=TEST_CID, lifecycle_session_id=lifecycle_session_id)

        assert result.result_state == "finalized"
        assert result.finalized is True
        assert read_source_manifest(brain, TEST_CID) is None
        assert load_source_lifecycle_runtime(brain, TEST_CID) is None
        assert TEST_CID not in load_sync_progress(brain)
        assert load_child_discovery_request(brain, TEST_CID) is None
        assert not attachment_dir.exists()

        finalized_events = load_operational_events(brain, event_type="source.finalized")
        assert finalized_events
        assert finalized_events[-1].canonical_id == TEST_CID
        assert finalized_events[-1].outcome == "finalized"
        details = json.loads(finalized_events[-1].details_json or "{}")
        assert details["revalidation_basis"] == "finalization_preflight"
        assert details["missing_confirmation_count"] >= 3

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
        reconcile_sources(root=brain)
        lifecycle_session_id = ensure_lifecycle_session(brain, owner_kind="cli")

        pending = finalize_missing(brain, canonical_id=TEST_CID, lifecycle_session_id=lifecycle_session_id)
        assert pending.result_state == "pending_confirmation"
        result = finalize_missing(brain, canonical_id=TEST_CID, lifecycle_session_id=lifecycle_session_id)

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
        assert json.loads(rediscovered_events[-1].details_json or "{}") == {
            "revalidation_basis": "finalization_preflight"
        }

        not_missing_events = load_operational_events(brain, event_type="source.finalization_not_missing")
        assert not_missing_events
        assert json.loads(not_missing_events[-1].details_json or "{}") == {"revalidation_basis": "rediscovered"}

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

"""Integration tests for missing-source lifecycle commands."""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from brain_sync.application.init import init_brain
from brain_sync.application.source_state import load_state
from brain_sync.application.sources import (
    add_source,
    list_sources,
    mark_source_missing,
    move_source,
    reconcile_sources,
    remove_source,
    update_source,
)
from brain_sync.brain.managed_markdown import prepend_managed_header
from brain_sync.brain.manifest import mark_manifest_missing, read_source_manifest, write_source_manifest
from brain_sync.brain.repository import BrainRepository
from brain_sync.runtime.operational_events import FIELD_LOCKED_EVENT_FIELDS, OperationalEventType
from brain_sync.runtime.repository import (
    OperationalEvent,
    acquire_source_lifecycle_lease,
    clear_source_lifecycle_lease,
    load_operational_events,
    load_source_lifecycle_runtime,
)
from brain_sync.sources.base import DiscoveredImage, SourceFetchResult, UpdateCheckResult, UpdateStatus
from brain_sync.sources.test import register_test_root, reset_test_adapter
from brain_sync.sync.attachments import StagedManagedArtifact
from brain_sync.sync.lifecycle import observe_missing_source, process_prepared_source
from brain_sync.sync.pipeline import PreparedSourceSync, SourceLifecycleLeaseConflictError, process_source

pytestmark = pytest.mark.integration

CONFLUENCE_URL = "https://example.atlassian.net/wiki/spaces/TEAM/pages/12345/Test-Page"
CONFLUENCE_CID = "confluence:12345"
OTHER_CONFLUENCE_URL = "https://example.atlassian.net/wiki/spaces/TEAM/pages/67890/Other-Page"
OTHER_CONFLUENCE_CID = "confluence:67890"
GDOC_URL = "https://docs.google.com/document/d/abc123/edit"
GDOC_CID = "gdoc:abc123"


@pytest.fixture
def brain(tmp_path: Path) -> Path:
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    return root


def _materialize_manifest(brain: Path) -> None:
    manifest = read_source_manifest(brain, CONFLUENCE_CID)
    assert manifest is not None
    manifest.knowledge_state = "materialized"
    manifest.knowledge_path = "area/c12345-test-page.md"
    manifest.content_hash = "sha256:abc"
    manifest.remote_fingerprint = "rev-1"
    manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
    write_source_manifest(brain, manifest)


def _script_test_source(root: Path, canonical_id: str, sequence: list[dict[str, str]]) -> None:
    adapter_dir = root / ".test-adapter"
    adapter_dir.mkdir(exist_ok=True)
    safe_name = canonical_id.replace(":", "_")
    (adapter_dir / f"{safe_name}.json").write_text(json.dumps({"sequence": sequence}), encoding="utf-8")


def _start_lease_attempt(
    root: Path,
    canonical_id: str,
    owner_id: str,
) -> tuple[dict[str, object], threading.Event, threading.Thread]:
    outcome: dict[str, object] = {}
    finished = threading.Event()

    def _runner() -> None:
        try:
            acquired, existing = acquire_source_lifecycle_lease(
                root,
                canonical_id,
                owner_id,
                lease_expires_utc="2099-01-01T00:00:00+00:00",
            )
            outcome["acquired"] = acquired
            outcome["existing"] = existing
        finally:
            finished.set()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    return outcome, finished, thread


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


class TestMissingSourceCommands:
    def test_remove_missing_source(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        state = load_state(brain)
        assert CONFLUENCE_CID not in state.sources

        result = remove_source(root=brain, source=CONFLUENCE_CID)
        assert result.canonical_id == CONFLUENCE_CID
        assert read_source_manifest(brain, CONFLUENCE_CID) is None

    def test_update_missing_source(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        result = update_source(root=brain, source=CONFLUENCE_CID, sync_attachments=True)
        assert result.canonical_id == CONFLUENCE_CID
        assert result.sync_attachments is True

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.sync_attachments is True

    def test_missing_source_not_in_list(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        sources = list_sources(root=brain)
        assert len(sources) == 1
        assert sources[0].canonical_id == CONFLUENCE_CID
        assert sources[0].knowledge_state == "missing"

    def test_missing_source_not_scheduled(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        mark_manifest_missing(brain, CONFLUENCE_CID, "2026-03-14T00:00:00")

        state = load_state(brain)
        assert CONFLUENCE_CID not in state.sources

    def test_remote_missing_reappears_through_existing_reconcile_lifecycle(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        materialized = brain / "knowledge" / "area" / "c12345-test-page.md"
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_text(prepend_managed_header(CONFLUENCE_CID, "Body"), encoding="utf-8")
        _materialize_manifest(brain)

        assert mark_source_missing(
            brain,
            canonical_id=CONFLUENCE_CID,
            missing_since_utc="2026-03-18T00:00:00+00:00",
            outcome="remote_missing",
        )

        result = reconcile_sources(brain)

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "stale"
        assert result.reappeared == [CONFLUENCE_CID]
        assert CONFLUENCE_CID in load_state(brain).sources

        rediscovered_events = load_operational_events(brain, event_type="source.rediscovered")
        assert rediscovered_events
        assert rediscovered_events[-1].canonical_id == CONFLUENCE_CID
        assert rediscovered_events[-1].outcome == "rediscovered"
        _assert_locked_fields(rediscovered_events[-1])

        updated_events = load_operational_events(brain, event_type="reconcile.path_updated")
        assert updated_events
        assert updated_events[-1].canonical_id == CONFLUENCE_CID
        assert updated_events[-1].outcome == "reappeared"
        assert _event_details(updated_events[-1]) == {"old_path": "area", "new_path": "area"}
        _assert_locked_fields(updated_events[-1])

    def test_root_backed_processing_refreshes_target_path_after_move(self, brain: Path) -> None:
        reset_test_adapter()
        try:
            add_source(root=brain, url="test://doc/move-race", target_path="old-area")
            stale_state = load_state(brain).sources["test:move-race"]

            register_test_root("test:move-race", brain)
            _script_test_source(
                brain,
                "test:move-race",
                [{"status": "CHANGED", "body": "# Moved\n\nFresh content.", "title": "Moved"}],
            )

            move_source(root=brain, source="test:move-race", to_path="new-area")

            async def _run() -> tuple[bool, list]:
                async with httpx.AsyncClient() as client:
                    return await process_source(
                        stale_state,
                        client,
                        root=brain,
                        lifecycle_owner_id="daemon-owner",
                    )

            changed, _children = asyncio.run(_run())

            assert changed is True
            assert not (brain / "knowledge" / "old-area" / "tmove-race.md").exists()
            new_files = list((brain / "knowledge" / "new-area").glob("*.md"))
            assert len(new_files) == 1

            manifest = read_source_manifest(brain, "test:move-race")
            assert manifest is not None
            assert manifest.target_path == "new-area"
            assert manifest.knowledge_path.startswith("new-area/")
        finally:
            reset_test_adapter()

    def test_observe_missing_source_blocks_last_moment_lease_takeover_until_commit(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")

        move_owner = "move-owner"
        thread: threading.Thread | None = None
        finished: threading.Event | None = None

        original_mark_source_missing = BrainRepository.mark_source_missing

        def _gated_mark_source_missing(self, canonical_id: str) -> None:
            nonlocal thread, finished
            _outcome, finished, thread = _start_lease_attempt(brain, canonical_id, move_owner)
            assert finished.wait(0.2) is False
            original_mark_source_missing(self, canonical_id)

        with patch("brain_sync.brain.repository.BrainRepository.mark_source_missing", new=_gated_mark_source_missing):
            observation = observe_missing_source(
                brain,
                canonical_id=CONFLUENCE_CID,
                outcome="missing",
            )

        assert observation is not None
        assert observation.knowledge_state == "missing"
        assert finished is not None and thread is not None
        assert finished.wait(2.0) is True
        thread.join(timeout=2.0)

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.knowledge_state == "missing"
        runtime_state = load_source_lifecycle_runtime(brain, CONFLUENCE_CID)
        assert runtime_state is not None
        assert runtime_state.missing_confirmation_count == 1
        clear_source_lifecycle_lease(brain, CONFLUENCE_CID, owner_id=move_owner)

    def test_observe_missing_source_emits_first_stage_proof_events(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")

        observation = observe_missing_source(
            brain,
            canonical_id=CONFLUENCE_CID,
            outcome="missing",
        )

        assert observation is not None
        assert observation.newly_missing is True
        assert observation.missing_confirmation_count == 1

        marked_events = load_operational_events(brain, event_type="source.missing_marked")
        confirmed_events = load_operational_events(brain, event_type="source.missing_confirmed")

        assert marked_events
        assert marked_events[-1].canonical_id == CONFLUENCE_CID
        assert marked_events[-1].knowledge_path == "area"
        assert marked_events[-1].outcome == "missing"
        assert _event_details(marked_events[-1]) == {"source_url": CONFLUENCE_URL}
        _assert_locked_fields(marked_events[-1])

        assert confirmed_events
        assert confirmed_events[-1].canonical_id == CONFLUENCE_CID
        assert confirmed_events[-1].knowledge_path == "area"
        assert confirmed_events[-1].outcome == "missing"
        assert _event_details(confirmed_events[-1]) == {"missing_confirmation_count": 1}
        _assert_locked_fields(confirmed_events[-1])

    def test_reconcile_path_repair_blocks_last_moment_lease_takeover_until_commit(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="old-area")
        moved = brain / "knowledge" / "new-area" / "c12345-test-page.md"
        moved.parent.mkdir(parents=True, exist_ok=True)
        moved.write_text(prepend_managed_header(CONFLUENCE_CID, "Body"), encoding="utf-8")
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "old-area/c12345-test-page.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        write_source_manifest(brain, manifest)

        move_owner = "move-owner"
        thread: threading.Thread | None = None
        finished: threading.Event | None = None
        original_sync_manifest = BrainRepository.sync_manifest_to_found_path

        def _gated_sync_manifest_to_found_path(self, canonical_id: str, found: Path) -> None:
            nonlocal thread, finished
            _outcome, finished, thread = _start_lease_attempt(brain, canonical_id, move_owner)
            assert finished.wait(0.2) is False
            original_sync_manifest(self, canonical_id, found)

        with patch(
            "brain_sync.brain.repository.BrainRepository.sync_manifest_to_found_path",
            new=_gated_sync_manifest_to_found_path,
        ):
            result = reconcile_sources(brain)

        assert result.updated
        assert result.updated[0].canonical_id == CONFLUENCE_CID
        assert finished is not None and thread is not None
        assert finished.wait(2.0) is True
        thread.join(timeout=2.0)

        refreshed = read_source_manifest(brain, CONFLUENCE_CID)
        assert refreshed is not None
        assert refreshed.target_path == "new-area"
        clear_source_lifecycle_lease(brain, CONFLUENCE_CID, owner_id=move_owner)

        updated_events = load_operational_events(brain, event_type="reconcile.path_updated")
        assert updated_events
        assert updated_events[-1].canonical_id == CONFLUENCE_CID
        assert updated_events[-1].outcome == "updated"
        assert _event_details(updated_events[-1]) == {
            "old_path": "old-area",
            "new_path": "new-area",
        }
        _assert_locked_fields(updated_events[-1])

    def test_root_backed_processing_does_not_write_staged_artifacts_after_lease_loss(self, brain: Path) -> None:
        add_source(root=brain, url=GDOC_URL, target_path="area", sync_attachments=True)
        source_state = load_state(brain).sources[GDOC_CID]
        adapter = MagicMock()
        adapter.capabilities.supports_version_check = True
        adapter.capabilities.supports_children = False
        adapter.capabilities.supports_attachments = True
        adapter.capabilities.supports_comments = False
        adapter.auth_provider.load_auth.return_value = MagicMock()
        adapter.check_for_update = AsyncMock(
            return_value=UpdateCheckResult(
                status=UpdateStatus.CHANGED,
                fingerprint="rev-2",
                title="Lease Race",
                adapter_state={"revisionId": "rev-2"},
            )
        )
        adapter.fetch = AsyncMock(
            return_value=SourceFetchResult(
                body_markdown="# Lease Race\n\nBody.",
                title="Lease Race",
                remote_fingerprint="rev-2",
                comments=[],
                inline_images=[
                    DiscoveredImage(
                        canonical_id="gdoc-image:abc123:kix.obj1",
                        download_url="https://example.com/image.png",
                        title="diagram.png",
                        mime_type="image/png",
                    )
                ],
                download_headers={"Authorization": "Bearer token"},
                attachment_parent_id=GDOC_CID,
            )
        )
        staged_local_path = ".brain-sync/attachments/gabc123/a1-diagram.png"
        move_owner = "move-owner"

        async def _stage_and_lose_lease(*_args, **_kwargs):
            clear_source_lifecycle_lease(brain, GDOC_CID, owner_id="daemon-owner")
            acquired, _existing = acquire_source_lifecycle_lease(
                brain,
                GDOC_CID,
                move_owner,
                lease_expires_utc="2099-01-01T00:00:00+00:00",
            )
            assert acquired is True
            return (
                {"gdoc-image:abc123:kix.obj1": staged_local_path},
                [StagedManagedArtifact(local_path=staged_local_path, data=b"PNG-DATA")],
            )

        try:
            with (
                patch("brain_sync.sync.pipeline.get_adapter", return_value=adapter),
                patch("brain_sync.sync.attachments.process_inline_images", side_effect=_stage_and_lose_lease),
            ):

                async def _run() -> tuple[bool, list]:
                    async with httpx.AsyncClient() as client:
                        return await process_source(
                            source_state,
                            client,
                            root=brain,
                            lifecycle_owner_id="daemon-owner",
                        )

                with pytest.raises(SourceLifecycleLeaseConflictError):
                    asyncio.run(_run())
        finally:
            clear_source_lifecycle_lease(brain, GDOC_CID, owner_id=move_owner)

        assert not list((brain / "knowledge" / "area").glob("*.md"))
        assert not (brain / "knowledge" / "area" / staged_local_path).exists()

    def test_move_source_prunes_empty_runtime_row_after_success(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")

        result = move_source(root=brain, source=CONFLUENCE_CID, to_path="new-area")

        assert result.result_state == "moved"
        assert load_source_lifecycle_runtime(brain, CONFLUENCE_CID) is None

    def test_move_source_only_moves_owned_artifacts(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area", sync_attachments=True)
        add_source(root=brain, url=OTHER_CONFLUENCE_URL, target_path="area")

        primary_file = brain / "knowledge" / "area" / "c12345-test-page.md"
        primary_file.parent.mkdir(parents=True, exist_ok=True)
        primary_file.write_text(prepend_managed_header(CONFLUENCE_CID, "# Primary"), encoding="utf-8")
        primary_attachment_dir = brain / "knowledge" / "area" / ".brain-sync" / "attachments" / "c12345"
        primary_attachment_dir.mkdir(parents=True, exist_ok=True)
        (primary_attachment_dir / "a789.bin").write_bytes(b"primary")

        sibling_file = brain / "knowledge" / "area" / "c67890-other-page.md"
        sibling_file.write_text(prepend_managed_header(OTHER_CONFLUENCE_CID, "# Secondary"), encoding="utf-8")
        user_note = brain / "knowledge" / "area" / "user-notes.md"
        user_note.write_text("# Notes", encoding="utf-8")

        primary_manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert primary_manifest is not None
        primary_manifest.knowledge_state = "materialized"
        primary_manifest.knowledge_path = "area/c12345-test-page.md"
        primary_manifest.content_hash = "sha256:abc"
        primary_manifest.remote_fingerprint = "rev-1"
        primary_manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        write_source_manifest(brain, primary_manifest)

        secondary_manifest = read_source_manifest(brain, OTHER_CONFLUENCE_CID)
        assert secondary_manifest is not None
        secondary_manifest.knowledge_state = "materialized"
        secondary_manifest.knowledge_path = "area/c67890-other-page.md"
        secondary_manifest.content_hash = "sha256:def"
        secondary_manifest.remote_fingerprint = "rev-2"
        secondary_manifest.materialized_utc = "2026-03-19T09:00:00+00:00"
        write_source_manifest(brain, secondary_manifest)

        result = move_source(root=brain, source=CONFLUENCE_CID, to_path="new-area")

        assert result.result_state == "moved"
        assert not primary_file.exists()
        assert (brain / "knowledge" / "new-area" / "c12345-test-page.md").exists()
        assert not primary_attachment_dir.exists()
        assert (brain / "knowledge" / "new-area" / ".brain-sync" / "attachments" / "c12345" / "a789.bin").exists()
        assert sibling_file.exists()
        assert user_note.exists()

        moved_manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert moved_manifest is not None
        assert moved_manifest.target_path == "new-area"
        unchanged_manifest = read_source_manifest(brain, OTHER_CONFLUENCE_CID)
        assert unchanged_manifest is not None
        assert unchanged_manifest.target_path == "area"

    def test_move_source_acquires_long_operation_lease_before_first_renewal(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area")
        materialized = brain / "knowledge" / "area" / "c12345-test-page.md"
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_text(prepend_managed_header(CONFLUENCE_CID, "Body"), encoding="utf-8")
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "area/c12345-test-page.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        write_source_manifest(brain, manifest)

        lease_probe: tuple[bool, object | None] | None = None

        original_move = BrainRepository.move_source_owned_markdown

        def _probe_lease_during_move(self, source_file: Path, dest_path: str):
            nonlocal lease_probe
            lease_probe = acquire_source_lifecycle_lease(
                brain,
                CONFLUENCE_CID,
                "other-owner",
                lease_expires_utc="2099-01-01T00:00:00+00:00",
            )
            return original_move(self, source_file, dest_path)

        try:
            with (
                patch("brain_sync.sync.lifecycle._lease_expiry", return_value="2000-01-01T00:00:00+00:00"),
                patch("brain_sync.sync.lifecycle._long_lease_expiry", return_value="2099-01-01T00:00:00+00:00"),
                patch(
                    "brain_sync.brain.repository.BrainRepository.move_source_owned_markdown",
                    new=_probe_lease_during_move,
                ),
            ):
                result = move_source(root=brain, source=CONFLUENCE_CID, to_path="new-area")
        finally:
            clear_source_lifecycle_lease(brain, CONFLUENCE_CID, owner_id="other-owner")

        assert result.result_state == "moved"
        assert lease_probe is not None
        acquired, existing = lease_probe
        assert acquired is False
        assert existing is not None

    def test_process_prepared_source_rolls_back_attachments_when_materialization_fails(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area", sync_attachments=True)
        source_state = load_state(brain).sources[CONFLUENCE_CID]
        legacy_dir = brain / "knowledge" / "area" / "_sync-context" / "attachments"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_file = legacy_dir / "a789-legacy.bin"
        legacy_file.write_bytes(b"legacy")
        staged_path = ".brain-sync/attachments/c12345/a790-new.bin"

        prepared = PreparedSourceSync(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
            filename="c12345-test-page.md",
            markdown="# Test",
            content_hash="sha256:new",
            remote_fingerprint="rev-2",
            checked_utc="2026-03-21T00:00:00+00:00",
            discovered_children=[],
            staged_managed_artifacts=(StagedManagedArtifact(local_path=staged_path, data=b"new"),),
        )

        with patch(
            "brain_sync.brain.repository.BrainRepository.materialize_markdown",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                process_prepared_source(brain, source_state, prepared)

        assert legacy_file.exists()
        assert legacy_file.read_bytes() == b"legacy"
        assert not (brain / "knowledge" / "area" / staged_path).exists()

    def test_process_prepared_source_rolls_back_markdown_when_manifest_update_fails(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area", sync_attachments=True)
        source_state = load_state(brain).sources[CONFLUENCE_CID]
        legacy_dir = brain / "knowledge" / "area" / "_sync-context" / "attachments"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_file = legacy_dir / "a789-legacy.bin"
        legacy_file.write_bytes(b"legacy")
        staged_path = ".brain-sync/attachments/c12345/a790-new.bin"
        markdown_path = brain / "knowledge" / "area" / "c12345-test-page.md"

        prepared = PreparedSourceSync(
            canonical_id=CONFLUENCE_CID,
            source_url=CONFLUENCE_URL,
            source_type="confluence",
            target_path="area",
            filename="c12345-test-page.md",
            markdown="# Test",
            content_hash="sha256:new",
            remote_fingerprint="rev-2",
            checked_utc="2026-03-21T00:00:00+00:00",
            discovered_children=[],
            staged_managed_artifacts=(StagedManagedArtifact(local_path=staged_path, data=b"new"),),
        )

        with patch("brain_sync.brain.repository.update_manifest_materialization", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError, match="boom"):
                process_prepared_source(brain, source_state, prepared)

        assert not markdown_path.exists()
        assert legacy_file.exists()
        assert legacy_file.read_bytes() == b"legacy"
        assert not (brain / "knowledge" / "area" / staged_path).exists()

    def test_move_source_returns_lease_conflict_after_mid_operation_lease_loss(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area", sync_attachments=True)
        materialized = brain / "knowledge" / "area" / "c12345-test-page.md"
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_text(prepend_managed_header(CONFLUENCE_CID, "Body"), encoding="utf-8")
        attachment_dir = brain / "knowledge" / "area" / ".brain-sync" / "attachments" / "c12345"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        (attachment_dir / "a789.bin").write_bytes(b"payload")

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "area/c12345-test-page.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        write_source_manifest(brain, manifest)

        original_move = BrainRepository.move_source_owned_markdown

        def _lose_lease_after_real_move(self, source_file: Path, dest_path: str):
            rollback = original_move(self, source_file, dest_path)
            clear_source_lifecycle_lease(brain, CONFLUENCE_CID)
            acquired, _existing = acquire_source_lifecycle_lease(
                brain,
                CONFLUENCE_CID,
                "other-owner",
                lease_expires_utc="2099-01-01T00:00:00+00:00",
            )
            assert acquired is True
            return rollback

        try:
            with patch(
                "brain_sync.brain.repository.BrainRepository.move_source_owned_markdown",
                new=_lose_lease_after_real_move,
            ):
                result = move_source(root=brain, source=CONFLUENCE_CID, to_path="new-area")
        finally:
            clear_source_lifecycle_lease(brain, CONFLUENCE_CID, owner_id="other-owner")

        assert result.result_state == "lease_conflict"
        assert result.lease_owner == "other-owner"
        assert materialized.exists()
        assert not (brain / "knowledge" / "new-area" / "c12345-test-page.md").exists()
        assert attachment_dir.exists()
        assert not (brain / "knowledge" / "new-area" / ".brain-sync" / "attachments" / "c12345").exists()
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.target_path == "area"

    def test_move_source_rolls_back_owned_moves_when_manifest_update_fails(self, brain: Path) -> None:
        add_source(root=brain, url=CONFLUENCE_URL, target_path="area", sync_attachments=True)
        materialized = brain / "knowledge" / "area" / "c12345-test-page.md"
        materialized.parent.mkdir(parents=True, exist_ok=True)
        materialized.write_text(prepend_managed_header(CONFLUENCE_CID, "Body"), encoding="utf-8")
        attachment_dir = brain / "knowledge" / "area" / ".brain-sync" / "attachments" / "c12345"
        attachment_dir.mkdir(parents=True, exist_ok=True)
        (attachment_dir / "a789.bin").write_bytes(b"payload")
        user_note = brain / "knowledge" / "area" / "user-notes.md"
        user_note.write_text("# Notes", encoding="utf-8")

        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        manifest.knowledge_state = "materialized"
        manifest.knowledge_path = "area/c12345-test-page.md"
        manifest.content_hash = "sha256:abc"
        manifest.remote_fingerprint = "rev-1"
        manifest.materialized_utc = "2026-03-19T08:00:00+00:00"
        write_source_manifest(brain, manifest)

        with patch(
            "brain_sync.brain.repository.BrainRepository.sync_manifest_to_found_path",
            side_effect=RuntimeError("boom"),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                move_source(root=brain, source=CONFLUENCE_CID, to_path="new-area")

        assert materialized.exists()
        assert not (brain / "knowledge" / "new-area" / "c12345-test-page.md").exists()
        assert attachment_dir.exists()
        assert not (brain / "knowledge" / "new-area" / ".brain-sync" / "attachments" / "c12345").exists()
        assert user_note.exists()
        manifest = read_source_manifest(brain, CONFLUENCE_CID)
        assert manifest is not None
        assert manifest.target_path == "area"

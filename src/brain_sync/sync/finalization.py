"""Explicit missing-source finalization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brain_sync.brain.manifest import read_source_manifest
from brain_sync.brain.repository import BrainRepository
from brain_sync.runtime.operational_events import OperationalEventType
from brain_sync.runtime.repository import (
    acquire_source_lifecycle_lease,
    clear_child_discovery_request,
    clear_source_lifecycle_lease,
    delete_source,
    delete_source_lifecycle_runtime,
    ensure_source_polling,
    record_brain_operational_event,
)
from brain_sync.sync.lifecycle_policy import finalization_eligibility


@dataclass(frozen=True)
class FinalizationResult:
    canonical_id: str
    result_state: str
    finalized: bool
    knowledge_state: str | None = None
    message: str | None = None
    error: str | None = None
    lease_owner: str | None = None


def _owner_id() -> str:
    import os
    import uuid

    return f"finalize:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _lease_expiry() -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(seconds=30)).isoformat()


def _return_rediscovered_not_missing(
    root: Path,
    *,
    repository: BrainRepository,
    canonical_id: str,
    manifest_target_path: str,
    found_path: Path,
    revalidation_basis: str,
) -> FinalizationResult:
    repository.sync_manifest_to_found_path(canonical_id, found_path)
    delete_source_lifecycle_runtime(root, canonical_id)
    ensure_source_polling(root, canonical_id)
    refreshed = read_source_manifest(root, canonical_id)
    knowledge_path = refreshed.target_path if refreshed is not None else manifest_target_path
    record_brain_operational_event(
        root,
        event_type=OperationalEventType.SOURCE_REDISCOVERED,
        canonical_id=canonical_id,
        knowledge_path=knowledge_path,
        outcome="rediscovered",
        details={"revalidation_basis": revalidation_basis},
    )
    record_brain_operational_event(
        root,
        event_type=OperationalEventType.SOURCE_FINALIZATION_NOT_MISSING,
        canonical_id=canonical_id,
        knowledge_path=knowledge_path,
        outcome="not_missing",
        details={"revalidation_basis": "rediscovered"},
    )
    return FinalizationResult(
        canonical_id=canonical_id,
        result_state="not_missing",
        finalized=False,
        knowledge_state=refreshed.knowledge_state if refreshed is not None else "stale",
    )


def finalize_missing(
    root: Path,
    *,
    canonical_id: str,
    lifecycle_session_id: str | None = None,
) -> FinalizationResult:
    repository = BrainRepository(root)
    del lifecycle_session_id
    owner_id = _owner_id()
    acquired, existing = acquire_source_lifecycle_lease(
        root,
        canonical_id,
        owner_id,
        lease_expires_utc=_lease_expiry(),
    )
    if not acquired:
        record_brain_operational_event(
            root,
            event_type=OperationalEventType.SOURCE_FINALIZATION_LEASE_CONFLICT,
            canonical_id=canonical_id,
            outcome="lease_conflict",
            details={"lease_owner": existing.lease_owner if existing is not None else None},
        )
        return FinalizationResult(
            canonical_id=canonical_id,
            result_state="lease_conflict",
            finalized=False,
            message=f"Source lifecycle lease is already held for {canonical_id}",
            lease_owner=existing.lease_owner if existing is not None else None,
        )

    try:
        manifest = read_source_manifest(root, canonical_id)
        if manifest is None:
            delete_source_lifecycle_runtime(root, canonical_id)
            record_brain_operational_event(
                root,
                event_type=OperationalEventType.SOURCE_FINALIZATION_NOT_FOUND,
                canonical_id=canonical_id,
                outcome="not_found",
            )
            return FinalizationResult(
                canonical_id=canonical_id,
                result_state="not_found",
                finalized=False,
                error="not_found",
            )

        resolved = repository.resolve_source_file(manifest)
        if resolved.path is not None:
            return _return_rediscovered_not_missing(
                root,
                repository=repository,
                canonical_id=canonical_id,
                manifest_target_path=manifest.target_path,
                found_path=resolved.path,
                revalidation_basis="finalization_preflight",
            )

        eligibility = finalization_eligibility(
            manifest_exists=True,
            knowledge_state=manifest.knowledge_state,
            conflicting_lease=False,
        )
        if eligibility.reason == "not_missing":
            delete_source_lifecycle_runtime(root, canonical_id)
            record_brain_operational_event(
                root,
                event_type=OperationalEventType.SOURCE_FINALIZATION_NOT_MISSING,
                canonical_id=canonical_id,
                knowledge_path=manifest.target_path,
                outcome="not_missing",
            )
            return FinalizationResult(
                canonical_id=canonical_id,
                result_state="not_missing",
                finalized=False,
                knowledge_state=manifest.knowledge_state,
            )

        commit_resolution = repository.resolve_source_file(manifest)
        if commit_resolution.path is not None:
            return _return_rediscovered_not_missing(
                root,
                repository=repository,
                canonical_id=canonical_id,
                manifest_target_path=manifest.target_path,
                found_path=commit_resolution.path,
                revalidation_basis="finalization_commit",
            )

        repository.remove_source_managed_artifacts(manifest.target_path, canonical_id)
        delete_source(root, canonical_id)
        delete_source_lifecycle_runtime(root, canonical_id)
        clear_child_discovery_request(root, canonical_id)
        repository.delete_source_registration(canonical_id)
        record_brain_operational_event(
            root,
            event_type=OperationalEventType.SOURCE_FINALIZED,
            canonical_id=canonical_id,
            knowledge_path=manifest.target_path,
            outcome="finalized",
            details={
                "revalidation_basis": "finalization_commit",
            },
        )
        return FinalizationResult(
            canonical_id=canonical_id,
            result_state="finalized",
            finalized=True,
        )
    finally:
        clear_source_lifecycle_lease(root, canonical_id, owner_id=owner_id)

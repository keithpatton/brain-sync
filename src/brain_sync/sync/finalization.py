"""Explicit missing-source finalization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from brain_sync.brain.manifest import read_source_manifest
from brain_sync.brain.repository import BrainRepository
from brain_sync.runtime.repository import (
    acquire_source_lifecycle_lease,
    clear_child_discovery_request,
    clear_source_lifecycle_lease,
    delete_source,
    delete_source_lifecycle_runtime,
    ensure_source_polling,
    load_source_lifecycle_runtime,
    record_operational_event,
    record_source_missing_confirmation,
)
from brain_sync.sync.lifecycle_policy import finalization_eligibility


@dataclass(frozen=True)
class FinalizationResult:
    canonical_id: str
    result_state: str
    finalized: bool
    knowledge_state: str | None = None
    missing_confirmation_count: int | None = None
    eligible: bool | None = None
    message: str | None = None
    error: str | None = None


def _owner_id() -> str:
    import os
    import uuid

    return f"finalize:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _lease_expiry() -> str:
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(seconds=30)).isoformat()


def finalize_missing(root: Path, *, canonical_id: str) -> FinalizationResult:
    repository = BrainRepository(root)
    owner_id = _owner_id()
    acquired, existing = acquire_source_lifecycle_lease(
        root,
        canonical_id,
        owner_id,
        lease_expires_utc=_lease_expiry(),
    )
    if not acquired:
        record_operational_event(
            event_type="source.finalization_lease_conflict",
            canonical_id=canonical_id,
            outcome="lease_conflict",
            details={"lease_owner": existing.lease_owner if existing is not None else None},
        )
        return FinalizationResult(
            canonical_id=canonical_id,
            result_state="lease_conflict",
            finalized=False,
            eligible=False,
            message=f"Source lifecycle lease is already held for {canonical_id}",
        )

    try:
        manifest = read_source_manifest(root, canonical_id)
        if manifest is None:
            delete_source_lifecycle_runtime(root, canonical_id)
            record_operational_event(
                event_type="source.finalization_not_found",
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
            repository.sync_manifest_to_found_path(canonical_id, resolved.path)
            delete_source_lifecycle_runtime(root, canonical_id)
            ensure_source_polling(root, canonical_id)
            refreshed = read_source_manifest(root, canonical_id)
            record_operational_event(
                event_type="source.rediscovered",
                canonical_id=canonical_id,
                knowledge_path=refreshed.target_path if refreshed is not None else manifest.target_path,
                outcome="rediscovered",
                details={"revalidation_basis": "finalization_preflight"},
            )
            record_operational_event(
                event_type="source.finalization_not_missing",
                canonical_id=canonical_id,
                knowledge_path=refreshed.target_path if refreshed is not None else manifest.target_path,
                outcome="not_missing",
                details={"revalidation_basis": "rediscovered"},
            )
            return FinalizationResult(
                canonical_id=canonical_id,
                result_state="not_missing",
                finalized=False,
                knowledge_state=refreshed.knowledge_state if refreshed is not None else "stale",
            )

        runtime_state = load_source_lifecycle_runtime(root, canonical_id)
        eligibility = finalization_eligibility(
            manifest_exists=True,
            knowledge_state=manifest.knowledge_state,
            has_runtime_row=runtime_state is not None,
            missing_confirmation_count=runtime_state.missing_confirmation_count if runtime_state is not None else 0,
            conflicting_lease=False,
        )
        if eligibility.reason == "not_missing":
            delete_source_lifecycle_runtime(root, canonical_id)
            record_operational_event(
                event_type="source.finalization_not_missing",
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

        refreshed_runtime = record_source_missing_confirmation(root, canonical_id)
        if runtime_state is None or runtime_state.missing_confirmation_count < 2:
            record_operational_event(
                event_type="source.finalization_pending_confirmation",
                canonical_id=canonical_id,
                knowledge_path=manifest.target_path,
                outcome="pending_confirmation",
                details={
                    "missing_confirmation_count": refreshed_runtime.missing_confirmation_count,
                    "revalidation_basis": "finalization_preflight",
                },
            )
            return FinalizationResult(
                canonical_id=canonical_id,
                result_state="pending_confirmation",
                finalized=False,
                knowledge_state=manifest.knowledge_state,
                missing_confirmation_count=refreshed_runtime.missing_confirmation_count,
                eligible=False,
            )

        repository.remove_source_owned_files(manifest.target_path, canonical_id)
        delete_source(root, canonical_id)
        delete_source_lifecycle_runtime(root, canonical_id)
        clear_child_discovery_request(root, canonical_id)
        repository.delete_source_registration(canonical_id)
        record_operational_event(
            event_type="source.finalized",
            canonical_id=canonical_id,
            knowledge_path=manifest.target_path,
            outcome="finalized",
            details={
                "missing_confirmation_count": refreshed_runtime.missing_confirmation_count,
                "revalidation_basis": "finalization_preflight",
            },
        )
        return FinalizationResult(
            canonical_id=canonical_id,
            result_state="finalized",
            finalized=True,
            eligible=True,
        )
    finally:
        clear_source_lifecycle_lease(root, canonical_id, owner_id=owner_id)

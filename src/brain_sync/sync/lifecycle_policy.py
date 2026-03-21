"""Pure source lifecycle policy.

This module intentionally stays IO-free so lifecycle transition tests can pin
the reducer semantics without touching the filesystem or runtime DB.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FinalizationEligibility:
    eligible: bool
    reason: str


def stale_blocks_unchanged_fast_path(*, knowledge_state: str) -> bool:
    return knowledge_state == "stale"


def can_use_unchanged_fast_path(*, knowledge_state: str, has_existing_file: bool, context_missing: bool) -> bool:
    return knowledge_state == "materialized" and has_existing_file and not context_missing


def finalization_eligibility(
    *,
    manifest_exists: bool,
    knowledge_state: str | None,
    conflicting_lease: bool,
) -> FinalizationEligibility:
    if not manifest_exists:
        return FinalizationEligibility(False, "not_found")
    if knowledge_state != "missing":
        return FinalizationEligibility(False, "not_missing")
    if conflicting_lease:
        return FinalizationEligibility(False, "lease_conflict")
    return FinalizationEligibility(True, "finalized")

# Plan source-lifecycle-hardening v2.5 Implementation Notes

2026-03-22T13:08:00+13:00
Change: Post-review compatibility docs were narrowed to the supported user-facing upgrade path `0.5.0 / 1.0 / v23 -> 0.7.0.0 / 1.2 / v29`, and the migration guide was renamed to `docs/migrations/v0.5.0-v0.7.0.md`.
Reason: Repository policy now treats Brain Format `1.2` as the only supported steady-state portable format while still documenting the guided `0.5.0` upgrade path; removing `0.6.0 / 1.1` as a supported row avoids overstating compatibility expectations that are no longer part of the intended release contract.
Status: Clarified.

2026-03-22T12:32:00+13:00
Change: Approved plan implementation is materially complete in the current working tree after plan-trail commit `0a0b8b1` (`docs(plans): add source lifecycle hardening trail`).
Reason: The approved finalization-focused scope has been realized across code, tests, and owning docs without reopening broader lifecycle-hardening behavior; focused validation passed against the updated contract and no known blocking deviations remain.
Status: Completed.

2026-03-22T12:28:00+13:00
Change: Runtime schema `v29` keeps `local_missing_first_observed_utc` and `local_missing_last_confirmed_utc` only as machine-local missing-observation history, while removing `missing_confirmation_count` and `last_missing_confirmation_session_id` from the shipped schema.
Reason: The approval attestation required an explicit end-state for these fields. Code, migration tests, and owning runtime/versioning/sync docs now state that the retained timestamps are diagnostic and rediscovery-adjacent context only; they are not part of explicit finalization authorization, which now depends solely on manifest state, lease ownership, and command-time revalidation.
Status: Clarified.

# PLAN_source-lifecycle-hardening-v2: Source Lifecycle Hardening V2

## Status

Planning artifact only. This document defines a second implementation round for
source lifecycle hardening after review of commit `3cc93ec` (`Harden source
lifecycle ownership and finalization`).

This stage does **not** approve implementation. It records the findings,
architectural tightening targets, sequencing, and acceptance gates for later
review and approval.

## Objective

Close the concrete hardening gaps left after the first source lifecycle
implementation so the subsystem behaves like solid production-grade lifecycle
infrastructure under:

- process restart
- daemon and CLI/MCP overlap
- destructive lifecycle actions
- source-level serialization
- user-facing conflict handling
- restart/overlap observability and testing

This round is a hardening-and-closure pass, not a redesign. It should preserve
the approved lifecycle direction from the prior plan while tightening the
remaining correctness, authority, and coverage gaps.

## Relationship To Prior Plan

This plan is derived from the completed first-round implementation authorized by:

- `docs/plans/plan_source-lifecycle-hardening_9_approved_2026-03-20T17-41-44.md`

and informed by:

- `docs/plans/plan_source-lifecycle-hardening_9_notes.md`
- commit `3cc93ec`

The prior approved plan remains authoritative for the first-round lifecycle
architecture. This v2 plan exists to address the concrete defects, residual
architectural weaknesses, and missing fortress coverage identified in the
post-implementation hardening review.

## Authoritative Inputs

The implementation and review must treat these documents as the primary
constraints:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`
- `docs/plans/plan_source-lifecycle-hardening_9_approved_2026-03-20T17-41-44.md`
- `docs/plans/plan_source-lifecycle-hardening_9_notes.md`

The implementation and review must also align with the current lifecycle
surface and the affected test seams:

- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/finalization.py`
- `src/brain_sync/sync/lifecycle_policy.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/application/doctor.py`
- `tests/unit/test_architecture_boundaries.py`
- `tests/integration/test_manifest_read_path.py`
- `tests/integration/test_source_finalization.py`
- `tests/system/test_finalize_missing_cli.py`
- `tests/mcp/test_finalize_missing_mcp.py`
- `tests/e2e/test_db_contention.py`

## Findings Driving This Plan

This second-round plan is required because the first-round implementation left
the following material hardening gaps:

1. Persisted `missing_confirmation_count >= 2` can still be reused by a new
   process to finalize immediately without a fresh current-process confirmation.
2. Source lifecycle serialization is not yet enforced for all
   lifecycle-affecting writes. In particular, explicit remove can proceed while
   another lifecycle owner holds the source lease.
3. `move` lease conflicts surface as raw exceptions at CLI/MCP boundaries
   instead of a controlled lifecycle result.
4. Non-missing lease-driven operations can leave behind empty
   `source_lifecycle_runtime` rows, which violates the intended runtime-row
   contract and muddies restart reasoning.
5. Canonical-ID validation remains heuristic rather than schema-backed and
   shared.
6. Restart, overlap, and cross-process coverage remain thinner than the prior
   approved plan intended, especially where `operational_events` should provide
   proof of ordering and terminal outcome.

## Product Decisions Confirmed For This Plan

The following decisions are confirmed and should be treated as settled design
input unless a later review artifact identifies a material conflict.

### 1. This is a hardening closure round, not a feature redesign

The sync-owned lifecycle architecture from the prior approved plan stays in
place. This plan should tighten and complete it rather than reopen the broad
portable/runtime split, move/finalization product model, or admin-surface
direction.

### 2. Lifecycle serialization becomes a product rule for lifecycle-affecting writes

Per-source lifecycle serialization should no longer remain effectively limited
to move/finalization. The implementation revision derived from this artifact
must make the rule explicit for destructive or lifecycle-significant writes on
one `canonical_id`.

### 3. Current-process confirmation must be explicit in finalization eligibility

Persisted runtime rows remain machine-local history only. A carried-forward
`missing_confirmation_count` from an earlier process must not by itself
authorize destructive finalization in a later process.

### 4. User-facing conflict handling must be deterministic

Normal lifecycle overlap is a supported operating condition. CLI and MCP
surfaces must not leak raw exceptions for expected lease conflicts or related
contention outcomes.

### 5. Empty lifecycle runtime rows are contract violations, not cosmetic debt

`source_lifecycle_runtime` rows must exist only when the source is missing,
under explicit finalization coordination, or actively leased / waiting on a
lifecycle lease. Successful completion of a non-missing lifecycle action should
not leave an empty row behind.

### 6. Operational events stay non-authoritative but must be strong enough for proof

`operational_events` remains append-only, non-authoritative, and non-replay.
However, overlap and restart tests in this plan should use it to prove ordering
and terminal outcomes rather than relying only on logs or inferred end state.

## Problem Statement

The first-round implementation materially improved lifecycle ownership, but it
does not yet feel fully sealed as high-grade production infrastructure because
the remaining defects sit in the most failure-sensitive parts of the system:

- restart-era destructive eligibility
- overlap between explicit commands and daemon-owned work
- transport behavior under contention
- runtime-row hygiene after lease-owned operations
- exactness of lifecycle input validation
- test proof for overlap and restart behavior

This means the subsystem is directionally correct but still vulnerable in the
precise places where users are least tolerant of ambiguity:

- destructive cleanup after restart
- daemon/CLI competition
- retries and re-entry after interruption
- machine-local runtime history being mistaken for current authority

## Scope

In scope for the implementation stage:

- tightening process-boundary rules for explicit finalization eligibility
- broadening lifecycle serialization to the remaining lifecycle-affecting write
  paths that materially require it
- hardening user-facing move conflict behavior for CLI and MCP
- enforcing runtime-row cleanup/hygiene after lease-driven operations
- replacing heuristic canonical-ID targeting checks with a shared validator
- updating rules, runtime docs, architecture docs, and README text where the
  product rule becomes sharper
- expanding fortress coverage for restart, overlap, cross-process, and
  event-proven lifecycle outcomes

## Non-goals

- no new portable source manifest version unless later review proves that one
  of these fixes changes the portable contract
- no broad redesign of provider adapters
- no broad event-catalog refactor outside the bounded lifecycle/finalization
  slice needed for proof and observability
- no expansion into unrelated CLI/MCP/product-surface work
- no broad rewrite of daemon scheduling outside lifecycle hardening needs

## Workstreams

### Workstream 1: Restart-Safe Finalization Eligibility

Goals:

- make current-process confirmation a first-class part of destructive
  finalization eligibility
- ensure carried-forward runtime rows from prior processes cannot authorize
  finalization without fresh current-process confirmation
- update runtime schema/docs/rules if an explicit epoch, owner, or confirmation
  freshness field is required

### Workstream 2: Full Lifecycle Serialization For Critical Writes

Goals:

- close the remaining lifecycle-affecting write paths that can still bypass the
  per-source lifecycle lease
- harden explicit remove against in-flight lifecycle work
- define how watcher/reconcile lifecycle writes participate in or respect the
  serialization rule

### Workstream 3: Transport And Input Contract Hardening

Goals:

- replace raw move conflict exceptions with deterministic CLI/MCP-visible
  conflict handling
- keep move/finalization user-facing contracts exact and testable
- replace heuristic canonical-ID admission checks with one shared validator

### Workstream 4: Runtime Row Hygiene And Event Guarantees

Goals:

- prevent empty `source_lifecycle_runtime` rows from persisting after
  successful non-missing operations
- sharpen lifecycle/finalization event guarantees enough for restart/overlap
  testing
- keep `operational_events` non-authoritative while making it useful as proof

### Workstream 5: Fortress Coverage For Restart And Overlap

Goals:

- add the restart, overlap, and cross-process tests that were still thin after
  round one
- prove destructive eligibility, source removal, move conflicts, and terminal
  event ordering under realistic contention
- treat test sufficiency as part of completion, not follow-up debt

## Acceptance Criteria

The implementation should not be considered complete unless it demonstrates at
least the following:

1. A persisted `source_lifecycle_runtime` row with
   `missing_confirmation_count >= 2` from a prior process does not by itself
   permit finalization in a new process.
2. Explicit finalization requires a fresh current-process confirmation of
   missing state before destructive cleanup when the runtime row predates the
   current process epoch or attachment.
3. Explicit remove does not bypass lifecycle serialization when another
   lifecycle owner currently holds the source lease.
4. The lifecycle materialization path fails closed if explicit removal or an
   equivalent conflicting lifecycle mutation invalidates the source mid-flight.
5. CLI `move` and MCP `brain_sync_move` return deterministic conflict behavior
   for lease contention and do not leak raw exceptions for normal overlap.
6. Successful non-missing lease-owned operations do not leave behind empty
   `source_lifecycle_runtime` rows.
7. Canonical-ID targeting for finalization uses one shared validator rather
   than duplicated heuristic checks.
8. `docs/RULES.md`, `docs/runtime/SCHEMAS.md`, and
   `docs/architecture/ARCHITECTURE.md` state the sharpened lifecycle
   serialization and restart-confirmation rules explicitly.
9. `operational_events` is used in overlap/restart lifecycle tests to prove
   ordering and terminal outcomes for the hardened behaviors covered here.
10. The new tests cover restart, overlap, and cross-process lifecycle
    scenarios tightly enough that the defects identified by this review cannot
    regress silently.

## Test Fortress Expectations

The implementation and review must plan and land coverage at these levels.

### Unit

- exact reducer tests for current-process confirmation versus inherited runtime
  history
- move conflict result tests for CLI/MCP transport shaping
- runtime-row cleanup tests proving empty lifecycle rows are pruned after
  successful non-missing lease-owned operations
- boundary tests proving the expanded lifecycle-serialization rule is enforced
  at the approved lifecycle owners

### Integration

- explicit finalization with a reused runtime row from a prior process proving
  the first new-process invocation remains non-finalizing until fresh
  confirmation
- explicit remove overlapping a held lifecycle lease proving remove cannot
  bypass serialization
- materialization/remove overlap proving the path fails closed instead of
  resurrecting polling or leaving orphaned managed state
- successful move proving runtime lifecycle cleanup leaves no empty row behind

### MCP

- `brain_sync_move` lease-conflict behavior as a deterministic handled result
  rather than an unhandled exception
- `brain_sync_finalize_missing` canonical-ID validation through the shared
  validator

### System

- CLI `finalize-missing` after a simulated restart with a carried-forward
  `missing_confirmation_count >= 2` proving no immediate destructive cleanup
- CLI `move` under held lifecycle lease proving deterministic conflict
  behavior
- CLI `remove` while a same-source lifecycle lease is held proving
  serialization-safe behavior

### E2E

- daemon poll/materialization racing CLI move
- daemon poll/materialization racing CLI remove
- process stop/start with reused `source_lifecycle_runtime` rows from a prior
  process
- restart/overlap assertions that use `operational_events` to prove ordering
  and terminal outcome rather than relying only on logs

## Review Focus

The first review pass for the revision derived from this artifact should focus
especially on:

- whether the new current-process confirmation rule is explicit enough to close
  the restart-era finalization hole without leaving implementer guesswork
- whether lifecycle serialization is now defined tightly enough for all
  lifecycle-affecting writes that materially require it
- whether the transport conflict contract for move is exact and user-facing
  rather than exception-driven
- whether runtime-row cleanup rules are now strong enough that
  `source_lifecycle_runtime` remains trustworthy as a coordination table rather
  than a pile of stale residue
- whether the v2 fortress tests prove overlap and restart behavior strongly
  enough to justify calling the lifecycle subsystem production-grade

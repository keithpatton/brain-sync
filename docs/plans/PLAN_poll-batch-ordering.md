# PLAN_poll-batch-ordering: Due-Batch Freshness Ordering For Source Polling

## Status

Planning artifact only. This document defines the implementation plan for
changing daemon polling so that, within an already-due batch of sources,
brain-sync checks the sources most likely to have changed first.

This stage does **not** authorize implementation by itself. Work should follow
the normal `docs/plans/` review and approval trail before code changes begin.

## Objective

Improve freshness for high-churn synced content without changing the existing
polling authority model, poll volume, or regen sequencing.

The implementation must preserve the current model:

- `sync_polling` remains authoritative for which sources are due
- portable source manifests remain authoritative for durable source lifecycle
  and settled materialization state
- `missing` sources remain excluded from active polling
- source fetching and regen remain separate phases of the daemon loop
- the change affects ordering only inside the already-due batch

The user-visible outcome should be:

- when many sources are due together, `awaiting` and `stale` sources are
  checked first
- among otherwise materialized sources, the most recently materialized sources
  are checked first
- unchanged cold content is still checked eventually under the existing
  scheduler

## Authoritative Inputs

Implementation must treat these documents as the primary constraints:

- `docs/RULES.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/README.md`
- `AGENTS.md`

Implementation must also align with the current owning seams for scheduling,
runtime polling state, and source lifecycle:

- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/scheduler.py`
- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/brain/manifest.py`

## Context

The current daemon already has adaptive polling backoff based on settled source
recency.

- newly changed or newly materialized sources stay on the hottest interval
- long-stable sources back off gradually to longer intervals
- sources with no persisted runtime schedule are scheduled immediately
- `missing` sources are excluded from active polling state

That means the system already answers "which sources are due now?" reasonably
well. The remaining issue is the order inside the due batch.

Today:

- the scheduler drains due keys in heap order
- the daemon processes them in that returned order
- there is no secondary sort based on source lifecycle state or durable
  freshness recency

With hundreds of sources, a single pass can contain many unchanged checks.
Ordering the due batch can improve time-to-detect for hot content without:

- increasing the number of checks
- weakening scheduling persistence
- introducing new concurrency paths
- pulling regen into the middle of the fetch loop

## Scope

In scope for the implementation stage:

- add a deterministic ordering rule for the already-due source batch
- use manifest-backed lifecycle and materialization state already available in
  `SourceState`
- keep current due-batch eligibility and rescheduling behavior unchanged
- add tests for the ordering rule and daemon-level usage of that rule
- update sync docs only if the explanation of daemon poll ordering becomes
  materially incomplete without it

## Non-goals

- no change to how a source becomes due
- no change to polling intervals or backoff thresholds
- no change to `sync_polling` schema or meaning
- no new durable freshness field in runtime state
- no change to source lifecycle lease behavior
- no change to regen debounce, cooldown, rate limiting, or queue sequencing
- no mid-batch "regen immediately after fetch" behavior
- no attempt to use provider-native upstream modification timestamps in this
  phase

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material issue.

### 1. `sync_polling` remains the authority for due eligibility, not freshness ordering

The scheduler and persisted runtime poll state continue to decide which sources
are due in a given daemon tick.

The new ordering logic applies only after that due set has already been
selected.

### 2. Freshness ordering uses existing manifest-backed state

This change should not introduce a new persisted "hotness" field.

Within the due batch, ordering should use the current in-memory `SourceState`
projection, specifically:

- `knowledge_state`
- manifest `materialized_utc`

`materialized_utc` is the current durable proxy for "recently settled source
content" and is sufficient for this narrow ordering improvement.

### 3. Ordering priority is lifecycle-first, then recency

Within a due batch, the intended order is:

1. `awaiting`
2. `stale`
3. other actively polled settled sources ordered by `materialized_utc`
   descending

Practical interpretation:

- `awaiting` should go first because the source has not yet been successfully
  materialized
- `stale` should go next because current local content is explicitly no longer
  trusted
- settled materialized sources should then be checked from newest
  `materialized_utc` to oldest

### 4. `missing` remains excluded before ordering

The ordering helper must not become a back door that reintroduces `missing`
sources into polling.

`missing` remains excluded by the existing active-state load logic before the
due batch is formed.

### 5. Regen sequencing remains unchanged in this phase

The daemon should continue to:

- fetch and process due sources first
- enqueue regen for changed sources
- process ready regen work afterward

This plan intentionally avoids starting regen in the middle of polling because
that would create a larger scheduling and churn discussion than the ordering
change itself.

## Workstreams

### Phase 0: Ordering Contract Clarification

Goals:

- make the intended due-batch ordering explicit before code changes

Implementation requirements:

- define the exact ordering rule in code comments or helper docstrings
- ensure the rule distinguishes:
  - due eligibility
  - lifecycle priority
  - recency ordering
- keep the language aligned with current schema names:
  - `knowledge_state`
  - `materialized_utc`

Primary modules:

- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/source_state.py`

### Phase 1: Extract A Deterministic Due-Batch Sort Helper

Goals:

- keep the daemon loop readable
- make the ordering rule unit-testable in isolation

Implementation requirements:

- add a helper that accepts due keys plus active `SourceState` data and returns
  the ordered key list
- rank keys by:
  - `knowledge_state` priority: `awaiting`, then `stale`, then other active
    settled states
  - `materialized_utc` descending for the settled group
  - stable deterministic fallback for ties, such as `canonical_id`
- define how `None` `materialized_utc` values sort within the settled group
  without inventing a new meaning for them

Primary modules:

- `src/brain_sync/sync/daemon.py`

### Phase 2: Apply The Ordering Inside The Existing Due-Batch Path

Goals:

- change processing order without changing scheduling authority

Implementation requirements:

- leave `scheduler.pop_due()` untouched as the due-selection mechanism
- sort only the resulting due keys before the daemon enters the existing
  per-source processing loop
- preserve current handling for:
  - source disappearance between scheduling and processing
  - lease conflicts
  - remote missing handling
  - error backoff and rescheduling

Primary modules:

- `src/brain_sync/sync/daemon.py`

### Phase 3: Verification Coverage

Goals:

- lock the ordering rule in place and prevent accidental drift

Implementation requirements:

- add unit coverage for the ordering helper with cases for:
  - `awaiting` before `stale`
  - `stale` before materialized sources
  - more recent `materialized_utc` before older `materialized_utc`
  - deterministic tie behavior
  - absent `materialized_utc` behavior for settled sources
- add daemon-level coverage or a focused integration-style test proving that
  the sorted due batch is the order used for source processing

Primary test areas:

- `tests/unit/`
- `tests/integration/` only if unit-level proof is insufficient

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. The scheduler remains the sole authority for deciding which sources are due
   in a daemon tick.
2. The daemon processes already-due sources in this priority order:
   `awaiting`, then `stale`, then settled active sources by
   `materialized_utc` descending.
3. `missing` sources remain excluded from active polling and do not appear in
   the ordered due batch.
4. Persisted runtime polling behavior, including `sync_polling` fields and
   rescheduling semantics, is unchanged by the feature.
5. Regen still runs after due-source processing rather than interleaving into
   the middle of the polling batch.
6. Tests make the ordering rule and the daemon’s use of it explicit enough
   that a later refactor cannot silently drop the behavior.

## Risks And Mitigations

### Risk: The implementation accidentally changes due eligibility rather than ordering

Mitigation:

- keep `scheduler.pop_due()` unchanged
- keep ordering logic isolated as a post-selection step

### Risk: The ordering helper depends on runtime-only state that may be absent

Mitigation:

- use the existing `SourceState` projection that already merges manifests and
  runtime polling state
- rely on manifest `materialized_utc`, not a new runtime column

### Risk: Ordering semantics become ambiguous for sources without settled timestamps

Mitigation:

- document explicit fallback behavior for `None` `materialized_utc`
- keep the final fallback deterministic

### Risk: The team expects this change to solve regen latency by itself

Mitigation:

- state clearly in docs and review that this phase only improves fetch
  detection order
- keep regen sequencing out of scope for this plan

## Reviewer / Approver Focus

Review should challenge these questions carefully:

1. Is the plan narrow enough that it changes ordering only inside the existing
   due batch?
2. Does the plan make the lifecycle-first ordering rule unambiguous?
3. Is `materialized_utc` an acceptable durable proxy for recency in this
   phase?
4. Do the acceptance criteria preserve current scheduler, lifecycle, and regen
   boundaries?
5. Are the proposed tests strong enough to prove the daemon actually uses the
   sorted order rather than only defining it?

## Next Step After Review

If review feedback identifies issues, the planner should create a revised plan
artifact rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

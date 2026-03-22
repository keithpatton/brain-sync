# PLAN_operational-events-hardening: Operational Event Reliability Hardening For REGEN

## Status

Planning artifact only. This document defines the implementation plan for
making `operational_events` reliable enough to support the upcoming REGEN
refactor without expanding the work into a full observability project.

This stage does **not** approve implementation. It records the intended
scope, design constraints, sequencing, and acceptance gates for later review
and approval.

## Objective

Strengthen the existing operational-event spine so REGEN-facing work can rely
on it as a stable local diagnostic contract:

- centralize event family/type names behind one shared in-code catalog
- keep `runtime.repository` as the only persistence owner for
  `operational_events`
- add retention and pruning for `operational_events` parallel to
  `token_events`
- stop high-churn emitters from hand-rolling event names and repeated common
  fields
- add enforcement tests so ad hoc event families and accidental contract drift
  fail fast during normal development

The goal is reliability and refactor-readiness, not richer reporting.

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`

The plan is also informed by the current architecture review findings that
called out stringly typed operational events as a remaining risk:

- `docs/architecture/reviews/2026-03-18-review-3.md`

Primary code seams that must stay aligned:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/runtime/token_tracking.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/application/query_index.py`
- `src/brain_sync/application/local_files.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/finalization.py`
- `src/brain_sync/sync/reconcile.py`
- `tests/unit/test_runtime_operational_events.py`
- `tests/unit/test_runtime_operational_event_callers.py`
- `tests/unit/test_state.py`

## Context

The repository already has a real local operational event trail:

- `operational_events` is persisted in the runtime DB
- event emission is intentionally non-fatal
- `runtime.repository` is already the sole persistence owner
- the daemon already prunes `token_events` on startup

What is still weak is the in-code contract around those events:

- event names are still spread across `application/`, `regen/`, `sync/`, and
  `runtime/` as string literals
- high-churn callers repeat common event fields manually
- there is no retention path for `operational_events`
- tests do not yet lock the allowed event families and required fields tightly
  enough for REGEN-driven refactoring

The architecture review already identified this exact drift risk. The purpose
of this plan is to close that gap with a bounded reliability pass rather than
adding new reporting surfaces, dashboards, or replay tooling.

## Scope

In scope for the implementation stage:

- one shared in-code catalog/constants layer for operational event
  family/type names used by REGEN, sync, and query-index invalidation
- one small helper/wrapper layer that standardizes event emission for the
  REGEN-facing and query-index-invalidating call paths
- retention config for `operational_events`
- pruning code in `runtime.repository`
- daemon-startup invocation of `operational_events` pruning alongside token
  pruning
- tests that lock:
  - the allowed event families used by the targeted flows
  - the minimum required fields for each depended-on family
  - the persistence-ownership seam
- documentation updates for runtime schema/config reference, architecture, and
  relevant README text

## Non-goals

- no dashboards or reporting
- no event replay tooling
- no conversion to event sourcing
- no broad redesign of every operational event payload
- no broad sync lifecycle decomposition
- no new persistence owner outside `runtime.repository`
- no attempt to type-check every existing event in one pass if it is outside
  the targeted REGEN, sync, and query-index invalidation scope

## Fixed Design Decisions

These decisions should be treated as settled unless review finds a material
architectural problem.

### 1. Keep the stored runtime shape, centralize the in-code contract

The current `operational_events` table shape remains the persistence contract
for this work. The hardening happens in code through a catalog/spec layer and
wrapper helpers, not through a larger telemetry redesign.

This keeps the change small enough for the upcoming REGEN refactor and avoids
an unnecessary runtime DB schema expansion.

### 2. `runtime.repository` remains the only persistence owner

No module outside `src/brain_sync/runtime/repository.py` may write SQL for
`operational_events`.

If a new helper module is introduced, it must delegate persistence to
`runtime.repository` rather than opening sqlite itself. This preserves the
current two-plane write discipline and keeps the event hardening aligned with
the repository's runtime-ownership rules.

### 3. The shared catalog should live in the runtime plane

The centralized event catalog and helper wrappers should live under
`src/brain_sync/runtime/`, not under REGEN or sync.

Reason:

- `runtime/` already owns operational-event persistence
- the catalog is cross-subsystem runtime contract, not REGEN-only policy
- `sync/`, `regen/`, and `application/` can import `runtime/` without
  violating the documented dependency direction

An implementation may split this into a small new module such as
`runtime/operational_events.py`, but the persistence seam must still resolve
through `runtime.repository`.

### 4. Retention should mirror the token-telemetry pattern

`operational_events` should gain config and pruning behavior parallel to
`token_events`:

- config key: `operational_events.retention_days`
- default retention: `90` days
- pruning entrypoint: config-dir-scoped, like `prune_token_events(...)`
- daemon startup should invoke pruning during the normal runtime boot path

The default is intentionally the same as `token_events` to minimize surprise
and configuration sprawl while event volume remains semantic rather than
high-cardinality.

### 5. Helpers should be family-focused, not framework-heavy

The wrapper layer should stay small and opinionated. It should reduce string
literal churn and repeated field assembly for the REGEN-facing event families
we already depend on, rather than becoming a generic observability framework.

Good examples:

- catalog entries or specs for `regen.started`, `regen.completed`,
  `regen.failed`, `regen.enqueued`
- helper functions for query-index invalidation/rebuild events
- helper functions for reconcile and watcher events that REGEN depends on

Bad examples:

- a large pluggable event SDK
- runtime event buses or replay abstractions
- a requirement that every event payload in the repository be redesigned now

### 6. Enforcement should be repository-level, not convention-only

The final state must include automated tests that fail when:

- a targeted caller introduces an ad hoc event family/type string outside the
  catalog
- a targeted event family drops its minimum required fields
- a new persistence path bypasses `runtime.repository`

Manual grep is useful during implementation, but it is not the lasting guard.

## Planned Workstreams

The implementation should be organized into four phases.

### Phase 1: Catalog And Contract Baseline

Goals:

- define the event family/type catalog for the flows this work depends on
- define the minimum required field contract for those families
- keep the contract narrow enough to support REGEN refactoring without
  over-typing the entire repository

Required changes:

- add a shared catalog/spec layer under `src/brain_sync/runtime/`
- represent, at minimum, the event families/types used by:
  - REGEN engine lifecycle
  - REGEN queue enqueue/fail behavior
  - query-index invalidation and rebuild
  - reconcile events that feed REGEN work
  - watcher/sync lifecycle events that directly affect REGEN or query-index
    invalidation behavior
- define the minimum required fields per depended-on family, for example:
  - whether `knowledge_path` is required
  - whether `outcome` is required
  - whether `canonical_id` is required
  - whether `details` must contain a stable key for multi-path invalidation

Validation gate:

- one authoritative catalog exists for the targeted event families/types
- the minimum field matrix exists in code and is testable
- the chosen coverage boundary is explicit so later review can tell what is
  intentionally included now versus deferred

Checkpoint review focus:

- whether the catalog boundary is narrow but sufficient for the REGEN refactor
- whether the field contract is concrete enough to prevent drift
- whether the work is centralizing the in-code contract without pretending to
  redesign the whole event system

### Phase 2: Wrapper Adoption Across Targeted Emitters

Goals:

- replace high-churn string-literal event emission in the targeted flows
- standardize repeated common-field assembly without moving persistence out of
  `runtime.repository`

Required changes:

- add helper/wrapper functions that use the shared catalog/spec layer
- migrate targeted emitters in:
  - `application/query_index.py`
  - `regen/engine.py`
  - `regen/queue.py`
  - `sync/lifecycle.py`
  - `sync/reconcile.py`
  - `sync/finalization.py`
- migrate any directly related runtime-owned emission that those helpers still
  depend on, such as child-discovery request events

Implementation rule:

- targeted callers should no longer pass raw string literals for event families
  to `record_brain_operational_event(...)`
- helper/wrapper functions may still pass the final stored `event_type` string
  into `runtime.repository`; the point is to centralize and validate that
  string in one place

Validation gate:

- REGEN-facing events and query-index invalidation events are catalog-backed
- the targeted flows no longer depend on scattered event-family string
  literals
- existing behavior remains non-fatal when event recording fails

Checkpoint review focus:

- whether the helper layer stayed small enough to be maintainable
- whether targeted call sites actually stopped hand-rolling event names and
  common fields
- whether the migration preserved current event semantics needed by tests and
  operators

### Phase 3: Retention And Runtime Pruning

Goals:

- give `operational_events` the same operational lifecycle discipline already
  used for `token_events`
- ensure pruning runs on a normal runtime path rather than existing only as a
  callable helper

Required changes:

- add config loading for `operational_events.retention_days`
- add `prune_operational_events(*, retention_days: int) -> int` in
  `runtime.repository`
- keep that pruning path config-dir-scoped, mirroring `prune_token_events`
- invoke pruning from daemon startup alongside token pruning
- update runtime tests for retention and prune behavior

Validation gate:

- `operational_events` retention defaults to `90` days when unset
- old rows are pruned correctly
- recent rows are retained
- daemon startup exercises the operational-event prune path in the normal boot
  flow
- pruning failure remains non-fatal

Checkpoint review focus:

- whether the prune seam still respects runtime ownership
- whether the daemon path is early enough and normal enough to count as real
  operational coverage
- whether config behavior is clearly parallel to token telemetry without
  creating unnecessary coupling

### Phase 4: Enforcement Tests And Documentation

Goals:

- make naming drift and field drift fail fast
- align the documented runtime contract with the hardened implementation

Required changes:

- extend or replace current event tests so they verify:
  - the allowed targeted event families/types come from the shared catalog
  - targeted event emitters do not add ad hoc families
  - required fields for the depended-on families are present in emitted rows
- keep or strengthen AST-level inventory tests that guard the caller surface
- update:
  - `docs/runtime/SCHEMAS.md`
  - `docs/architecture/ARCHITECTURE.md`
  - relevant `README.md` text

Documentation expectations:

- `docs/runtime/SCHEMAS.md` should describe:
  - `operational_events.retention_days`
  - the fact that `operational_events` uses a centralized in-code catalog for
    stable event families/types
  - the runtime-only, non-authoritative nature of the event trail
- `docs/architecture/ARCHITECTURE.md` should explain:
  - that `runtime.repository` remains the sole persistence owner
  - that event family/type naming is centralized under the runtime plane
  - that pruning happens in normal daemon startup
- `README.md` should mention:
  - machine-local retention for operational events alongside existing runtime
    config/telemetry references

Validation gate:

- tests fail when a targeted ad hoc event family/type is introduced
- tests fail when required fields are removed from a depended-on family
- docs match the implemented retention and centralized contract

Checkpoint review focus:

- whether the enforcement is strong enough to matter after the implementing
  agent is gone
- whether docs say only what is true today rather than promising a broader
  observability system

## Versioning And Compatibility Expectations

This plan does not intentionally change the runtime DB table shape. The
expected change is to runtime config usage, helper organization, tests, and
daemon behavior.

Therefore, the default expectation is:

- no Brain Format version change
- no runtime DB schema version bump
- no required `docs/VERSIONING.md` or `docs/COMPATIBILITY.md` update

Escalation rule:

- if implementation discovers that a DB schema change is actually necessary,
  stop and verify that the plan is still sufficient before silently expanding
  scope into a runtime-schema/versioning change

## Recommended Test Cadence

The implementation stage should use this cadence:

1. After Phase 1:
   - run targeted unit tests for the new catalog/spec layer
   - review the family/type inventory and required-field matrix
2. After Phase 2:
   - run `tests/unit/test_runtime_operational_events.py`
   - run `tests/unit/test_runtime_operational_event_callers.py`
   - run REGEN, sync, and query-index slices affected by migrated emitters
3. After Phase 3:
   - run token/operational retention tests
   - run daemon-startup tests that prove pruning is invoked
4. After Phase 4:
   - run the full affected unit and integration slice for REGEN, sync, query,
     and runtime contract enforcement

Minimum expected validation slice:

- `tests/unit/test_runtime_operational_events.py`
- `tests/unit/test_runtime_operational_event_callers.py`
- `tests/unit/test_token_tracking.py`
- `tests/unit/test_state.py`
- `tests/unit/test_regen_queue.py`
- `tests/unit/test_sync_events.py`
- `tests/unit/test_query_index.py`
- targeted integration or system tests if daemon-startup proof requires them

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. `operational_events` has a retention setting parallel to
   `token_events.retention_days`, exposed as
   `operational_events.retention_days`.
2. `prune_operational_events(...)` exists in `runtime.repository`.
3. The operational-event prune path is called from a normal runtime path,
   ideally alongside token pruning in daemon startup.
4. REGEN-facing events and query-index invalidation events no longer depend on
   scattered string literals.
5. Event names used by targeted REGEN, sync, and query-index invalidation
   flows are catalog-backed.
6. Tests fail if a targeted caller introduces a new event family/type ad hoc.
7. Tests fail if required fields are dropped from an existing depended-on
   family/type.
8. `runtime.repository` remains the only persistence owner for
   `operational_events`.
9. `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`, and
   relevant `README.md` text describe the retention behavior and centralized
   event contract accurately.

## Risks And Mitigations

### Risk: The helper layer turns into a mini observability framework

Mitigation:

- keep helpers narrow and family-focused
- centralize only the catalog/specs and repeated field assembly needed for the
  targeted flows
- defer broader payload redesign and reporting surfaces explicitly

### Risk: Tests lock too much and make normal event evolution painful

Mitigation:

- lock only the targeted families/types needed for REGEN work now
- enforce minimum required fields rather than every optional payload detail
- keep additions possible through intentional catalog changes

### Risk: Retention is added as dead code rather than real runtime behavior

Mitigation:

- require pruning to be invoked from daemon startup
- add tests that prove the startup path actually exercises pruning

### Risk: Persistence ownership drifts while adding helpers

Mitigation:

- keep SQL and DB access in `runtime.repository`
- use AST- or inventory-based tests to prevent new sqlite/event-write bypasses

## Reviewer Focus

The reviewer should concentrate on these questions:

1. Is the catalog boundary narrow enough to stay maintainable but broad enough
   for the upcoming REGEN refactor?
2. Does the helper layer reduce string drift without becoming a new framework?
3. Is the retention design truly parallel to `token_events` in both config and
   runtime behavior?
4. Are the enforcement tests strong enough to prevent ad hoc event-family
   drift after this work lands?
5. Does the plan preserve `runtime.repository` as the only
   `operational_events` persistence owner?

## Next Step After Review

If review feedback identifies issues, the planner should create a revised plan
artifact rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

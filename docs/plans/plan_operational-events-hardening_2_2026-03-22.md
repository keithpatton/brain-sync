# PLAN_operational-events-hardening Revision 2: Explicit Catalog Boundary And Daemon-Wired Retention

## Status

Planning artifact only. This revision supersedes the root plan for execution
planning purposes and resolves the first review's findings around scope
boundary, persistence-owner enforcement, daemon prune wiring, and doc
authority coverage.

This stage does **not** approve implementation. It records the revised scoped
execution model for later review and approval.

## Relationship To Prior Artifacts

This revision refines:

- `docs/plans/PLAN_operational-events-hardening.md`
- `docs/plans/plan_operational-events-hardening_review_1_2026-03-22.md`

The root plan remains the canonical origin artifact. This revision exists to
resolve the review findings that:

1. the catalog boundary and required-field matrix were still too implicit
2. the sole-persistence-owner rule did not yet have a strong enough explicit
   enforcement strategy
3. the acceptance criteria weakened the daemon prune hook with "ideally"
4. the documentation authority set omitted `docs/sync/README.md`

## Objective

Keep the same overall objective while making the execution boundary explicit
enough for implementation without guesswork:

- centralize the naming of all current production `operational_events` event
  types behind one shared in-code catalog
- migrate every current production emitter in the caller inventory to
  catalog-backed naming during this pass
- add a concrete required-field matrix for the exact event types the upcoming
  REGEN refactor depends on
- preserve `runtime.repository` as the only `operational_events` persistence
  owner through an explicit anti-bypass guard
- add `operational_events` retention and wire pruning into the existing daemon
  startup path in `sync.daemon.run()`
- update runtime, sync-flow, architecture, and README docs in their correct
  authority homes

The goal remains reliability hardening for REGEN readiness, not a general
observability expansion.

## Why This Revision Is Needed

The root plan captured the right direction but still left four decisions too
implicit for approval:

- which exact current emitters and event types this pass must cover
- how sole persistence ownership will be enforced beyond convention
- whether daemon startup is required or only preferred for prune wiring
- which docs own the daemon-startup explanation for this behavior

This revision removes those ambiguities by locking the current-pass inventory,
the anti-bypass guard, the daemon hook location, and the documentation set.

## Authoritative Inputs

This revision inherits the root plan's constraints and adds the missing
sync-flow authority home explicitly:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`
- `docs/architecture/reviews/2026-03-18-review-3.md`
- `docs/plans/plan_operational-events-hardening_review_1_2026-03-22.md`

Primary code and test seams for this revision:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/runtime/token_tracking.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/application/local_files.py`
- `src/brain_sync/application/query_index.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/sync/finalization.py`
- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/reconcile.py`
- `tests/unit/test_runtime_operational_events.py`
- `tests/unit/test_runtime_operational_event_callers.py`
- `tests/unit/test_state.py`

## Confirmed Design Decisions

### 1. Current-pass migration covers every current production emitter

This revision removes the ambiguous "REGEN-facing and query-index-invalidating
flows" boundary by locking the migration set to the full current production
caller inventory of `record_brain_operational_event(...)`.

Included production emitters for this pass:

| File | Current reason for inclusion | Status in this revision |
|---|---|---|
| `src/brain_sync/application/local_files.py` | Current production emitter; local add/remove paths are part of the current operational-event surface | Must migrate |
| `src/brain_sync/application/query_index.py` | Canonical query-index rebuild/invalidation emitter | Must migrate |
| `src/brain_sync/application/sources.py` | Current production emitter of `source.updated` | Must migrate |
| `src/brain_sync/regen/engine.py` | REGEN lifecycle and REGEN-triggered query-index invalidation | Must migrate |
| `src/brain_sync/regen/queue.py` | Queue-level REGEN failure path | Must migrate |
| `src/brain_sync/runtime/repository.py` | Runtime-owned child-request events and sole persistence seam | Must use same catalog for runtime-owned events |
| `src/brain_sync/sync/finalization.py` | Source finalization and rediscovery events | Must migrate |
| `src/brain_sync/sync/lifecycle.py` | Source lifecycle, watcher, enqueue, and reconcile-adjacent events | Must migrate |
| `src/brain_sync/sync/reconcile.py` | Reconcile cleanup/enqueue events | Must migrate |

Deferred production emitters from the current caller inventory:

| File | Deferred? | Reason |
|---|---|---|
| none | No | This revision intentionally covers the whole current production caller inventory to remove partial-migration ambiguity |

Out of scope for this pass:

| Surface | Reason |
|---|---|
| test-only direct calls to `record_brain_operational_event(...)` | Tests may still construct rows directly when validating repository behavior |
| hypothetical future emitters not present in the current inventory | They must be added through the catalog intentionally after this pass lands |
| redesign of stored payload structure beyond the required-field locks below | This remains outside the workable minimum |

### 2. Current-pass catalog coverage is the exact current production event-type set

The shared catalog for this pass must contain every current production event
type emitted by the included files above.

Required catalog members for this pass:

| Event type |
|---|
| `query.index.invalidated` |
| `query.index.rebuilt` |
| `reconcile.missing_marked` |
| `reconcile.orphan_cleaned` |
| `reconcile.path_enqueued` |
| `reconcile.path_updated` |
| `regen.completed` |
| `regen.enqueued` |
| `regen.failed` |
| `regen.started` |
| `source.child_registered` |
| `source.child_request.cleared` |
| `source.child_request.saved` |
| `source.finalization_lease_conflict` |
| `source.finalization_not_found` |
| `source.finalization_not_missing` |
| `source.finalized` |
| `source.local_file.added` |
| `source.local_file.removed` |
| `source.missing_confirmed` |
| `source.missing_marked` |
| `source.moved` |
| `source.rediscovered` |
| `source.registered` |
| `source.removed` |
| `source.updated` |
| `watcher.move_applied` |
| `watcher.move_observed` |
| `watcher.structure_observed` |

This catalog-wide coverage is the naming contract for the pass.

### 3. The required-field matrix is narrower than the naming catalog, but explicit

This pass locks event names for the full current production set above, but the
required-field regression matrix is intentionally strongest for the exact event
types the upcoming REGEN work depends on for correlation and invalidation.

Required-field matrix for this pass:

| Event type | Required stable fields |
|---|---|
| `regen.started` | `knowledge_path`, `session_id`, `owner_id` |
| `regen.completed` | `knowledge_path`, `session_id`, `owner_id`, `outcome` |
| `regen.failed` | `knowledge_path`, `session_id`, `owner_id`, `outcome`, `details.error` |
| `regen.enqueued` | `knowledge_path`, `outcome` |
| `query.index.invalidated` | `outcome`, `details.knowledge_paths` |
| `query.index.rebuilt` | `outcome` |
| `watcher.structure_observed` | `knowledge_path`, `outcome` |
| `watcher.move_observed` | `outcome`, `details.old_path`, `details.new_path` |
| `watcher.move_applied` | `outcome`, `details.old_path`, `details.new_path` |
| `reconcile.path_updated` | `canonical_id`, `outcome`, `details.old_path`, `details.new_path` |
| `reconcile.path_enqueued` | `knowledge_path`, `outcome` |
| `reconcile.orphan_cleaned` | `knowledge_path`, `outcome` |
| `reconcile.missing_marked` | `canonical_id`, `outcome` |
| `source.updated` | `canonical_id`, `outcome` |
| `source.registered` | `canonical_id`, `outcome` |
| `source.removed` | `canonical_id`, `outcome` |
| `source.moved` | `canonical_id`, `outcome`, `details.old_path`, `details.new_path` |
| `source.missing_marked` | `canonical_id`, `outcome` |
| `source.missing_confirmed` | `canonical_id`, `outcome` |
| `source.rediscovered` | `canonical_id`, `outcome` |
| `source.child_registered` | `canonical_id`, `outcome`, `details.child_canonical_id` |
| `source.child_request.saved` | `canonical_id`, `outcome` |
| `source.child_request.cleared` | `canonical_id`, `outcome` |

Event types catalog-backed but not field-locked beyond row insertion in this
pass:

| Event type | Reason |
|---|---|
| `source.local_file.added` | Catalog migration required now; payload redesign remains intentionally minimal |
| `source.local_file.removed` | Same as above |
| `source.finalization_lease_conflict` | Naming must centralize now; richer field lock can wait |
| `source.finalization_not_found` | Same as above |
| `source.finalization_not_missing` | Same as above |
| `source.finalized` | Same as above |

### 4. `runtime.repository` remains the only persistence owner, with an explicit anti-bypass guard

This revision makes persistence ownership an enforceable repository rule, not
just an intent statement.

Required enforcement for this pass:

- one repository-level test must fail if any non-test production module
  outside `src/brain_sync/runtime/repository.py` contains SQL text that reads
  from or writes to `operational_events`
- helper modules under `src/brain_sync/runtime/` may call only the public
  repository seam for this table and may not:
  - import `sqlite3` for `operational_events` access
  - import `_connect(...)` or `_connect_runtime(...)` to touch
    `operational_events`
  - contain `"operational_events"` SQL strings outside
    `runtime/repository.py`

Acceptable detection strategy for the enforcement test:

- AST or text inventory over production modules that rejects:
  - `INSERT INTO operational_events`
  - `UPDATE operational_events`
  - `DELETE FROM operational_events`
  - `FROM operational_events`
  - `JOIN operational_events`
  outside `runtime/repository.py`

The implementation may choose AST, text inventory, or a stronger equivalent,
but the approved plan requires a durable automated guard at repository scope.

### 5. The prune hook is required in `sync.daemon.run()`, not merely preferred

This revision locks the operational-event prune hook to the existing daemon
startup seam in `src/brain_sync/sync/daemon.py`.

Required daemon-startup placement:

- `prune_operational_events(...)` must be called in `sync.daemon.run()`
- it must run during startup before the main loop begins
- it must be adjacent to the existing `prune_token_events(...)` call
- it must happen before `load_active_sync_state(root)` so the normal daemon
  boot path exercises retention before steady-state work begins

Proof obligation:

- tests must prove that the normal daemon boot path invokes
  `prune_operational_events(...)`
- tests must also prove that failure in that call remains non-fatal on the
  same daemon startup path

### 6. Documentation must land in the correct authority homes

This revision adds the missing sync-flow authority home.

Required documentation updates:

| Document | Required content for this pass |
|---|---|
| `docs/runtime/SCHEMAS.md` | `operational_events.retention_days`, centralized in-code event catalog reference, runtime-only contract |
| `docs/sync/README.md` | daemon-startup flow explanation showing operational-event pruning alongside token pruning |
| `docs/architecture/ARCHITECTURE.md` | runtime ownership summary, centralized event contract summary, daemon-startup prune ownership at explanatory level |
| `README.md` | brief user-facing/runtime-config mention of machine-local operational-event retention |

## Phased Execution Plan

### Phase 1: Inventory-Locked Catalog And Contract Baseline

Goals:

- create the shared catalog for the full current production event-type set
- define the explicit field-lock matrix above in code
- make the current-pass include/defer boundary durable rather than implicit

Required changes:

- add a shared catalog/spec layer under `src/brain_sync/runtime/`
- encode the exact event-type list in this revision as the authoritative
  current-pass catalog set
- encode the exact required-field matrix in code so tests can assert it
- update or replace the current caller-inventory test so it continues to lock
  the included production emitter set above

Validation gate:

- the catalog contains every event type listed in this revision
- the emitter inventory test matches the exact production caller set listed in
  this revision
- the field-lock matrix exists as code, not only prose

Checkpoint review focus:

- whether the code-level inventory now matches the plan's explicit boundary
- whether any current production caller was left ambiguous
- whether the field-lock set is concrete enough to guide implementation

### Phase 2: Full Current-Inventory Emitter Migration

Goals:

- migrate every current production emitter to catalog-backed naming
- remove ad hoc event-type string literals from the included production
  emitters for this pass

Required changes:

- migrate:
  - `application/local_files.py`
  - `application/query_index.py`
  - `application/sources.py`
  - `regen/engine.py`
  - `regen/queue.py`
  - `runtime/repository.py` for runtime-owned emitted events
  - `sync/finalization.py`
  - `sync/lifecycle.py`
  - `sync/reconcile.py`
- where high-churn call sites repeat common field assembly, route them through
  small helper/wrapper functions built on the shared catalog/spec layer

Implementation rule:

- after this phase, no included production emitter should introduce a new raw
  event-type literal at the call site for `record_brain_operational_event(...)`
- the helper layer must remain small and runtime-owned, not a generic event
  framework

Validation gate:

- every included production emitter is catalog-backed
- no included production emitter depends on ad hoc event-type literals
- current semantics remain non-fatal on event-write failure

Checkpoint review focus:

- completeness of the full emitter migration
- whether wrappers stayed narrow and practical
- whether the migration removed duplication rather than only moving it around

### Phase 3: Persistence-Owner Guard And Daemon-Wired Retention

Goals:

- add operational-event retention parallel to token telemetry
- add the strong anti-bypass guard for persistence ownership
- wire pruning into the normal daemon startup path concretely

Required changes:

- add config loading for `operational_events.retention_days`
- add `prune_operational_events(*, retention_days: int) -> int` to
  `runtime.repository`
- add the repository-level anti-bypass test that rejects
  `operational_events` SQL outside `runtime.repository`
- update `sync.daemon.run()` so startup calls:
  - `prune_token_events(...)`
  - `prune_operational_events(...)`
  in the startup path before `load_active_sync_state(root)` and before the
  daemon enters the main loop

Validation gate:

- `operational_events` defaults to `90` retention days when unset
- prune deletes old rows and keeps recent rows
- daemon startup invokes `prune_operational_events(...)` on the normal boot
  path
- prune failure remains non-fatal on that same path
- the anti-bypass guard fails if production code outside
  `runtime/repository.py` adds `operational_events` SQL

Checkpoint review focus:

- whether daemon wiring is concrete and provable
- whether ownership enforcement is now strong enough to matter
- whether runtime-owned helpers remain helpers rather than second persistence
  owners

### Phase 4: Field-Lock Tests And Authority-Aligned Docs

Goals:

- make event-type drift and field drift fail fast
- align docs with the implemented runtime and daemon-flow behavior

Required changes:

- add or strengthen tests that prove:
  - the catalog event-type set matches the revision's required list
  - the included emitter inventory remains exact
  - the required-field matrix is honored by emitted rows for the locked event
    types
  - ad hoc event types introduced in included production emitters fail tests
- update:
  - `docs/runtime/SCHEMAS.md`
  - `docs/sync/README.md`
  - `docs/architecture/ARCHITECTURE.md`
  - `README.md`

Validation gate:

- tests fail when a new ad hoc event type is introduced in an included
  production emitter
- tests fail when a required field is removed from a field-locked event type
- docs describe both the runtime retention contract and the daemon-startup
  flow in their correct authority homes

Checkpoint review focus:

- whether the tests now protect both naming and field contract drift
- whether docs are split correctly across runtime, sync, architecture, and
  README roles

## Recommended Test And Review Cadence

The implementation stage should use this cadence:

1. After Phase 1:
   - run the catalog/spec tests
   - run the emitter-inventory test
   - review the exact event-type and field-lock sets against this revision
2. After Phase 2:
   - run:
     - `tests/unit/test_runtime_operational_events.py`
     - `tests/unit/test_runtime_operational_event_callers.py`
     - `tests/unit/test_sync_events.py`
     - `tests/unit/test_query_index.py`
     - `tests/unit/test_regen_queue.py`
   - review whether every included production emitter actually migrated
3. After Phase 3:
   - run:
     - `tests/unit/test_token_tracking.py`
     - `tests/unit/test_state.py`
     - targeted daemon-startup tests proving prune invocation and non-fatal
       failure
     - the anti-bypass ownership test
4. After Phase 4:
   - run the full affected unit and integration slice for runtime, sync,
     query, and REGEN event contract enforcement

## Acceptance Criteria

This revision is complete only when all of the following are true:

1. A shared in-code catalog exists for every event type listed in this
   revision's required catalog set.
2. Every current production emitter listed in this revision's included
   inventory is migrated to catalog-backed naming in this pass.
3. `operational_events` has a retention setting exposed as
   `operational_events.retention_days`.
4. `prune_operational_events(...)` exists in `runtime.repository`.
5. `sync.daemon.run()` invokes `prune_operational_events(...)` during startup
   adjacent to token pruning, before `load_active_sync_state(root)`, and
   before the main loop begins.
6. Tests prove that the normal daemon boot path invokes
   `prune_operational_events(...)`.
7. Tests prove that failure in `prune_operational_events(...)` remains
   non-fatal on that same daemon startup path.
8. A repository-level automated guard fails if production code outside
   `src/brain_sync/runtime/repository.py` issues SQL against
   `operational_events`.
9. Tests fail if an included production emitter introduces a new ad hoc event
   type outside the shared catalog.
10. Tests fail if a field-locked event type drops one of the required stable
    fields specified in this revision.
11. `runtime.repository` remains the only persistence owner for
    `operational_events`.
12. `docs/runtime/SCHEMAS.md`, `docs/sync/README.md`,
    `docs/architecture/ARCHITECTURE.md`, and relevant `README.md` text are
    updated to describe the retention behavior and centralized event contract
    in the correct authority homes.

## Review Focus

The next review pass should focus especially on:

1. whether the explicit emitter inventory and event-type list now eliminate
   implementer guesswork
2. whether the field-lock matrix is concrete enough for the upcoming REGEN
   refactor without overreaching into a payload redesign
3. whether the anti-bypass persistence-owner guard is strong enough to protect
   `runtime.repository` ownership
4. whether the daemon prune hook is now fixed to the correct startup seam
5. whether the doc update set now matches repository doc-authority rules

## Exit Criteria

This revision should be considered ready for approval only when a reviewer can
confirm that it:

- resolves all four blocking findings from
  `plan_operational-events-hardening_review_1_2026-03-22.md`
- converts the current-pass boundary into explicit included emitters, exact
  event types, and a concrete field-lock matrix
- makes daemon-startup pruning a required and provable runtime path
- makes sole persistence ownership enforceable rather than aspirational

If review feedback identifies issues, the planner should create a later plan
revision rather than editing this file in place.

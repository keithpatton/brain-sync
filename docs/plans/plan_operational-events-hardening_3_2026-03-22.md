# PLAN_operational-events-hardening Revision 3: Corrected Field-Lock Matrix Without Payload-Key Drift

## Status

Planning artifact only. This revision supersedes revision 2 for execution
planning purposes and corrects the required-field matrix so it matches the
current stored event contract rather than accidentally redefining it.

This stage does **not** approve implementation. It records the revised scoped
execution model for later review and approval.

## Relationship To Prior Artifacts

This revision refines:

- `docs/plans/PLAN_operational-events-hardening.md`
- `docs/plans/plan_operational-events-hardening_review_1_2026-03-22.md`
- `docs/plans/plan_operational-events-hardening_2_2026-03-22.md`
- `docs/plans/plan_operational-events-hardening_2_review_1_2026-03-22.md`

Revision 2 already resolved the earlier blockers around:

- explicit current-pass emitter and event-type boundary
- sole `runtime.repository` persistence-owner enforcement
- mandatory daemon-startup prune wiring
- documentation authority coverage

This revision exists to resolve the remaining review finding that revision 2's
required-field matrix still contained:

1. an incorrect row-vs-details requirement for `source.child_registered`
2. an under-justified watcher move payload-key rename

## Objective

Keep the revision 2 objective, with one additional constraint: the field-lock
matrix must describe the real current stable event contract for this pass
rather than silently redesigning payload keys.

This pass still aims to:

- centralize the naming of all current production `operational_events` event
  types behind one shared in-code catalog
- migrate every current production emitter in the caller inventory to
  catalog-backed naming during this pass
- preserve `runtime.repository` as the only `operational_events` persistence
  owner through an explicit anti-bypass guard
- add `operational_events` retention and wire pruning into the existing daemon
  startup path in `sync.daemon.run()`
- update runtime, sync-flow, architecture, and README docs in their correct
  authority homes

And now explicitly:

- correct the field-lock matrix so row identity stays in row columns and
  existing stable detail keys remain unchanged unless a rename is separately
  justified and approved

## Authoritative Inputs

This revision inherits revision 2's authority set and adds direct code reality
for the corrected matrix as a required input:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`
- `docs/architecture/reviews/2026-03-18-review-3.md`
- `docs/plans/plan_operational-events-hardening_2_review_1_2026-03-22.md`
- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/application/query_index.py`

## Confirmed Design Decisions

### 1. Revision 2's explicit emitter and event-type boundary remains intact

This revision keeps revision 2's full current-production emitter inventory and
exact event-type catalog boundary. No production emitter from that inventory is
deferred in this pass.

The included production emitters therefore remain:

- `src/brain_sync/application/local_files.py`
- `src/brain_sync/application/query_index.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/finalization.py`
- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/reconcile.py`

The required catalog members therefore remain:

- `query.index.invalidated`
- `query.index.rebuilt`
- `reconcile.missing_marked`
- `reconcile.orphan_cleaned`
- `reconcile.path_enqueued`
- `reconcile.path_updated`
- `regen.completed`
- `regen.enqueued`
- `regen.failed`
- `regen.started`
- `source.child_registered`
- `source.child_request.cleared`
- `source.child_request.saved`
- `source.finalization_lease_conflict`
- `source.finalization_not_found`
- `source.finalization_not_missing`
- `source.finalized`
- `source.local_file.added`
- `source.local_file.removed`
- `source.missing_confirmed`
- `source.missing_marked`
- `source.moved`
- `source.rediscovered`
- `source.registered`
- `source.removed`
- `source.updated`
- `watcher.move_applied`
- `watcher.move_observed`
- `watcher.structure_observed`

### 2. Field locks must match current stable payload semantics

The field-lock matrix in this pass is a contract-preserving guard, not a
payload redesign mechanism.

Rules for this revision:

- if an identifier already lives in a stable row column such as
  `canonical_id`, the field-lock matrix must not move that identity into
  `details`
- if a stable detail key already exists in production for a locked event type,
  this pass keeps that key unless a rename is separately justified in plan
  text, acceptance criteria, tests, and docs
- this bounded hardening pass does not rename watcher move detail keys

### 3. `source.child_registered` keeps child identity in the row and parent linkage in details

For `source.child_registered`, the row's `canonical_id` remains the child
identifier. The stable detail linkage retained by this pass is
`details.parent_canonical_id`.

This is the useful correlation contract today and must not be replaced with a
duplicated `details.child_canonical_id`.

### 4. Watcher move events keep `details.src` / `details.dest` in this pass

For `watcher.move_observed` and `watcher.move_applied`, this pass locks the
current stable detail keys:

- `details.src`
- `details.dest`

This revision does not approve a rename to `old_path` / `new_path`.

If a later change wants to rename those keys for clarity, that must be treated
as an intentional event-contract change with its own explicit justification,
tests, and docs.

### 5. Revision 2's ownership, daemon-hook, and doc-authority decisions remain intact

This revision keeps revision 2's already-correct decisions that:

- `runtime.repository` remains the only `operational_events` persistence owner
- a repository-level anti-bypass guard is required
- `sync.daemon.run()` must invoke `prune_operational_events(...)` during
  startup adjacent to token pruning and before `load_active_sync_state(root)`
- `docs/runtime/SCHEMAS.md`, `docs/sync/README.md`,
  `docs/architecture/ARCHITECTURE.md`, and `README.md` are the required doc
  update set

## Corrected Required-Field Matrix

This revision keeps revision 2's narrow-vs-broad split:

- the full current production event-type set is catalog-backed
- the field-lock regression matrix is strongest for the exact event types the
  upcoming REGEN work depends on

Corrected required-field matrix for this pass:

| Event type | Required stable fields |
|---|---|
| `regen.started` | `knowledge_path`, `session_id`, `owner_id` |
| `regen.completed` | `knowledge_path`, `session_id`, `owner_id`, `outcome` |
| `regen.failed` | `knowledge_path`, `session_id`, `owner_id`, `outcome`, `details.error` |
| `regen.enqueued` | `knowledge_path`, `outcome` |
| `query.index.invalidated` | `outcome`, `details.knowledge_paths` |
| `query.index.rebuilt` | `outcome` |
| `watcher.structure_observed` | `knowledge_path`, `outcome` |
| `watcher.move_observed` | `knowledge_path`, `outcome`, `details.src`, `details.dest` |
| `watcher.move_applied` | `knowledge_path`, `outcome`, `details.src`, `details.dest` |
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
| `source.child_registered` | `canonical_id`, `knowledge_path`, `outcome`, `details.parent_canonical_id` |
| `source.child_request.saved` | `canonical_id`, `outcome` |
| `source.child_request.cleared` | `canonical_id`, `outcome` |

Catalog-backed but not field-locked beyond row insertion in this pass:

| Event type | Reason |
|---|---|
| `source.local_file.added` | Catalog migration required now; payload redesign remains intentionally minimal |
| `source.local_file.removed` | Same as above |
| `source.finalization_lease_conflict` | Naming must centralize now; richer field lock can wait |
| `source.finalization_not_found` | Same as above |
| `source.finalization_not_missing` | Same as above |
| `source.finalized` | Same as above |

Matrix verification rule for this revision:

- before approval, the reviewer should sanity-check the locked fields against
  current code reality so no other row-vs-details mistake survives into the
  approved artifact

## Phased Execution Plan

### Phase 1: Inventory-Locked Catalog And Corrected Contract Baseline

Goals:

- create the shared catalog for the full current production event-type set
- encode the corrected field-lock matrix above in code
- preserve current stable payload semantics rather than renaming keys

Required changes:

- add a shared catalog/spec layer under `src/brain_sync/runtime/`
- encode the exact event-type list above as the authoritative current-pass
  catalog set
- encode the corrected field-lock matrix in code so tests can assert it
- update or replace the current caller-inventory test so it continues to lock
  the full included production emitter set

Validation gate:

- the catalog contains every event type listed in this revision
- the emitter inventory test matches the full included production caller set
- the field-lock matrix exists as code, not only prose
- the encoded matrix does not rename current stable watcher move detail keys
  and does not duplicate child identity into `details`

### Phase 2: Full Current-Inventory Emitter Migration

Goals:

- migrate every included production emitter to catalog-backed naming
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
- this phase must preserve the corrected field-lock contract above; it is not a
  payload-rename phase

Validation gate:

- every included production emitter is catalog-backed
- no included production emitter depends on ad hoc event-type literals
- current semantics remain non-fatal on event-write failure

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
  before `load_active_sync_state(root)` and before the daemon enters the main
  loop

Validation gate:

- `operational_events` defaults to `90` retention days when unset
- prune deletes old rows and keeps recent rows
- daemon startup invokes `prune_operational_events(...)` on the normal boot
  path
- prune failure remains non-fatal on that same path
- the anti-bypass guard fails if production code outside
  `runtime/repository.py` adds `operational_events` SQL

### Phase 4: Field-Lock Tests And Authority-Aligned Docs

Goals:

- make event-type drift and field drift fail fast
- align docs with the implemented runtime and daemon-flow behavior

Required changes:

- add or strengthen tests that prove:
  - the catalog event-type set matches this revision's required list
  - the included emitter inventory remains exact
  - the corrected field-lock matrix is honored by emitted rows for the locked
    event types
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
- tests fail if the locked watcher move contract silently changes from
  `details.src` / `details.dest` in this pass
- tests fail if `source.child_registered` loses the parent linkage in
  `details.parent_canonical_id`
- docs describe both the runtime retention contract and the daemon-startup
  flow in their correct authority homes

## Acceptance Criteria

This revision is complete only when all of the following are true:

1. A shared in-code catalog exists for every event type in the required
   current-pass catalog set.
2. Every included current production emitter is migrated to catalog-backed
   naming in this pass.
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
11. Tests fail if `source.child_registered` stops carrying child identity in
    row `canonical_id` plus parent linkage in `details.parent_canonical_id`.
12. Tests fail if watcher move events stop carrying `details.src` and
    `details.dest` in this pass.
13. `runtime.repository` remains the only persistence owner for
    `operational_events`.
14. `docs/runtime/SCHEMAS.md`, `docs/sync/README.md`,
    `docs/architecture/ARCHITECTURE.md`, and relevant `README.md` text are
    updated to describe the retention behavior and centralized event contract
    in the correct authority homes.

## Review Focus

The next review pass should focus especially on:

1. whether the corrected field-lock matrix now matches current event semantics
   without accidental payload redesign
2. whether any remaining row-vs-details mistake survives in the locked event
   contract
3. whether the already-fixed boundary, ownership, daemon-hook, and doc
   authority decisions remain intact

## Exit Criteria

This revision should be considered ready for approval only when a reviewer can
confirm that it:

- resolves the remaining finding from
  `plan_operational-events-hardening_2_review_1_2026-03-22.md`
- keeps revision 2's explicit emitter/type boundary, ownership enforcement,
  daemon wiring, and doc-authority coverage intact
- corrects the field-lock matrix without smuggling in a broader payload
  redesign

If review feedback identifies issues, the planner should create a later plan
revision rather than editing this file in place.

# Approval

Approved: 2026-03-18T10-56-01
Approved by: codex-gpt-5

Notes:
- The plan makes the REGEN public surface, runtime DB ownership, watcher and daemon policy extraction, invalidation seams, and operational event model concrete enough for implementation without leaving key boundary choices to implementer guesswork.
- Brain Format `1.0` remains intentionally unchanged, with a clear stop-and-replan rule if execution finds a proven contract-change blocker.
- The sequencing, ratchets, and review-tied exit criteria are specific enough for the next architecture rerun to judge readiness against the existing rubric.

---

# plan_architecture-hardening_3: REGEN Refactor Readiness Hardening

## Status

Approved plan revision 3.

This artifact records approval of
`docs/plans/plan_architecture-hardening_3_2026-03-18.md` as the authoritative
implementation handoff for this work.

## Objective

Make the next architecture review able to mark the system ready for a major
REGEN refactor without changing Brain Format `1.0`.

This revision is narrower than the prior hardening pass. Its job is to finish
the structural work that the 2026-03-18 review still found blocking:

1. give REGEN a genuinely narrow public boundary
2. unify runtime DB ownership behind one truthful runtime persistence surface
3. extract daemon and watcher policy that still encodes REGEN-adjacent behavior
4. replace scan-heavy freshness paths with explicit invalidation seams
5. upgrade observability from token telemetry to an operational event model

## Prior Context And Inputs

This revision is grounded in these upstream artifacts:

- `docs/architecture/reviews/README.md`
- `docs/architecture/reviews/2026-03-17-baseline.md`
- `docs/architecture/reviews/2026-03-18-review-2.md`
- `docs/plans/PLAN_architecture-hardening.md`
- `docs/plans/plan_architecture-hardening_2_approved_2026-03-17T20-58-15.md`

The 2026-03-18 architecture review is the problem statement for this plan.
Its findings diagnose the current architecture; they do not authorize code
changes by themselves.

## Authoritative Inputs

Implementation must treat these documents as primary constraints:

- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/architecture/reviews/TEMPLATE.md`
- `docs/architecture/reviews/2026-03-18-review-2.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `AGENTS.md`

## Problem Statement

The second architecture review confirmed that the previous hardening pass
improved contract truthfulness and transport thinning, but it left five
blocking issues for REGEN-refactor readiness:

1. `brain_sync.regen` still exposes engine internals instead of a narrow public API
2. runtime DB ownership is conceptually cleaner but still split across direct owners
3. daemon and watcher code still encode child-discovery, move, cache, and enqueue policy inline
4. query freshness and startup reconcile still pay for broad scans and repeated classification
5. telemetry exists, but there is still no typed operational event spine

This revision resolves those boundary choices explicitly. It does not leave
the steady state for REGEN, runtime persistence, watcher policy, invalidation,
or events to implementation-time guesswork.

## Fixed Design Decisions

### 1. Brain Format `1.0` stays unchanged in this plan

This plan does not change any portable manifest, sidecar, or on-disk brain
layout contract.

If implementation discovers that any item in this plan cannot be completed
without changing Brain Format `1.0`, implementation must stop and produce a
new review-and-plan trail. That contract change is blocked and out of scope
for this revision.

### 2. The REGEN public boundary is explicitly small

The supported cross-package REGEN API after this hardening pass is:

- `brain_sync.regen.ChangeEvent`
- `brain_sync.regen.RegenFailed`
- `brain_sync.regen.classify_folder_change()`
- `brain_sync.regen.regen_path()`
- `brain_sync.regen.regen_all()`

Daemon-only orchestration seams remain supported, but only as named
non-barrel imports:

- `brain_sync.regen.lifecycle.regen_session`
- `brain_sync.regen.queue.RegenQueue`

Caller rules:

- CLI and MCP use only `application.regen.run_regen()`
- `application/regen.py` is the only application-owned bridge to the public
  `brain_sync.regen` API
- `sync/daemon.py` may use `regen_session` and `RegenQueue` as an approved
  orchestration surface
- `sync/reconcile.py` and `sync/watcher.py` must not import `brain_sync.regen`
- no transport module may import `brain_sync.regen.queue`, `brain_sync.regen.engine`,
  or any REGEN internal helper module directly

What stops being exported from `brain_sync.regen`:

- every underscore-prefixed symbol
- queue topology helpers such as `_PROPAGATES_UP`, `_parent_path`, and `compute_waves`
- single-folder engine internals such as `regen_single_folder`
- prompt and parsing helpers such as `_build_prompt`, `_build_chunk_prompt`,
  `_parse_stream_json`, and `_parse_structured_output`
- content and structure helper exports such as `collect_child_summaries`,
  `compute_content_hash`, `compute_structure_hash`, `invoke_claude`,
  `invalidate_global_context_cache`, and prompt-budget constants

Internal ownership target inside `regen/`:

- `regen/topology.py` owns wave computation and parent propagation rules
- `regen/engine.py` owns single-folder execution and internal prompt assembly
- `regen/__init__.py` stops acting as a barrel over those internals

This is the key boundary decision for localizing the next REGEN refactor.

### 3. Runtime DB access is unified behind one truthful owner

`runtime.repository` remains the only supported runtime persistence surface and
the only place outside tests and migration code that may:

- resolve the runtime DB path
- open sqlite connections
- declare runtime table DDL
- mutate runtime tables directly

Implementation may split persistence by concern under `runtime/`, but only as
internal store modules beneath `runtime.repository`. The supported import
surface stays `runtime.repository`, not a new set of peer DB owners.

Approved runtime persistence families:

- sync progress
- child-discovery requests
- regen lifecycle state
- operational events
- usage telemetry reporting and retention

Required caller outcome:

- `runtime/child_requests.py` stops opening the DB and stops duplicating DDL;
  it becomes a pure model/facade layer or is removed
- `runtime/token_tracking.py` stops opening sqlite directly; usage-event
  writes, reads, and pruning route through `runtime.repository`
- no production module outside `runtime.repository` may call `_connect()` or
  `sqlite3.connect()` for runtime DB access

This keeps runtime ownership narrow without returning to one monolithic mixed
module as the only place where every concern is implemented inline.

### 4. Daemon and watcher policy move behind explicit application services

The remaining REGEN-adjacent policy will be extracted into two named services:

- `application/child_discovery.py`
- `application/sync_events.py`

`application/child_discovery.py` owns:

- child placement rules
- parent-derived default child path calculation
- discovered-child registration workflow
- one-shot request clearing semantics

`application/sync_events.py` owns:

- folder-move application to manifests and runtime regen state
- structure-only insight-state repair decisions
- `_core`-related invalidation decisions
- watcher/reconcile/source-change to regen-enqueue translation
- area-index invalidation decisions for knowledge-tree mutations

Resulting ownership shape:

- `sync/watcher.py` becomes an edge observer only; it emits raw file and
  folder events and performs no manifest or runtime mutation
- `sync/daemon.py` keeps loop, scheduling, HTTP client ownership, and process
  lifecycle wiring only
- semantic handling of watcher events and child-discovery outcomes happens
  through application-owned services called by `sync/daemon.py`

### 5. Scan-heavy freshness checks are replaced with explicit invalidation seams

The steady state for freshness is not "never scan anything." Offline
correctness still requires filesystem discovery. The change in this plan is
that on-demand freshness stops depending on whole-tree summary scans and
start-of-day reconcile stops classifying every tracked area by default.

Approved invalidation design:

- `runtime.repository` owns a runtime dirty-set for knowledge paths that need
  reclassification or downstream refresh
- `application/query_index.py` owns area-index lifecycle against an explicit
  invalidation token or generation, not `rglob()`-based staleness checks
- summary writes, summary deletes, source add/remove/move, local-file add/remove,
  reconcile enqueue decisions, and folder moves must emit invalidation updates

Required behavior changes:

- `AreaIndex.is_stale()` stops scanning `knowledge/**/.brain-sync/insights/summary.md`
- `load_area_index()` rebuilds from explicit invalidation state, then clears or
  advances the relevant token
- startup reconcile may still walk the tree to discover present and missing
  areas, but `classify_folder_change()` runs only on candidate paths derived
  from the dirty-set, untracked-path discovery, and orphan cleanup, not on
  every tracked path on every startup

### 6. Observability becomes a typed operational event model

Usage telemetry remains, but it is no longer the only persisted operational
history.

Approved runtime event surface:

- runtime table: `operational_events`
- owner: `runtime.repository`
- durability: machine-local only
- write pattern: append-only

Required stable fields:

- `event_type`
- `created_utc`
- `session_id`
- `owner_id`
- `canonical_id`
- `knowledge_path`
- `outcome`
- `duration_ms`
- `details_json`

Required event families in this plan:

- source lifecycle: register, update, move, remove, child-request saved/cleared
- reconcile outcomes: path updated, missing marked, deleted, orphan cleaned, path enqueued
- watcher handling: folder move observed and applied
- regen lifecycle: enqueued, started, completed, failed
- query/index lifecycle: area index invalidated and rebuilt

The event model is not intended to become full event sourcing in this pass.
It is an operational trail for correlation, review reruns, and structural
debugging.

## Phased Workstreams

## Phase 1. Lock The REGEN Boundary

Primary owners:

- `regen/`
- `application/regen.py`
- `tests/unit/test_architecture_boundaries.py`

Goal:
Make REGEN callable through a small public API and stop broad barrel export
leakage before the larger refactor begins.

Required outcomes:

- `brain_sync.regen.__all__` contains only the approved public surface
- queue-only helpers move to `regen/topology.py` and stop appearing in the barrel
- `RegenQueue` imports REGEN internals from package-local modules, not through
  `brain_sync.regen`
- `application/regen.py` becomes the stable application bridge for full regen,
  path regen, and folder classification

Acceptance criteria:

- no underscore-prefixed REGEN symbol is exported from `brain_sync.regen`
- `sync/reconcile.py` and `sync/watcher.py` import no REGEN modules
- no transport module imports `brain_sync.regen` directly
- the transitional `sync -> regen` debt entries can be removed from the
  architecture boundary test

## Phase 2. Unify Runtime Persistence Ownership

Primary owners:

- `runtime/`
- `application/source_state.py`
- `application/insights.py`
- `docs/runtime/SCHEMAS.md`

Goal:
Finish runtime ownership unification so machine-local persistence has one
truthful write surface.

Required outcomes:

- `runtime.repository` becomes the sole supported runtime DB surface
- child requests and usage telemetry route through `runtime.repository`
- runtime table declarations live in one place
- runtime modules are split by concern behind that surface instead of acting as
  competing DB owners

Acceptance criteria:

- production code outside `runtime.repository` does not call `_connect()` or
  `sqlite3.connect()` for runtime DB access
- `runtime/child_requests.py` no longer declares or applies its own DDL
- `runtime/token_tracking.py` no longer resolves `RUNTIME_DB_FILE` or opens
  sqlite directly
- runtime schema docs describe the new authoritative surface and any new
  runtime tables added by this plan

## Phase 3. Extract Daemon And Watcher Policy

Primary owners:

- `application/child_discovery.py`
- `application/sync_events.py`
- `sync/daemon.py`
- `sync/watcher.py`

Goal:
Remove semantic policy from the long-running loop and the filesystem observer
without hiding that policy in a new sync-owned grab bag.

Required outcomes:

- child-discovery outcome handling moves into `application/child_discovery.py`
- watcher move application and structure-only regen decisions move into
  `application/sync_events.py`
- watcher emits raw events only
- daemon becomes a coordinator that calls named services

Acceptance criteria:

- `sync/watcher.py` performs no manifest mutation and no runtime mutation
- `sync/daemon.py` no longer calculates child placement paths inline
- request-clearing semantics are owned by `application/child_discovery.py`
- structure-only repair, `_core` invalidation, and queue-enqueue decisions are
  owned by `application/sync_events.py`

## Phase 4. Replace Scan-Heavy Freshness With Invalidation

Primary owners:

- `runtime.repository`
- `application/query_index.py`
- `query/area_index.py`
- `application/reconcile.py`
- `sync/reconcile.py`

Goal:
Make the hot freshness paths event-led while keeping offline correctness.

Required outcomes:

- query freshness uses explicit invalidation state, not summary-tree rescans
- startup reconcile narrows classification to candidate paths
- summary writes and source lifecycle changes emit invalidation updates

Acceptance criteria:

- `AreaIndex.is_stale()` no longer walks the summary tree
- query index rebuilds are driven by explicit invalidation state
- startup reconcile no longer calls `classify_folder_change()` across every
  tracked path by default
- offline correctness is still preserved by directory discovery for
  untracked and missing paths

## Phase 5. Add The Operational Event Model And Final Ratchets

Primary owners:

- `runtime.repository`
- `application/sources.py`
- `application/reconcile.py`
- `application/regen.py`
- `sync/daemon.py`
- `docs/architecture/ARCHITECTURE.md`
- `docs/runtime/SCHEMAS.md`

Goal:
Leave the system reviewable and diagnosable enough that the next architecture
review can mark it ready for major REGEN work.

Required outcomes:

- operational events are emitted at the required boundaries
- event fields are stable enough for correlation and review evidence
- docs describe the event model and invalidation seams truthfully
- tests ratchet the new ownership and event surfaces

Acceptance criteria:

- `operational_events` exists in the documented runtime schema
- the required event families are emitted from repository or application
  boundaries rather than transport-local code
- event writes are non-fatal and append-only
- the architecture review rerun can cite event evidence for source lifecycle,
  reconcile, watcher move handling, and regen ownership transitions

## Sequencing Rationale

Required order:

1. Phase 1: REGEN boundary
2. Phase 2: runtime persistence unification
3. Phase 3: daemon and watcher policy extraction
4. Phase 4: invalidation-driven freshness
5. Phase 5: operational event model and final ratchets

Why this order is fixed:

- the REGEN public boundary must be locked first so later extractions target
  the final seam instead of a barrel of internals
- runtime persistence must unify before invalidation and event work, otherwise
  new state will spread across multiple competing DB owners
- daemon and watcher extraction should happen after those seams exist so the
  policy lands on named services instead of new transitional shortcuts
- invalidation comes before the event model because the event seams should
  describe the chosen freshness architecture, not the old scan-heavy one
- the event model and review rerun are last because they should attest to the
  final ownership shape, not a moving intermediate state

## Required Test And Review Ratchets

The implementation is not complete unless it adds these ratchets:

- remove the `sync/reconcile.py` and `sync/watcher.py` transitional REGEN debt
  entries from `tests/unit/test_architecture_boundaries.py`
- add a runtime persistence guard that fails if production code outside
  `runtime.repository` opens sqlite or imports `_connect()`
- add unit tests for `application/child_discovery.py` covering default child
  path calculation, duplicate-child handling, and request clearing
- add unit or integration tests for `application/sync_events.py` covering
  folder moves, structure-only repair, and `_core` invalidation
- add tests for query-index invalidation that prove no summary-tree rescan is
  needed on normal query paths
- add tests for startup reconcile candidate narrowing so it does not classify
  every tracked path
- add tests for operational event emission and stable fields
- rerun compatibility tests proving Brain Format `1.0` remains unchanged

## Exit Criteria

This plan is complete only when the follow-up architecture review can make all
of the statements below true:

- the verdict is no longer `Not Yet` for major REGEN refactor readiness
- the five findings from `2026-03-18-review-2.md` no longer appear as active
  blocking findings
- `Dependency direction and orchestration` scores at least `8`
- `State authority and persistence integrity` scores at least `8`
- `Workflow and data-flow clarity` scores at least `8`
- `Performance and scale behavior` scores at least `7`
- `Observability and diagnosability` scores at least `7`
- `Extensibility and refactor readiness` scores at least `8`
- no score in the rubric falls below `6`
- the expected breakpoints for a major REGEN refactor are limited to
  `src/brain_sync/regen/**`, `src/brain_sync/application/regen.py`, and
  `src/brain_sync/sync/daemon.py`
- Brain Format `1.0` and compatibility expectations remain unchanged

## Definition Of “REGEN Refactor Ready”

For this repository, “REGEN refactor ready” means all of the following are
measurably true at the same time:

- REGEN engine internals are not part of the supported import surface
- runtime DB writes and reads have one truthful owner
- watcher and daemon code no longer hide REGEN policy in edge handling
- query freshness and startup candidate selection are driven by explicit
  invalidation state rather than repeated whole-tree checks
- operational behavior can be reconstructed from typed runtime events with
  session, owner, canonical id, knowledge path, outcome, and timing fields

That is the steady state this plan approves. No alternative steady state is
left open in this revision.

## Next Step

Implementation may proceed under this approved revision.

If execution clarifications become material, record them in
`docs/plans/plan_architecture-hardening_3_notes.md`.

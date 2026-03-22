# Review

Plan reviewed: `docs/plans/PLAN_operational-events-hardening.md`
Reviewer: Codex
Date: 2026-03-22

## Verdict

Changes required.

Create a new plan revision that resolves the findings below. This review
artifact does not approve the plan and does not authorize implementation.

## Findings

### 1. The catalog boundary is still too implicit to implement without guesswork

The plan says the scope is "REGEN-facing and query-index-invalidating" flows,
but it does not convert that into an exact current-pass boundary. That leaves
material ambiguity in both implementation and enforcement.

Current code reality is broader than the migration list in Phase 2:

- `tests/unit/test_runtime_operational_event_callers.py` currently inventories
  callers in `application/local_files.py`, `application/query_index.py`,
  `application/sources.py`, `regen/engine.py`, `regen/queue.py`,
  `runtime/repository.py`, `sync/finalization.py`, `sync/lifecycle.py`, and
  `sync/reconcile.py`
- the same family, `query.index.invalidated`, is emitted in multiple modules
  today, including `application/query_index.py`, `sync/lifecycle.py`, and
  `regen/engine.py`
- Phase 2 names only `application/query_index.py`, `regen/engine.py`,
  `regen/queue.py`, `sync/lifecycle.py`, `sync/reconcile.py`, and
  `sync/finalization.py`, while `application/local_files.py`,
  `application/sources.py`, and `runtime.repository` still sit in the current
  caller inventory and current event surface

Because the plan does not enumerate the exact included and deferred emitters,
the implementer still has to guess:

- whether `application/local_files.py` is intentionally out of scope even
  though it drives query-index invalidation side effects
- whether `application/sources.py` is intentionally out of scope even though
  it remains in the caller inventory and emits `source.updated`
- whether runtime-owned child-request events are in scope only as examples or
  as mandatory catalog members for this pass
- which exact watcher/source/reconcile families are required for the upcoming
  REGEN refactor versus explicitly deferred

Required revision:

- add an explicit include/exclude table derived from the current caller
  inventory
- name the exact files that must be migrated in this pass
- name the exact files that are intentionally deferred
- name the exact event families/types covered in this pass, not just category
  labels such as "watcher/sync lifecycle events"
- add the minimum required-field matrix for those families as a concrete table,
  not examples only

Without that, the boundary is still narrow in intent but not narrow enough in
execution terms to prevent drift or partial coverage.

### 2. The persistence-owner enforcement is not strong enough yet

The plan correctly says `runtime.repository` must remain the only persistence
owner for `operational_events`, but the lasting enforcement described in the
plan is still too soft for that requirement.

The current concrete enforcement seam is mostly the caller inventory test for
`record_brain_operational_event(...)`. That is not sufficient to prove sole
persistence ownership:

- a new helper could write `operational_events` through `_connect(...)`
  directly
- a new module could import `sqlite3` and issue SQL outside
  `runtime.repository`
- a runtime-plane helper could bypass `record_brain_operational_event(...)`
  while still satisfying a caller-inventory test

This matters because the plan itself allows new helper modules under
`src/brain_sync/runtime/`, which is the exact shape where an ownership bypass
could look legitimate unless the test contract is explicit.

Required revision:

- add one explicit enforcement requirement that fails if any non-test module
  outside `src/brain_sync/runtime/repository.py` issues SQL against
  `operational_events`
- specify the detection strategy, for example an AST/text inventory that fails
  on `operational_events` SQL outside `runtime.repository`, or an equivalent
  stronger repository-level guard
- state that helper modules may call only the public repository seam and may
  not open sqlite or import private connection helpers for this table

Until that is explicit, the plan preserves the ownership rule as intention, not
as a strong enough implementation gate.

### 3. The retention/pruning acceptance gate weakens the required daemon wiring

Fixed Design Decision 4 says daemon startup should invoke operational-event
pruning during the normal runtime boot path. Phase 3 repeats that. But
Acceptance Criterion 3 weakens the requirement to a normal runtime path,
"ideally" alongside token pruning in daemon startup.

That wording reopens a key requirement the plan otherwise treats as settled:

- daemon startup could become optional rather than required
- a less-normal path could satisfy the acceptance text while missing the exact
  runtime coverage the plan claims to be adding
- review would have to guess whether a helper-only path, CLI-only path, or
  some later daemon hook is acceptable

The current code has a clear normal seam already:
`sync.daemon.run()` prunes `token_events` before the main loop. The plan should
lock the new behavior to that seam rather than leaving room for interpretation.

Required revision:

- make daemon startup in `sync.daemon.run()` the required prune hook, not an
  "ideal" example
- state where in startup sequencing the prune call must happen
- require proof that the normal daemon boot path invokes
  `prune_operational_events(...)`
- require proof that prune failure remains non-fatal on that same path

As written, the pruning design is directionally right but not yet concrete
enough for approval.

### 4. The documentation obligations are incomplete under the repository doc-authority rules

The plan currently requires updates to:

- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- relevant `README.md` text

That is not complete against this repository's own documentation governance.

Per `AGENTS.md`:

- `docs/runtime/` is the authority for runtime schema/config/daemon shapes
- `docs/sync/` is the authority for daemon/watch/reconcile/poll flow
  explanation and sync-specific process models
- `docs/architecture/` is explanatory system design, not the main home for
  daemon-flow details

This plan changes normal daemon startup behavior by adding operational-event
pruning to the runtime boot path. That is a `docs/sync/README.md` concern as
well as a runtime-schema concern.

Required revision:

- add `docs/sync/README.md` to the required documentation updates
- state that `docs/sync/README.md` must describe the daemon-startup placement
  of operational-event pruning at the flow/explanation level
- keep field/config detail in `docs/runtime/SCHEMAS.md`
- keep ownership/rationale summary in `docs/architecture/ARCHITECTURE.md`

Without that, the plan leaves a real doc-authority gap for the daemon-flow
change it is explicitly making.

## Summary

The plan is close, but it is not approval-ready yet. The main issues are:

- the catalog boundary and required-field matrix are still too implicit
- the sole-persistence-owner rule is not backed by a strong enough explicit
  enforcement strategy
- the prune-path acceptance language weakens the daemon-startup requirement
- the documentation update set misses the sync-flow authority home

The next revision should resolve those four points directly rather than adding
more general rationale.

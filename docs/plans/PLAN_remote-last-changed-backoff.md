# PLAN_remote-last-changed-backoff: Runtime Upstream Freshness For Poll Backoff

## Status

Planning artifact only. This document defines the intended remediation for the
current polling-backoff mismatch where source age is derived from local
materialization time rather than upstream source-change time.

This stage does not change product behavior. It records the intended schema,
adapter, lifecycle, rollout, and verification work for a later implementation
stage.

## Objective

Align polling backoff with upstream source freshness rather than local
materialization timing.

The implementation must preserve the distinction between:

- portable brain truth about what has been materialized locally
- machine-local runtime knowledge about when the upstream source last changed
- per-source adapter authority over what counts as a meaningful remote change

The intended user-visible outcome is:

- newly registered or re-materialized old content should not be polled as if it
  were newly changed
- long-stable remote content should back off quickly once the runtime knows its
  upstream age
- cross-device portable brain moves may temporarily differ in polling behavior,
  but each runtime should converge after re-establishing local upstream
  freshness state

## Authoritative Inputs

Implementation must treat these documents as the primary constraints:

- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/README.md`
- `AGENTS.md`

Implementation must also align with the current owning seams for runtime poll
state, source-state projection, adapter change detection, and lifecycle
materialization:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/sync/scheduler.py`
- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sources/base.py`
- `src/brain_sync/sources/confluence/__init__.py`
- `src/brain_sync/sources/confluence/rest.py`
- `src/brain_sync/sources/googledocs/__init__.py`
- `src/brain_sync/sources/googledocs/rest.py`
- `src/brain_sync/brain/manifest.py`

## Confirmed Findings

The current investigation established the following facts.

### 1. Poll-backoff age is currently derived from local materialization time

`sync_active_source_once()` computes the next interval from
`source_state.last_changed_utc`, but `SourceState.last_changed_utc` is an alias
for `materialized_utc`.

That means the scheduler currently answers "how old is this content?" with
"how long since brain-sync last materialized it locally?"

### 2. `materialized_utc` is not the same thing as upstream change time

A source may have:

- upstream content last changed months ago
- local materialization performed today because the source was newly added,
  re-fetched, repaired, or moved between machines

In those cases the current scheduler treats cold remote content as newly
changed, which keeps polling unnecessarily hot.

### 3. Portable brain truth should remain separate from runtime freshness hints

`materialized_utc` is part of the durable portable manifest contract and
currently means the local materialization event that settled brain content.

Reinterpreting that field as upstream change time would conflate local truth
with a machine-local scheduling input and would make existing naming and schema
meaning misleading.

### 4. Runtime polling state is the natural home for upstream freshness

The existing `sync_polling` runtime state already owns:

- last checked time
- current interval
- next check time

Upstream freshness used only to drive polling belongs in the same machine-local
runtime authority rather than in the portable brain manifest by default.

### 5. Adapter-specific "remote change" semantics are not uniform

Confluence version metadata is a plausible upstream freshness signal for this
workstream.

Google Docs currently has a known false-positive issue where a cheap version
change can overstate whether synchronized markdown content actually changed.

That means the runtime layer must not invent a global provider-agnostic notion
of "remote last changed." The owning adapter must decide what upstream change
signal is trustworthy enough for scheduling.

### 6. Rollout must account for existing runtime rows that lack the new field

After the new runtime field is introduced, existing `sync_polling` rows will
not have upstream freshness populated.

If the implementation does nothing else, upgraded runtimes could keep stale
`next_check_utc` and interval decisions that were derived from the wrong age
signal.

## Scope

In scope for the implementation stage:

- add a runtime-only upstream freshness field to the polling state schema
- plumb that field through runtime repository load/save and active source state
- teach source adapters to provide upstream freshness metadata where supported
- change poll-backoff computation to prefer runtime upstream freshness over
  manifest `materialized_utc`
- define rollout behavior for existing runtime rows so upgraded runtimes
  re-establish upstream freshness intentionally
- add tests for runtime migration, scheduling behavior, and provider-specific
  change-detection interactions
- update runtime, sync, and architecture docs where schema or authority meaning
  changes

## Non-goals

- no portable brain manifest field for upstream freshness in this phase
- no attempt to make cross-device runtimes produce identical schedules before
  each device has re-established local runtime freshness
- no broad redesign of the source-adapter protocol beyond the minimal fields
  needed to carry upstream freshness
- no change to the existing backoff tier thresholds unless required by review
- no generic central scheduler heuristic that overrides source-specific change
  semantics
- no attempt to solve every Google Docs change-detection edge case beyond the
  minimum needed so the new runtime field does not encode known false positives

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact identifies
a material issue.

### 1. `materialized_utc` remains local materialization truth

The implementation must preserve the current semantic boundary:

- `materialized_utc` means when local brain content was last successfully
  materialized
- it must not be repurposed to mean upstream last changed time

This preserves manifest honesty and avoids rewriting portable contract meaning
for a runtime scheduling concern.

### 2. A new runtime-only field will carry upstream freshness

Introduce a runtime field named `remote_last_changed_utc` in `sync_polling`
and the corresponding in-memory sync state.

This field represents the upstream freshness signal used for polling. It is
machine-local and may differ across runtimes until each runtime refreshes it.

### 3. Poll backoff will prefer `remote_last_changed_utc`

After the new field is available, interval computation should use
`remote_last_changed_utc` as the primary age signal.

Fallback behavior should remain safe when the field is absent or unavailable,
but the normal steady-state path should no longer derive source age from
`materialized_utc`.

### 4. Source adapters remain authoritative for meaningful remote change

The runtime and scheduler layers consume an adapter-provided upstream freshness
signal; they do not define provider semantics themselves.

Practical interpretation:

- Confluence may populate `remote_last_changed_utc` directly from reliable
  page-version metadata
- Google Docs must not advance the field based only on a cheap version signal
  if that signal is known to produce false-positive content changes for
  synchronized markdown

### 5. Rollout should intentionally invalidate stale scheduling rows

The upgrade path should not leave old `sync_polling` rows in place as if their
derived intervals were still trustworthy.

The implementation should intentionally clear or rebuild machine-local polling
rows so each active source is re-polled and the new upstream freshness field is
populated under the new semantics.

This is a runtime-only reset, not a portable brain rewrite.

## Workstreams

### Phase 0: Contract Clarification And Naming

Goals:

- make the local-versus-upstream timestamp boundary explicit before code changes
- define the precise meaning of the new runtime field

Implementation requirements:

- document that `materialized_utc` remains local materialization truth
- document that `remote_last_changed_utc` is a runtime-only polling input
- define whether the field means:
  - raw provider last modified time
  - or the adapter's best upstream timestamp for a change that matters to
    synchronized content

Primary modules and docs:

- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/sync/scheduler.py`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`

### Phase 1: Runtime Schema And State Projection

Goals:

- add durable machine-local storage for upstream freshness
- make the field available anywhere polling decisions are computed

Implementation requirements:

- add `remote_last_changed_utc` to `sync_polling`
- update runtime DB migration logic
- extend runtime load/save helpers for the new field
- extend active sync-state projection so `SourceState` exposes the field
- preserve safe behavior when reading older rows that do not yet have the field

Primary modules:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/source_state.py`

### Phase 2: Adapter Freshness Plumbing

Goals:

- let adapters supply upstream freshness intentionally
- keep provider-specific change truth in adapter-owned code

Implementation requirements:

- extend adapter result types as needed so a version check or fetch can carry
  upstream freshness metadata
- teach the Confluence path to capture upstream last-changed time during the
  cheap metadata check and/or full fetch path
- define the Google Docs behavior intentionally:
  - cheap version metadata may continue to detect "possible change"
  - but the implementation must not encode a false-positive upstream freshness
    advance if the synchronized markdown proves unchanged

Primary modules:

- `src/brain_sync/sources/base.py`
- `src/brain_sync/sources/confluence/__init__.py`
- `src/brain_sync/sources/confluence/rest.py`
- `src/brain_sync/sources/googledocs/__init__.py`
- `src/brain_sync/sources/googledocs/rest.py`

### Phase 3: Lifecycle Scheduling Switch

Goals:

- make runtime upstream freshness the primary backoff input
- keep local materialization truth untouched

Implementation requirements:

- update interval computation call sites to use `remote_last_changed_utc`
- define fallback behavior when the runtime field is absent:
  - initial post-upgrade repoll path
  - transient provider failures
  - sources without a trustworthy upstream timestamp
- ensure unchanged-source processing preserves:
  - `last_checked_utc`
  - existing fingerprint behavior
  - correct rescheduling

Primary modules:

- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/scheduler.py`
- `src/brain_sync/sync/pipeline.py`

### Phase 4: Rollout And Runtime Rebuild Behavior

Goals:

- prevent upgraded runtimes from carrying forward bad intervals derived from
  `materialized_utc`

Implementation requirements:

- choose one explicit rollout mechanism and document it:
  - clear `sync_polling` rows during migration
  - or perform a one-shot rebuild that removes stale `next_check_utc` /
    interval data and forces prompt rechecks
- ensure the rollout is runtime-only and does not rewrite portable source
  manifests solely to seed the new field
- define how missing or inactive sources are handled during the reset

Primary modules:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/application/doctor.py`

### Phase 5: Verification Coverage

Goals:

- prove the new schedule age source is correct
- prove rollout convergence on upgraded runtimes
- prevent provider-specific regressions

Implementation requirements:

- add runtime migration tests for the new `sync_polling` field
- add scheduler/lifecycle tests showing:
  - old remote content newly materialized today backs off according to remote
    age, not local materialization age
  - missing `remote_last_changed_utc` triggers the intended rollout / fallback
    path
- add adapter or integration tests for:
  - Confluence upstream freshness extraction
  - Google Docs false-positive version changes not incorrectly advancing the
    new runtime freshness field when markdown is unchanged
- update any affected compatibility-focused tests intentionally

Primary test areas:

- `tests/unit/`
- `tests/integration/`
- `tests/external/`

## Acceptance Criteria

The implementation is complete when all of the following are true.

1. Poll-backoff age for active sources is normally derived from runtime
   `remote_last_changed_utc`, not manifest `materialized_utc`.
2. `materialized_utc` still records local materialization timing and is not
   redefined to mean upstream freshness.
3. The runtime DB schema and state projection support the new field without
   breaking older-row reads during upgrade.
4. Upgrading an existing runtime intentionally invalidates or rebuilds stale
   poll scheduling so active sources are rechecked under the new semantics.
5. Confluence sources populate upstream freshness from adapter-owned metadata
   without requiring a portable manifest change.
6. Google Docs false-positive version changes do not incorrectly make the new
   runtime freshness field look newer when synchronized markdown is unchanged.
7. Documentation clearly describes the authority split between:
   - portable materialization state
   - runtime polling state
   - adapter-owned remote change semantics

## Risks And Review Focus

Reviewers should pay particular attention to these risks.

### 1. Field semantics drift

The plan uses the name `remote_last_changed_utc`, but implementation must still
decide whether that means raw provider last-modified time or the adapter's best
timestamp for meaningful synchronized-content change. That meaning must be made
explicit and then applied consistently.

### 2. Google false-positive handling could be under-specified

If the implementation simply records cheap Drive version changes as upstream
freshness, it may preserve the existing false-positive problem in a new place
and keep polling hotter than intended.

### 3. Rollout could be too timid

If old `sync_polling` rows are not invalidated or rebuilt intentionally, the
new field may exist but the effective schedule can still be governed by stale
pre-upgrade intervals for too long.

### 4. Rollout could be too aggressive

A full runtime-only polling reset is acceptable, but the plan should still make
sure the recheck storm is bounded and does not accidentally become a portable
manifest churn event.

## Open Questions For Review

These questions should be answered during review before approval.

1. Should `remote_last_changed_utc` mean raw upstream last-modified time, or
   the adapter's best timestamp for a change that affects synchronized content?
2. Is the rollout mechanism better expressed as:
   - a DB migration that clears `sync_polling`
   - or an application-level rebuild path that intentionally invalidates timing
     rows after upgrade?
3. For Google Docs, should semantic false-positive suppression live entirely in
   the adapter, or should the lifecycle layer gain an explicit "provider said
   changed but effective content was unchanged" branch?

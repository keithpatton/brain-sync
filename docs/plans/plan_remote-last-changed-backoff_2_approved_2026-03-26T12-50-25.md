# Approval

Approved: 2026-03-26T12-50-25
Approved by: codex-gpt-5

Notes:

- `materialized_utc` and runtime upstream freshness are now separated explicitly and consistently
- the Google Docs false-positive seam is fixed at the adapter boundary rather than deferred to shared lifecycle code
- the `v29 -> v30` migration-time `sync_polling` reset gives the rollout a deterministic, machine-local recovery path
- the runtime schema bump, doc-authority updates, and migration/compatibility proof obligations are specific enough for implementation
- cross-device runtime divergence is described honestly as temporary machine-local scheduling variance until each runtime refreshes its own freshness state

---

# PLAN_remote-last-changed-backoff Revision 2: Runtime Upstream Freshness For Poll Backoff

## Status

Approved plan artifact. This file copies
`docs/plans/plan_remote-last-changed-backoff_2_2026-03-26.md` as the
authoritative implementation handoff.

This approval covers a runtime-schema and scheduling-semantics change that:

- adds runtime-only upstream freshness to `sync_polling`
- preserves `materialized_utc` as portable local-materialization truth
- keeps Google Docs false-positive suppression in the adapter seam
- resets stale `sync_polling` rows during `v29 -> v30` migration so upgraded
  runtimes re-establish local freshness intentionally

Implementation may proceed from this approved artifact under the
`docs/plans/` workflow.

## Objective

Align polling backoff with upstream source freshness rather than local
materialization timing, while preserving the portable/runtime authority split.

The implementation must preserve the distinction between:

- portable brain truth about what has been materialized locally
- machine-local runtime knowledge used to schedule future polls
- adapter-owned semantics for what counts as a meaningful upstream content
  change

The intended user-visible outcome is:

- newly registered or re-materialized old content is not polled as if it were
  newly changed upstream
- long-stable remote content backs off quickly once the local runtime
  establishes trustworthy upstream freshness
- different machines may temporarily use different polling schedules for the
  same portable brain, and convergence happens only after each machine
  re-establishes its own runtime freshness state

## Authoritative Inputs

Implementation must treat these documents as the primary constraints:

- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/plans/README.md`
- `AGENTS.md`

Implementation must also align with the current owning seams for runtime poll
state, source-state projection, adapter change detection, lifecycle
materialization, and compatibility coverage:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/runtime/paths.py`
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
- `tests/compat/test_brain_format_v1.py`
- `tests/unit/test_state.py`

## Confirmed Findings

The current investigation established the following facts.

### 1. Poll-backoff age is currently derived from local materialization time

`sync_active_source_once()` computes the next interval from
`source_state.last_changed_utc`, but `SourceState.last_changed_utc` is an alias
for `materialized_utc`.

That means the scheduler currently answers "how old is this content?" with
"how long since brain-sync last materialized it locally?"

### 2. `materialized_utc` is not upstream freshness

A source may have:

- upstream content last changed months ago
- local materialization performed today because the source was newly added,
  re-fetched, repaired, or moved between machines

In those cases the current scheduler treats cold remote content as newly
changed, which keeps polling unnecessarily hot.

### 3. Upstream freshness is runtime-only state

Upstream freshness used only to decide future polling is machine-local runtime
state, not portable brain truth.

It belongs with:

- `last_checked_utc`
- `current_interval_secs`
- `next_check_utc`

rather than in the portable source manifest.

### 4. Existing `last_changed_utc` read models currently mean local materialization

The current `last_changed_utc` alias and admin-read surfaces are compatibility
views over `materialized_utc`.

Silently changing those surfaces to mean upstream freshness would blur the
portable/runtime boundary and make existing naming dishonest.

### 5. Google Docs cheap version checks are not trustworthy as synchronized-content change truth

Google Docs currently has a known false-positive issue where a Drive version
change can overstate whether the synchronized markdown content actually
changed.

Any new upstream freshness field must therefore be defined around
adapter-confirmed synchronized-content change, not raw provider metadata alone.

### 6. Startup currently trusts persisted `sync_polling` timing rows

The daemon reuses `next_check_utc` and `interval_seconds` from persisted
`sync_polling` rows on startup.

If runtime rollout is not explicit, upgraded runtimes can continue honoring
stale pre-upgrade intervals that were derived from `materialized_utc`.

## Scope

In scope for the implementation stage:

- add a runtime-only upstream freshness field to `sync_polling`
- bump the runtime DB schema from `v29` to `v30`
- plumb the new field through runtime repository load/save and active source
  state
- change poll-backoff computation to prefer the new runtime freshness field
- reset stale `sync_polling` rows during the `v29 -> v30` migration
- teach Confluence and Google Docs adapters to provide or suppress upstream
  freshness according to explicit source-specific rules
- preserve existing `materialized_utc` semantics and existing
  `last_changed_utc -> materialized_utc` read-model meaning
- update runtime, sync, architecture, versioning, compatibility, and runtime
  reference docs
- add migration and compatibility tests for the new runtime schema row

## Non-goals

- no portable brain manifest field for upstream freshness
- no change to Brain Format `1.2`
- no silent redefinition of existing `last_changed_utc` compatibility views
- no attempt to make two machines produce identical schedules before each
  machine refreshes its own runtime freshness data
- no broad redesign of the source-adapter protocol beyond the fields needed to
  carry confirmed upstream freshness
- no change to backoff tier thresholds in this phase
- no provider-agnostic shared lifecycle heuristic for Google false positives

## Fixed Design Decisions

These decisions are settled for implementation.

### 1. `materialized_utc` remains portable local-materialization truth

`materialized_utc` continues to mean when local brain content was last
successfully materialized.

It must not be repurposed to mean upstream change time.

### 2. Existing `last_changed_utc` read models remain tied to `materialized_utc`

The existing `SourceState.last_changed_utc` compatibility alias and current
admin/listing views continue to expose local materialization timing.

This plan does not retarget those surfaces to runtime upstream freshness.

If a user-facing or admin-facing surface later needs upstream freshness, it
must add an explicit `remote_last_changed_utc` field rather than silently
changing the meaning of `last_changed_utc`.

### 3. `remote_last_changed_utc` means adapter-confirmed synchronized-content freshness

Introduce a runtime field named `remote_last_changed_utc` in `sync_polling`
and the corresponding in-memory runtime sync state.

Semantic contract:

- it is the upstream timestamp for the most recent adapter-confirmed change
  that affects the synchronized source content semantics for that source
- it is not automatically the provider's raw last-modified timestamp
- a provider timestamp may be used only when that adapter declares it a
  trustworthy proxy for synchronized-content change

Practical interpretation:

- Confluence may use page-version metadata as the authoritative upstream
  freshness timestamp for the synchronized page/comments contract
- Google Docs must not persist Drive version-change timing as
  `remote_last_changed_utc` unless the adapter has confirmed that the
  synchronized markdown semantics actually changed

### 4. Google Docs false-positive suppression lives in the Google adapter seam

False-positive suppression for Google Docs belongs in the Google Docs adapter
path, not in shared lifecycle or scheduler code.

Required behavior:

- `check_for_update()` may continue to treat Drive version change as a cheap
  "possible change" signal that justifies a fetch
- the shared lifecycle must not synthesize or overwrite
  `remote_last_changed_utc` for Google Docs from that cheap signal
- the Google adapter fetch path must compare fetched synchronized content
  against prior source state and only return `remote_last_changed_utc` when the
  Google adapter has confirmed an effective synchronized-content change

Shared lifecycle code may persist adapter-provided `remote_last_changed_utc`
but must not implement a Google-specific false-positive suppression branch.

### 5. Poll backoff will prefer runtime `remote_last_changed_utc`

After the new field is available, interval computation must use
`remote_last_changed_utc` as the primary age signal.

Fallback order:

1. `remote_last_changed_utc` when present
2. `materialized_utc` only as a temporary fallback for sources that have not
   yet re-established runtime freshness on the current machine
3. the existing base interval behavior when neither timestamp is available

This fallback is transitional and machine-local. The normal steady-state path
must not derive source age from `materialized_utc`.

### 6. Runtime schema version bumps from `v29` to `v30`

This work is an explicit runtime DB schema change.

The implementation must:

- bump `RUNTIME_DB_SCHEMA_VERSION` from `29` to `30`
- update `docs/VERSIONING.md` so the current runtime DB schema row becomes
  `v30`
- update `docs/COMPATIBILITY.md` so the current supported row for the shipping
  app version references runtime DB schema `v30`
- update `docs/runtime/README.md` and `docs/runtime/SCHEMAS.md` for the new
  `sync_polling` shape and `v30` summary

### 7. The authoritative rollout mechanism is `v29 -> v30` migration-time clearing of `sync_polling`

The rollout mechanism is fixed:

- during the runtime DB migration to `v30`, add `remote_last_changed_utc` to
  `sync_polling`
- then delete all rows from `sync_polling`

No application-level rebuild alternative is part of this plan.

Why this mechanism is authoritative:

- it prevents stale `next_check_utc` and `interval_seconds` rows from surviving
  the schema change
- it keeps the reset machine-local
- it does not rewrite portable manifests
- it relies on existing startup scheduling behavior for sources with no
  `sync_polling` row

### 8. First post-upgrade scheduling behavior is deterministic

After `v29 -> v30` migration:

- `sync_polling` exists with the new column and zero rows
- `load_active_sync_state()` still derives active sources from portable
  manifests
- `missing` sources remain excluded because active sync state already filters
  them out before polling
- deregistered or otherwise inactive sources have no manifest-backed active row
  and therefore do not re-enter polling

On the first daemon cycle after upgrade:

- every active non-missing registered source has no persisted polling row
- `_sync_scheduler_state()` therefore schedules each such source immediately
  under the existing no-row path

On the first successful post-upgrade source check:

- if the adapter can establish trustworthy upstream freshness during the cheap
  unchanged path, persist `remote_last_changed_utc` and compute the next
  interval from it without changing `materialized_utc`
- if the adapter cannot establish trustworthy upstream freshness during the
  cheap path, fall through to its normal fetch path
- if the check fails, preserve the existing error-backoff behavior; the source
  remains without `remote_last_changed_utc` until a later successful run

## Workstreams

### Phase 0: Contract And Authority Update

Goals:

- make the new runtime field semantics explicit before code changes
- update the authoritative doc trail for a runtime schema change

Implementation requirements:

- document `remote_last_changed_utc` as adapter-confirmed synchronized-content
  freshness
- document that `materialized_utc` and existing `last_changed_utc` read models
  remain local materialization surfaces
- update:
  - `docs/runtime/SCHEMAS.md`
  - `docs/runtime/README.md`
  - `docs/sync/README.md`
  - `docs/architecture/ARCHITECTURE.md`
  - `docs/VERSIONING.md`
  - `docs/COMPATIBILITY.md`

Primary modules and docs:

- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/sync/scheduler.py`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`

### Phase 1: Runtime Schema `v30` And Migration Reset

Goals:

- add durable machine-local storage for upstream freshness
- invalidate stale polling rows during upgrade

Implementation requirements:

- bump runtime schema version to `30`
- add `remote_last_changed_utc` to `sync_polling`
- implement the `v29 -> v30` migration so it:
  - adds the new column
  - deletes all rows from `sync_polling`
  - preserves other runtime tables and data not owned by `sync_polling`
- keep `source_lifecycle_runtime` untouched by this reset
- ensure the migrated DB advertises schema version `30`

Primary modules:

- `src/brain_sync/runtime/paths.py`
- `src/brain_sync/runtime/repository.py`

### Phase 2: Runtime State Projection And Scheduling Input Switch

Goals:

- make runtime upstream freshness available to scheduling
- preserve existing local-materialization read semantics

Implementation requirements:

- extend runtime load/save helpers for `remote_last_changed_utc`
- extend active runtime sync state so it carries the field explicitly
- keep existing `last_changed_utc -> materialized_utc` compatibility behavior
- change interval computation call sites to prefer
  `remote_last_changed_utc`
- ensure the first post-upgrade no-row path yields immediate scheduling for
  active non-missing sources

Primary modules:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/sync/scheduler.py`
- `src/brain_sync/sync/lifecycle.py`

### Phase 3: Confluence Adapter Freshness Plumbing

Goals:

- make Confluence populate trustworthy upstream freshness on the cheap path

Implementation requirements:

- extend adapter result types as needed so update checks and/or fetch results
  can carry `remote_last_changed_utc`
- teach Confluence page metadata reads to return the upstream page-version time
  used for synchronized-content freshness
- allow unchanged Confluence checks to persist that timestamp without forcing a
  full materialization when other unchanged-source conditions already hold
- preserve current Confluence portable truth behavior:
  - `materialized_utc` changes only on actual local materialization
  - `remote_fingerprint` remains the durable portable freshness token

Primary modules:

- `src/brain_sync/sources/base.py`
- `src/brain_sync/sources/confluence/rest.py`
- `src/brain_sync/sources/confluence/__init__.py`
- `src/brain_sync/sync/pipeline.py`

### Phase 4: Google Docs Adapter False-Positive Suppression

Goals:

- keep Google false-positive suppression source-specific
- prevent cheap Drive metadata from polluting runtime freshness

Implementation requirements:

- keep Drive version metadata as a preflight "possible change" signal only
- do not persist `remote_last_changed_utc` from `check_for_update()` when the
  cheap signal has not yet been confirmed by adapter-owned content comparison
- in the Google adapter fetch path, compare fetched synchronized content
  against prior source state and:
  - return `remote_last_changed_utc` only when effective synchronized-content
    change is confirmed
  - suppress `remote_last_changed_utc` advancement when the fetched content is
    effectively unchanged despite a version bump

Primary modules:

- `src/brain_sync/sources/base.py`
- `src/brain_sync/sources/googledocs/__init__.py`
- `src/brain_sync/sources/googledocs/rest.py`

### Phase 5: Compatibility, Migration, And Behavioral Verification

Goals:

- prove the runtime schema bump
- prove the migration reset behavior
- prove the new scheduling semantics and source-specific suppression behavior

Implementation requirements:

- update compatibility constants/tests for runtime schema `v30`
- add or update migration tests proving:
  - supported runtime DB `v23/v24/v25/v26/v27/v29 -> v30` in-place migration
  - unreleased runtime DB `v28 -> v30` in-place migration when encountered
  - `v29 -> v30` migration adds `remote_last_changed_utc` and clears all
    `sync_polling` rows
- add runtime schema tests proving `sync_polling` now includes
  `remote_last_changed_utc`
- add scheduler/lifecycle tests proving:
  - old remote content newly materialized today backs off according to remote
    age, not local materialization age
  - first post-upgrade active sources with no polling rows become immediately
    due
  - missing sources do not re-enter active polling after the migration reset
- add adapter/integration tests proving:
  - Confluence unchanged cheap checks populate `remote_last_changed_utc`
  - Google Docs version-only false positives do not advance
    `remote_last_changed_utc`
- update any compatibility-focused assertions that name the current runtime
  schema row or supported migration rows

Primary test areas:

- `tests/compat/`
- `tests/unit/`
- `tests/integration/`
- `tests/external/`

## Acceptance Criteria

The implementation is complete when all of the following are true.

1. Runtime DB schema version is `v30`, and `sync_polling` includes
   `remote_last_changed_utc`.
2. `materialized_utc` still records local materialization timing and is not
   repurposed to mean upstream freshness.
3. Existing `last_changed_utc` read models still resolve to
   `materialized_utc`; no silent semantic drift occurs there.
4. `remote_last_changed_utc` is defined and implemented as adapter-confirmed
   synchronized-content freshness, not as a generic raw provider timestamp.
5. `v29 -> v30` migration deletes all `sync_polling` rows after adding the new
   column.
6. After that migration, active non-missing registered sources become
   immediately due on the next daemon startup or state load path because they
   have no persisted polling rows.
7. Missing sources remain excluded from active polling after the migration
   reset.
8. Confluence unchanged cheap checks can persist `remote_last_changed_utc`
   without updating `materialized_utc`.
9. Google Docs cheap version false positives do not advance
   `remote_last_changed_utc`; suppression lives in the Google adapter seam.
10. `docs/runtime/README.md`, `docs/runtime/SCHEMAS.md`, `docs/sync/README.md`,
    `docs/architecture/ARCHITECTURE.md`, `docs/VERSIONING.md`, and
    `docs/COMPATIBILITY.md` are updated consistently for runtime schema `v30`.
11. Compatibility and migration tests cover the new current row and the new
    supported migration expectations into `v30`.

## Risks And Review Focus

Reviewers should pay particular attention to these implementation risks.

### 1. Confluence freshness overreach

The implementation should use Confluence page-version timing only for the
current synchronized page/comments contract and must not accidentally imply a
broader attachment-freshness promise than the existing Confluence adapter
contract supports.

### 2. Google suppression leaking upward

If the implementation adds Google-specific branching in shared lifecycle code,
it violates the source-adapter boundary this revision intentionally fixes.

### 3. Reset storm risk

Clearing `sync_polling` is intentional, but the first post-upgrade poll wave
must rely on the existing daemon sequencing and backoff logic rather than
introducing new concurrency or manifest churn.

### 4. Compatibility row drift

Because this is a runtime schema bump, docs and tests that still say `v29`
after implementation would leave the repository in an internally inconsistent
state even if the code works.

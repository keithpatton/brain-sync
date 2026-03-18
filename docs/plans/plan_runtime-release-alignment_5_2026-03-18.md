# plan_runtime-release-alignment_5

## Status

Plan revision 5.

This artifact completes Phases 0-3 of
`docs/plans/plan_runtime-release-alignment_4_approved_2026-03-18T18-38-21.md`
and records the concrete narrowing decisions required before any code changes.

This file is still a planning artifact. Implementation remains gated on a
normal review/approval outcome for this revision.

## Objective

Narrow the disputed `v25` runtime expansion to the smallest release-safe
runtime shape that preserves the approved runtime-failure-hardening work while
restoring the architectural baseline:

- portable brain state remains authoritative
- runtime DB remains machine-local, rebuildable, and non-authoritative
- guarded regen ownership semantics remain in force
- the same portable brain may change elsewhere while this machine is idle
- no runtime-only surface may become hidden durable truth

## Authoritative Inputs

Stable authority for this revision:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/runtime/README.md`
- stable cross-cutting sections of `docs/VERSIONING.md`
- stable cross-cutting sections of `docs/COMPATIBILITY.md`
- `docs/plans/plan_runtime-failure-hardening_3_approved_2026-03-18T15-47-10.md`
- `docs/plans/plan_runtime-release-alignment_4_approved_2026-03-18T18-38-21.md`

Code and tests reviewed for Phases 0-3:

- commit `6d7eb76` (`Harden regen and runtime ownership boundaries`)
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/application/reconcile.py`
- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/application/query_index.py`
- `src/brain_sync/application/sync_events.py`
- `src/brain_sync/application/source_state.py`
- `src/brain_sync/application/local_files.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/application/child_discovery.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/query/area_index.py`
- `tests/unit/test_state.py`
- `tests/unit/test_query_index.py`
- `tests/unit/test_reconcile_knowledge_tree.py`
- `tests/unit/test_sync_events.py`
- `tests/unit/test_runtime_operational_events.py`
- `tests/compat/test_brain_format_v1.py`
- `tests/e2e/test_git_clone_scenario.py`

The table-specific `v25` claims currently present in `docs/RULES.md`,
`docs/VERSIONING.md`, `docs/runtime/SCHEMAS.md`,
`docs/architecture/ARCHITECTURE.md`, and `docs/COMPATIBILITY.md` remain
provisional until implementation and validation finish.

## Phase 0: Freeze and Evidence Inventory

### Freeze

Further runtime-surface expansion remains frozen. No new runtime table, file,
or hidden authority path is authorized by this revision.

### Retained runtime-surface candidate inventory


| Item                    | Kind          | Original bug evidence                                                                                                 | Approved workstream                                            | Current code owner                                                                                       | Current docs                                                                                                                   |
| ----------------------- | ------------- | --------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| `dirty_knowledge_paths` | runtime table | none; introduced by `6d7eb76`, not named in the approved bug bundle evidence                                          | none; outside approved Workstreams 1-4                         | `runtime/repository.py` storage; consumed by `application/reconcile.py` and `application/sync_events.py` | `docs/RULES.md`, `docs/VERSIONING.md`, `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`                          |
| `path_observations`     | runtime table | none; introduced by `6d7eb76`, not named in the approved bug bundle evidence                                          | none; outside approved Workstreams 1-4                         | `runtime/repository.py` storage; consumed by `sync/reconcile.py` and `application/reconcile.py`          | `docs/RULES.md`, `docs/VERSIONING.md`, `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`                          |
| `invalidation_tokens`   | runtime table | none; introduced by `6d7eb76`, not named in the approved bug bundle evidence                                          | none; outside approved Workstreams 1-4                         | `runtime/repository.py` storage; consumed by `application/query_index.py`                                | `docs/RULES.md`, `docs/VERSIONING.md`, `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`, `docs/COMPATIBILITY.md` |
| `operational_events`    | runtime table | no primary bug anchor; secondary observability support for logging, lock-contention, and remote-missing investigation | bounded observability support for Workstreams 1, 3, and 4 only | `runtime/repository.py` storage; emitted by `application/*`, `regen/*`, and `runtime/repository.py`      | `docs/RULES.md`, `docs/VERSIONING.md`, `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`, `docs/COMPATIBILITY.md` |


### Helper inventory


| Item                                              | Kind                                                                                                | Original bug evidence        | Approved workstream                                  | Current code owner                                                  | Current docs                                                                   |
| ------------------------------------------------- | --------------------------------------------------------------------------------------------------- | ---------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `mark_knowledge_paths_dirty()`                    | helper for `dirty_knowledge_paths`                                                                  | none                         | none                                                 | `runtime/repository.py`                                             | none beyond table docs                                                         |
| `load_dirty_knowledge_paths()`                    | helper for `dirty_knowledge_paths`                                                                  | none                         | none                                                 | `runtime/repository.py`                                             | none beyond table docs                                                         |
| `clear_dirty_knowledge_paths()`                   | helper for `dirty_knowledge_paths`                                                                  | none                         | none                                                 | `runtime/repository.py`                                             | none beyond table docs                                                         |
| `load_path_observations()`                        | helper for `path_observations`                                                                      | none                         | none                                                 | `runtime/repository.py`                                             | none beyond table docs                                                         |
| `save_path_observations()`                        | helper for `path_observations`                                                                      | none                         | none                                                 | `runtime/repository.py`                                             | none beyond table docs                                                         |
| `load_invalidation_token()`                       | helper for `invalidation_tokens`                                                                    | none                         | none                                                 | `runtime/repository.py`                                             | none beyond table docs                                                         |
| `advance_invalidation_token()`                    | helper for `invalidation_tokens`                                                                    | none                         | none                                                 | `runtime/repository.py`                                             | none beyond table docs                                                         |
| `clear_invalidation_token()`                      | helper for `invalidation_tokens`                                                                    | none                         | none                                                 | `runtime/repository.py`                                             | none beyond table docs                                                         |
| `runtime.repository.invalidate_area_index()`      | helper spanning `dirty_knowledge_paths` and `invalidation_tokens`                                   | none                         | none                                                 | `runtime/repository.py`                                             | `docs/architecture/ARCHITECTURE.md` (current provisional query lifecycle text) |
| `rename_knowledge_path_prefix()`                  | helper updating `regen_locks`, `dirty_knowledge_paths`, and `path_observations` during folder moves | none                         | none                                                 | `runtime/repository.py` with policy in `application/sync_events.py` | `docs/architecture/ARCHITECTURE.md`                                            |
| `record_operational_event()`                      | helper for `operational_events`                                                                     | secondary observability only | observability support around Workstreams 1, 3, and 4 | `runtime/repository.py`                                             | `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`                 |
| `load_operational_events()`                       | read helper for tests only                                                                          | none                         | none                                                 | `runtime/repository.py`                                             | none beyond table docs                                                         |
| `application.query_index.invalidate_area_index()` | application lifecycle helper delegating to runtime invalidation                                     | none                         | none                                                 | `application/query_index.py`                                        | `docs/architecture/ARCHITECTURE.md`                                            |
| `application.query_index.load_area_index()`       | application lifecycle helper reading runtime invalidation token                                     | none                         | none                                                 | `application/query_index.py`                                        | `docs/architecture/ARCHITECTURE.md`                                            |


### Consuming workflow inventory


| Workflow                                                                    | Runtime surfaces used                                                                     | Original bug evidence                                                 | Approved workstream       | Current code owner                                                                | Current docs                        |
| --------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | --------------------------------------------------------------------- | ------------------------- | --------------------------------------------------------------------------------- | ----------------------------------- |
| startup tree scan (`scan_knowledge_tree`)                                   | `path_observations`                                                                       | none                                                                  | none                      | `sync/reconcile.py`                                                               | `docs/architecture/ARCHITECTURE.md` |
| startup tree reconcile (`reconcile_knowledge_tree`)                         | `dirty_knowledge_paths`, `path_observations`, `invalidation_tokens`, `operational_events` | none                                                                  | none                      | `application/reconcile.py`                                                        | `docs/architecture/ARCHITECTURE.md` |
| MCP cached area-index refresh (`_brain_lifespan`, `_get_index`)             | `invalidation_tokens`                                                                     | none                                                                  | none                      | `interfaces/mcp/server.py` with `application/query_index.py`                      | `docs/architecture/ARCHITECTURE.md` |
| query/placement/browser cache refresh (`query_brain`, placement suggestion) | `invalidation_tokens`                                                                     | none                                                                  | none                      | `application/browse.py`, `application/placement.py`, `application/query_index.py` | `docs/architecture/ARCHITECTURE.md` |
| watcher folder change handling                                              | `dirty_knowledge_paths`, `invalidation_tokens`, `operational_events`                      | none                                                                  | none                      | `application/sync_events.py`                                                      | `docs/architecture/ARCHITECTURE.md` |
| watcher folder move handling                                                | `dirty_knowledge_paths`, `path_observations`, `invalidation_tokens`, `operational_events` | none                                                                  | none                      | `application/sync_events.py`                                                      | `docs/architecture/ARCHITECTURE.md` |
| source registration/removal/move/reconcile invalidation                     | `invalidation_tokens`, `operational_events`                                               | none                                                                  | none                      | `application/sources.py`                                                          | `docs/architecture/ARCHITECTURE.md` |
| local file add/remove invalidation                                          | `dirty_knowledge_paths`, `invalidation_tokens`, `operational_events`                      | none                                                                  | none                      | `application/local_files.py`                                                      | none                                |
| child-discovery event emission                                              | `operational_events`                                                                      | none                                                                  | none                      | `application/child_discovery.py`                                                  | none                                |
| regen summary write/delete invalidation                                     | `dirty_knowledge_paths`, `invalidation_tokens`, `operational_events`                      | none                                                                  | none                      | `regen/engine.py`                                                                 | `docs/architecture/ARCHITECTURE.md` |
| regen queue event emission                                                  | `operational_events`                                                                      | WinError 5 and regen-failure evidence need clearer diagnostics        | Workstream 3 support only | `regen/queue.py`                                                                  | none                                |
| source lifecycle diagnostics                                                | `operational_events`                                                                      | Confluence `404` and source-missing evidence need clearer diagnostics | Workstream 4 support only | `application/sources.py`                                                          | none                                |


## Phase 1: Retrospective and RCA

### Confirmed user-visible failures

The following failure classes were confirmed by the approved bug plan evidence
trail, even where the raw local log files were not re-imported into this repo:


| Failure class                                                     | Evidence anchor from approved bug plan                                                                                           | Phase 1 conclusion                                                                                                                                               |
| ----------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| shared-log rollover blocked on Windows                            | `run_id=720ebb`, stderr rollover diagnostic                                                                                      | real user-visible issue, but Workstream 1 was explicitly validation-first and did not justify new runtime tables                                                 |
| historical uniqueness failure on `knowledge_path` ownership state | `sqlite3.IntegrityError: UNIQUE constraint failed: insight_state.knowledge_path`, mapped forward to `regen_locks.knowledge_path` | real bug class; approved Workstream 2 targeted guarded ownership semantics, not broader runtime invalidation state                                               |
| repeated `[WinError 5] Access is denied` retries                  | `run_id=0eaaed` repeated regen failures                                                                                          | real user-visible failure; approved Workstream 3 justified bounded retry/defer behavior and clearer lock classification, not new runtime invalidation tables     |
| Confluence upstream `404` treated as opaque processing error      | `run_id=a8192e` with repeated `404 Not Found` handling                                                                           | real user-visible failure; approved Workstream 4 justified missing-state classification through the existing lifecycle, not new query/runtime invalidation state |


### Validated overreach risks

The following risks are directly validated by the `6d7eb76` diff and current
tests/docs:

1. The implementation exceeded the approved bug bundle by adding four runtime
  tables and threading them through runtime decision paths unrelated to the
   named failure evidence.
2. Startup reconcile changed from classifying every tracked path against
  portable state to a narrower path chosen from machine-local
   `path_observations` plus `dirty_knowledge_paths`.
3. Area-index freshness changed from summary-mtime scanning in portable state
  to machine-local `invalidation_tokens`.
4. The branch widened observability into a durable runtime table
  (`operational_events`) plus new event writes across source, watcher,
   reconcile, query, and regen flows.
5. Compatibility, versioning, runtime-schema, and architecture docs were
  updated as though the broadened `v25` runtime shape was already settled.
6. Tests were expanded to validate the new `v25` shape and current helper
  semantics, which increased the risk of the overreach hardening into an
   assumed release contract.

### Open hypotheses and incomplete RCA areas

The following remain hypotheses or incomplete evidence areas and must not be
presented as closed RCA:

- the original `documents.url` uniqueness evidence remains unresolved because
the current code scan did not identify a live normal-path writer
- the repo evidence does not prove that `dirty_knowledge_paths` or
`path_observations` have already caused a shipped user-visible regression;
the problem is that their safety proof is incomplete and their retention was
not approved
- the repo evidence does not prove that `operational_events` is necessary for
release; it only proves that it can be append-only and non-fatal
- the repo evidence does not complete a full raw-log RCA for every historical
incident window cited in the approved bug plan

### Where implementation exceeded approved scope


| Implemented change in `6d7eb76`                                                                                                                                          | Why it exceeds the approved bug bundle                                                                           |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| added `dirty_knowledge_paths`, `path_observations`, `invalidation_tokens`, and `operational_events` to runtime schema `v25`                                              | none of these runtime surfaces were named in the approved Workstreams 1-4 scope                                  |
| replaced `AreaIndex.is_stale(root)` summary scan with machine-local invalidation-token freshness                                                                         | this changed query correctness and cache invalidation architecture rather than hardening one approved failure    |
| changed startup reconcile to machine-local observation narrowing                                                                                                         | this changed reconcile authority and candidate selection architecture rather than hardening one approved failure |
| expanded event writes across source admin, local-file workflows, watcher flows, reconcile, query, and regen                                                              | the approved bundle allowed diagnostics, but did not approve a broad new durable event surface                   |
| updated `docs/RULES.md`, `docs/VERSIONING.md`, `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`, and `docs/COMPATIBILITY.md` to present `v25` as supported | this made provisional overreach look release-settled before narrowing review had happened                        |


## Phase 2: Runtime Authority Audit


| Name                    | Owner                                                                                                                                 | Classification        | Authoritative input                                                              | Rebuild source                                                                                                                            | Stale-state behavior                                                                                                                  | Missing-row behavior                                                                                                                           | Divergent-other-machine behavior                                                                                                                                     | Delete-and-rebuild behavior                                                                   | Proposed outcome                                                   |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `dirty_knowledge_paths` | `runtime/repository.py` storage, policy consumed by `application/reconcile.py` and `application/sync_events.py`                       | advisory optimization | portable filesystem mutations and known application mutations under `knowledge/` | future filesystem mutations plus startup scan and direct enqueue paths                                                                    | stale rows over-classify or reclassify already-stable paths; current evidence does not justify keeping them                           | missing rows should not suppress correctness because known same-process flows still enqueue work and startup can rediscover filesystem changes | other machines have unrelated local dirty sets; rows cannot be shared authority                                                                                      | safe to drop; only local hints disappear                                                      | revert now                                                         |
| `path_observations`     | `runtime/repository.py` storage, policy consumed by `sync/reconcile.py` and `application/reconcile.py`                                | advisory optimization | current filesystem walk under `knowledge/`                                       | fresh startup scan of the knowledge tree                                                                                                  | stale rows can narrow candidate selection based on local observations rather than portable truth; retained safety proof is incomplete | missing rows force broader classification, which is acceptable                                                                                 | another machine's local observations are meaningless for this machine and cannot be authoritative                                                                    | safe to drop; startup reconcile falls back to broader filesystem classification               | revert now                                                         |
| `invalidation_tokens`   | `runtime/repository.py` storage, policy consumed by `application/query_index.py` and long-lived caches in browser/placement/MCP paths | correctness-critical  | portable summary files and `knowledge/` structure used by `AreaIndex`            | none that is safe while relying on machine-local tokens; correctness requires portable-state inspection or purely in-process invalidation | stale clean token can keep an in-memory `AreaIndex` alive after portable summary changes                                              | missing row with generation `0` still allows a cached generation-`0` index to remain live                                                      | another machine can update portable summaries while this machine's token stays unchanged, leaving query caches stale; this violates the stated architecture baseline | DB rebuild alone does not fix a live cached index if the current process keeps generation `0` | revert now; this surface fails retention in the narrowing effort   |
| `operational_events`    | `runtime/repository.py` storage, emitted by application and regen flows                                                               | observability only    | none; event rows are diagnostics derived from already-authoritative workflows    | not rebuilt; history is optional                                                                                                          | stale rows only make diagnostics older or noisier                                                                                     | missing rows lose observability only                                                                                                           | another machine has a different local event trail by design                                                                                                          | DB reset loses local history only                                                             | keep now, but only as append-only, unread, non-fatal observability |


### Phase 2 conclusion

`invalidation_tokens` is the decisive retention failure. Because it is
correctness-critical for long-lived cached `AreaIndex` instances, it cannot
remain as a runtime-only retained surface under this narrowing effort.

`dirty_knowledge_paths` and `path_observations` are advisory in intent, but
their retention was not approved and their cross-machine negative proof is not
present. They do not earn retention.

`operational_events` is the only disputed runtime surface that currently meets
the retention bar because:

- production code writes it only for diagnostics
- no production correctness path reads it as authority
- write failure is explicitly non-fatal
- deletion loses local history only

## Phase 3: Concrete Narrowing Decision

### Exact keep / revert / defer table


| Runtime surface candidate | Decision   | Exact reason                                                                                                                                                                      |
| ------------------------- | ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `dirty_knowledge_paths`   | revert now | not part of the approved bug bundle; advisory only; retained safety proof is incomplete; same-process enqueue plus filesystem-based startup reconcile are the authoritative paths |
| `path_observations`       | revert now | not part of the approved bug bundle; advisory only; startup reconcile must return to portable/filesystem-driven truth rather than machine-local candidate narrowing               |
| `invalidation_tokens`     | revert now | machine-local token freshness is correctness-critical for long-lived cached `AreaIndex` instances and fails retention under the approved baseline                                 |
| `operational_events`      | keep now   | observability-only, append-only, machine-local, non-fatal on write failure, and not used as authority in production code                                                          |


### Exact post-narrowing runtime-shape outcome

Selected outcome: rollback-policy option 2.

Keep runtime schema label `v25`, but treat pre-narrowing local DBs as
unsupported and rebuild them on explicit detection.

The narrowed target runtime shape is:

- `meta`
- `sync_cache`
- `child_discovery_requests`
- `regen_locks`
- `operational_events`
- `token_events`

The narrowed target runtime shape does **not** retain:

- `dirty_knowledge_paths`
- `path_observations`
- `invalidation_tokens`

### Exact behavior after narrowing

1. Startup reconcile must classify tracked areas from portable insight state
  plus live filesystem truth without relying on retained machine-local path
   narrowing tables.
2. `AreaIndex` freshness must return to a portable-state or in-process
  correctness path. A machine-local runtime token must not decide whether a
   long-lived cached index is still valid after portable changes elsewhere.
3. Folder-move runtime repair may continue to update `regen_locks`, but it
  must not depend on any reverted runtime invalidation table.
4. `operational_events` must remain append-only, best-effort, and entirely
  outside correctness decisions.

### Exact detection and rebuild/reset policy for provisional pre-narrowing local DBs

The implementation must treat a local runtime DB as provisional pre-narrowing
state and reset it before normal use when all of the following are true:

1. `meta.schema_version == 25`
2. the DB contains any of these tables:
  - `dirty_knowledge_paths`
  - `path_observations`
  - `invalidation_tokens`

Required reset behavior:

- delete the machine-local runtime DB files
- recreate the narrowed `v25` runtime schema on next open
- do not modify the portable brain
- do not attempt in-place preservation of the disputed table contents

This reset policy applies only to provisional pre-release local runtime DBs
created during the disputed branch work. It does not change the intended
released portable-brain compatibility story.

### Portable format decision

The narrowed branch still targets Brain Format `1.0`.

No portable-format change is authorized or required by Phases 0-3. If later
implementation discovers that one of the approved narrow bug fixes truly needs
a portable-format change, that must go through a separate explicit plan and
approval path.

### Compatibility and schema wording that remains provisional until implementation completes

Until Phase 6 passes:

- current `0.6.0` / `v25` compatibility wording remains provisional
- current table-specific `v25` text that still lists
`dirty_knowledge_paths`, `path_observations`, or `invalidation_tokens`
remains provisional and is expected to be withdrawn during Phase 6
- `operational_events` retention remains provisional until Phase 5 confirms
that no production correctness path reads it as authority

## Approved Phase 4-6 execution scope after this revision is approved

If this revision is approved, Phase 4 implementation is limited to:

- reverting `dirty_knowledge_paths`, `path_observations`, and
`invalidation_tokens` from code, tests, and provisional docs
- restoring startup reconcile and area-index freshness to non-authoritative
runtime behavior
- keeping `operational_events` only as observability-only runtime state
- preserving the already-approved narrow hardening workstreams from
`plan_runtime-failure-hardening_3_approved_2026-03-18T15-47-10.md`

Phase 4 may not:

- add any new runtime table or file
- silently keep any reverted surface under a different name
- preserve machine-local correctness decisions for query freshness or startup
reconcile through another hidden cache
- change Brain Format `1.0` without a separate explicit approval path

## Exit Criteria

This revision is ready for approval only when the reviewer can confirm that it:

- inventories every disputed runtime surface, its helpers, and its consuming
workflows
- distinguishes confirmed failures, overreach risks, and open hypotheses
- classifies every retained runtime-surface candidate, including
`operational_events`
- forces an exact keep/revert/defer decision for every disputed surface
- chooses one exact post-narrowing runtime-shape outcome
- defines one exact detection and rebuild/reset policy for provisional
pre-narrowing `v25` DBs
- keeps Brain Format `1.0` unchanged unless a later separate plan says
otherwise
- leaves no material narrowing decision for implementation-time guesswork


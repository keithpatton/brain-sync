# plan_source-lifecycle-hardening-v2_2_2026-03-20: Source Lifecycle Hardening V2 Revision 2

## Status

Plan revision 2.

This revision supersedes
`docs/plans/PLAN_source-lifecycle-hardening-v2.md` for review purposes and
answers
`docs/plans/plan_source-lifecycle-hardening-v2_review_1_2026-03-20.md`.

This is a planning artifact only. It is not an approval artifact and does not
authorize implementation.

## Objective

Close the hardening gaps left after commit `3cc93ec` without reopening the
approved lifecycle direction from round one.

This revision is an implementation contract for a closure round. It must:

- close same-source lifecycle serialization gaps without redesigning the
  subsystem
- make destructive finalization restart-safe with one explicit freshness rule
- make move/remove contention deterministic at CLI and MCP boundaries
- replace heuristic canonical-id admission with one shared normative contract
- define a bounded event-proof slice for lifecycle/finalization tests
- keep `operational_events` non-authoritative, best-effort, and allowed to
  duplicate

## Relationship To Prior Artifacts

This revision preserves the approved lifecycle architecture from:

- `docs/plans/plan_source-lifecycle-hardening_9_approved_2026-03-20T17-41-44.md`

and incorporates the implementation context recorded in:

- `docs/plans/plan_source-lifecycle-hardening_9_notes.md`

It does not redesign the source lifecycle subsystem. It narrows the remaining
guesswork left by revision 1 of the v2 plan.

## Authoritative Inputs

Primary planning authority for this revision:

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
- `docs/plans/PLAN_source-lifecycle-hardening-v2.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_9_approved_2026-03-20T17-41-44.md`
- `docs/plans/plan_source-lifecycle-hardening_9_notes.md`

Implementation and later review must also align with the current lifecycle code
and test seams:

- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/finalization.py`
- `src/brain_sync/sync/lifecycle_policy.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/application/sources.py`
- `tests/integration/test_source_finalization.py`
- `tests/system/test_finalize_missing_cli.py`
- `tests/mcp/test_finalize_missing_mcp.py`
- `tests/mcp/test_mcp.py`
- `tests/unit/test_cli_finalize_missing.py`
- `tests/unit/test_lifecycle_policy.py`

## Fixed Scope

In scope for this closure round:

- exact same-source lifecycle serialization for the participating write set
- one explicit current-session freshness field and finalization predicate
- deterministic handled conflict results for `move`, and the same handled lease
  conflict model for `remove`
- one shared exact-target canonical-id validator for lifecycle surfaces that
  accept canonical IDs
- a bounded `operational_events` lifecycle/finalization proof contract
- runtime schema, docs, and tests required by those contract changes

## Non-goals

- no Brain Format change
- no provider-adapter redesign
- no broad event-catalog refactor
- no bulk finalization feature
- no rewrite of unrelated CLI or MCP surfaces
- no daemon scheduling redesign beyond the serialization/freshness contracts
  defined here

## Implementation Boundary

The lifecycle hardening in this revision is enforced at the sync-owned
orchestration boundary:

- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/finalization.py`

Lower-level helpers in `brain/` and `runtime/` may provide primitives, but
they must not silently implement alternate lifecycle policy, alternate
freshness heuristics, or bypass paths that let callers mutate same-source
lifecycle state without the contracts defined below.

## Normative Contracts

### 1. Same-Source Lifecycle Serialization

For this revision, a **same-source lifecycle write** is any mutation for an
already-registered `canonical_id` that changes one or more of:

- portable source manifest lifecycle state or `knowledge_path`
- source-owned files or managed artifacts
- `sync_polling` membership for that source
- `source_lifecycle_runtime` coordination for that source

The participating write set and rule for each path are fixed by this table:

| Path | Participates | Rule | On active same-source lease owned by another writer |
|---|---|---|---|
| explicit `move_source` | yes | acquire lease before any file move or manifest/path rewrite | return handled `lease_conflict`; do not move files; do not rewrite manifest |
| explicit `remove_source` | yes | acquire lease before any source-owned file delete, runtime cleanup, or manifest delete | return handled `lease_conflict`; do not delete files; do not delete manifest/runtime rows |
| explicit `finalize_missing` | yes | acquire lease before any finalization preflight or destructive commit | use the documented finalization terminal state `lease_conflict`; do not finalize |
| root-backed registered-source materialization commit path (`process_source` / `process_prepared_source`) | yes | acquire lease before materialized file write, manifest materialization write, polling restore, or lifecycle cleanup | abort the source commit path with handled lease conflict at the orchestration seam; do not write source truth after the conflict is detected |
| same-source missing observation commit path (`observe_missing_source`) | yes | do not acquire a lease; fresh-read manifest and runtime row immediately before writing missing state and polling removal | skip that source for the pass and leave portable/runtime state unchanged |
| same-source rediscovery/path-repair writes inside `reconcile_sources` | yes | do not acquire a lease; fresh-read manifest and runtime row immediately before `sync_manifest_to_found_path()`, lifecycle-row cleanup, or polling restore | skip that source for the pass and leave portable/runtime state unchanged |
| watcher batch path rewrites in `apply_folder_move()` / `apply_folder_move_to_manifests()` | yes | do not acquire per-source leases up front; for each affected manifest, check the current source lease immediately before rewriting that manifest | skip leased sources individually; do not rewrite those manifests in the batch |

The following paths do not participate in same-source serialization for this
round because they do not mutate existing registered-source lifecycle truth:

- `add_source`
- `update_source`
- child discovery request writes
- list/query/telemetry-only reads and events

Required enforcement details:

1. `move_source`, `remove_source`, `finalize_missing`, and the root-backed
   materialization commit path must use the source lease as the gate for their
   authoritative commit section.
2. `observe_missing_source`, reconcile path repair, reconcile rediscovery, and
   watcher batch path rewrites must fail closed by revalidation and skip, not
   by blindly overwriting leased state.
3. A skipped or lease-conflicted source must remain retryable. The current pass
   may return a handled conflict or skip result, but it must not leave partial
   same-source truth behind.
4. Review must be able to inspect the implementation and answer, per row in the
   table above, whether it acquires the lease or revalidates and skips. Any
   participating path not matching one of those two modes is a contract
   violation.

### 2. Restart-Safe Finalization Freshness Contract

This revision chooses one explicit freshness mechanism.

The implementation must introduce one runtime lifecycle session concept:

- every CLI invocation that can perform source lifecycle writes has exactly one
  `lifecycle_session_id`
- every daemon process has exactly one `lifecycle_session_id` for its process
  lifetime
- every MCP server lifespan has exactly one `lifecycle_session_id`

The runtime schema must advance from `v27` to `v28` and add this required
field to `source_lifecycle_runtime`:

- `last_missing_confirmation_session_id TEXT`

`record_source_missing_confirmation()` must persist the current
`lifecycle_session_id` into
`source_lifecycle_runtime.last_missing_confirmation_session_id` every time it
records a confirmation.

Explicit finalization eligibility is exact. A source is eligible for
destructive finalization only when all of the following are true at commit
time:

1. the manifest still exists
2. the manifest still has `knowledge_state = missing`
3. a `source_lifecycle_runtime` row still exists
4. `missing_confirmation_count >= 2`
5. `last_missing_confirmation_session_id == current lifecycle_session_id`
6. no conflicting source lease is active

Required preflight behavior:

1. If condition 5 is false, finalization must record a fresh missing
   confirmation for the current `lifecycle_session_id`, persist it, emit
   `source.finalization_pending_confirmation`, and return
   `pending_confirmation`.
2. That first invocation must not finalize, even when the inherited row already
   had `missing_confirmation_count >= 2`.
3. A later invocation in the same current session may finalize if conditions
   1-6 are then true.
4. No alternate epoch, process-start timestamp, owner-id comparison, or
   heuristic freshness rule may be used in place of
   `last_missing_confirmation_session_id`.

This is the only freshness contract for restart safety in this round.

### 3. Deterministic Conflict Handling For `move` And `remove`

#### Shared application result states

The move lifecycle surface must use exactly these terminal result states:

- `moved`
- `lease_conflict`
- `not_found`

The remove lifecycle surface must use exactly these terminal result states:

- `removed`
- `lease_conflict`
- `not_found`

Normal lease contention is not an exceptional transport failure. It is a
handled lifecycle result.

#### CLI contract

`brain-sync move` must:

- print `Result: moved` on success
- print `Result: lease_conflict` when another lifecycle owner holds the source
  lease
- exit `0` for `moved`
- exit `1` for `lease_conflict` and `not_found`
- avoid raw tracebacks for ordinary lease contention

When `lease_conflict` is returned, CLI output must include:

- the canonical ID
- the requested destination path
- the lease owner when known

`brain-sync remove` must use the same handled conflict shape:

- print `Result: removed` or `Result: lease_conflict`
- exit `0` for `removed`
- exit `1` for `lease_conflict` and `not_found`
- avoid raw tracebacks for ordinary lease contention

#### MCP contract

`brain_sync_move` must return one of these payload shapes:

- success:
  - `status: "ok"`
  - `result_state: "moved"`
  - `canonical_id`
  - `old_path`
  - `new_path`
  - `files_moved`
- handled lease conflict:
  - `status: "ok"`
  - `result_state: "lease_conflict"`
  - `canonical_id`
  - `new_path`
  - `message`
  - `lease_owner` when known
- not found:
  - `status: "error"`
  - `error: "source_not_found"`
  - `source`

`brain_sync_remove` must use the same handled conflict model:

- `status: "ok"` with `result_state: "removed"` or `result_state: "lease_conflict"`
- `status: "error"` with `error: "source_not_found"` for not found

`move` and `remove` lease conflicts are expected product behavior. Raw
transport exceptions for those cases are a contract violation.

### 4. Shared Canonical-Id Validation Contract

This revision requires one shared validator for **exact-target registered-source
canonical IDs**.

The owned contract is:

- trim is not allowed; the supplied string must already be exact
- empty strings are invalid
- URLs are invalid
- filesystem paths are invalid
- comma-separated or bulk targets are invalid
- attachment/image/helper canonical IDs are invalid lifecycle targets in this
  round
- the only valid source-target forms in this round are:
  - `confluence:<digits>`
  - `gdoc:<id>` where `<id>` matches `[A-Za-z0-9_-]+`
  - `test:<id>` where `<id>` matches `[A-Za-z0-9_-]+`

Ownership rule:

- this validator must live below CLI and MCP so interfaces do not keep private
  regex heuristics
- `application.sources.finalize_missing()` or an equivalent shared
  application-facing seam must call it so direct callers, CLI, and MCP share
  the same contract

Required user-facing lifecycle surfaces that must use this validator:

- CLI `brain-sync finalize-missing <canonical-id>`
- MCP `brain_sync_finalize_missing(canonical_id=...)`
- any new exact-target lifecycle surface introduced during this round

Surfaces that intentionally accept URL-or-canonical-id resolution, such as
`move` and `remove`, must continue to use the source resolver instead of the
exact-target canonical-id validator.

Failure behavior is exact:

- CLI: print `finalize-missing requires a canonical ID, not a URL, path, or bulk target.` and exit `1`
- MCP: return
  `{"status":"error","error":"invalid_canonical_id","message":"brain_sync_finalize_missing requires a canonical_id, not a URL or bulk target."}`

### 5. `operational_events` Proof Contract

`operational_events` remains:

- append-only
- machine-local
- non-authoritative
- not a replay source
- best-effort

Event write failure must never invalidate or roll back already-committed source
truth.

Event delivery is not exact-once. Duplicate rows are allowed during retries,
restart recovery, or overlapping writers. Tests must not assert exact row
counts for the lifecycle/finalization slice below.

#### Minimum lifecycle/finalization slice

Under a healthy runtime DB, the implementation must attempt to emit at least
this bounded slice:

| Event type | Outcome | Required stable fields | Required `details_json` keys |
|---|---|---|---|
| `source.missing_confirmed` | `missing` | `event_type`, `created_utc`, `canonical_id`, `knowledge_path`, `outcome` | `missing_confirmation_count` |
| `source.rediscovered` | `rediscovered` | `event_type`, `created_utc`, `canonical_id`, `knowledge_path`, `outcome` | `revalidation_basis` when emitted from finalization preflight |
| `source.finalization_pending_confirmation` | `pending_confirmation` | `event_type`, `created_utc`, `canonical_id`, `knowledge_path`, `outcome` | `missing_confirmation_count`, `revalidation_basis` |
| `source.finalization_lease_conflict` | `lease_conflict` | `event_type`, `created_utc`, `canonical_id`, `outcome` | `lease_owner` when known |
| `source.finalization_not_missing` | `not_missing` | `event_type`, `created_utc`, `canonical_id`, `knowledge_path`, `outcome` | `revalidation_basis` when known |
| `source.finalization_not_found` | `not_found` | `event_type`, `created_utc`, `canonical_id`, `outcome` | none |
| `source.finalized` | `finalized` | `event_type`, `created_utc`, `canonical_id`, `knowledge_path`, `outcome` | `missing_confirmation_count`, `revalidation_basis` |

#### Test proof rules

Tests may rely on:

- `load_operational_events()` ordering by append order
- existence of at least one matching event for the expected terminal result
- relative order between prerequisite and terminal events for one
  `canonical_id`
- stable field values listed in the table above

Tests must not rely on:

- exact row counts
- absence of duplicate rows
- the event table as the source of lifecycle truth
- timestamps alone as the only ordering proof when row order is available

## Runtime Schema And Documentation Obligations

This round changes runtime schema and must do so intentionally.

Required runtime/schema work:

1. bump runtime DB schema from `v27` to `v28`
2. migrate existing `source_lifecycle_runtime` rows to include
   `last_missing_confirmation_session_id`
3. update `src/brain_sync/runtime/paths.py`
4. update runtime migration tests for `v27 -> v28`

Required documentation updates:

- `docs/runtime/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `README.md`

Required doc content changes:

- name runtime schema `v28` as current once implemented
- document `last_missing_confirmation_session_id`
- document the `lifecycle_session_id` freshness rule as the only restart-safe
  finalization predicate
- document the exact-target canonical-id contract for `finalize-missing`
- document that lifecycle event emission is best-effort and may duplicate

This revision does not change Brain Format `1.2`.

## Acceptance Criteria

Implementation is not complete unless all of the following are true:

1. The participating same-source write set matches the serialization table in
   this plan.
2. Every participating path is implemented in exactly one of the two approved
   modes: `acquire lease` or `revalidate and skip`.
3. `remove_source` no longer bypasses an active same-source lifecycle lease.
4. The root-backed materialization commit path cannot commit same-source truth
   after a conflicting remove or move wins first.
5. Runtime schema `v28` exists and adds
   `last_missing_confirmation_session_id` to `source_lifecycle_runtime`.
6. Explicit finalization uses the exact six-part eligibility predicate defined
   in this plan.
7. A carried-forward runtime row from an earlier lifecycle session does not by
   itself permit immediate finalization after restart or re-attachment.
8. The first finalization invocation in a new lifecycle session against an
   inherited missing row returns `pending_confirmation` after recording fresh
   session confirmation.
9. `brain-sync move` and `brain_sync_move` implement the exact handled
   conflict contract in this plan and never leak raw exceptions for ordinary
   lease contention.
10. `brain-sync remove` and `brain_sync_remove` implement the same handled
    lease-conflict model.
11. Finalization canonical-id validation is owned by one shared validator and
    the required surfaces use it.
12. Invalid exact-target finalization input returns the exact CLI and MCP
    failure behavior defined in this plan.
13. `source_lifecycle_runtime` remains non-authoritative cached history and
    successful non-missing lease-owned operations do not leave empty rows
    behind.
14. The minimum lifecycle/finalization event slice is emitted in nominal runs
    with the required stable fields.
15. Lifecycle event emission is documented and tested as best-effort and
    duplicate-tolerant rather than exact-once.
16. `docs/runtime/SCHEMAS.md`, `docs/runtime/README.md`, `docs/RULES.md`,
    `docs/architecture/ARCHITECTURE.md`, `docs/VERSIONING.md`,
    `docs/COMPATIBILITY.md`, and `README.md` are updated consistently with the
    implemented contract.

## Test Fortress Expectations

The implementation and review must land coverage at these levels.

### Unit

- canonical-id validator accepts only the exact allowed source-target forms
- canonical-id validator rejects URLs, paths, bulk targets, whitespace-padded
  values, and attachment/image canonical IDs
- finalization eligibility tests cover the exact six-part predicate
- finalization eligibility tests prove that
  `last_missing_confirmation_session_id != current lifecycle_session_id`
  forces `pending_confirmation`
- move result-shaping tests cover `moved`, `lease_conflict`, and `not_found`
- remove result-shaping tests cover `removed`, `lease_conflict`, and
  `not_found`
- policy or orchestration tests pin which participating paths acquire the lease
  and which revalidate and skip
- operational event tests pin the stable fields and required `details_json`
  keys for the minimum slice

### Integration

- inherited `missing_confirmation_count >= 2` plus an old session ID does not
  finalize on the first call in a new lifecycle session
- the second qualifying call in the same lifecycle session can finalize when
  all other predicates hold
- explicit remove overlapping a held source lease returns handled
  `lease_conflict` and leaves files/manifests/runtime rows intact
- materialization overlapping remove or move fails closed and does not commit
  stale same-source truth
- reconcile rediscovery/path-repair skips leased sources rather than rewriting
  them
- watcher folder-move manifest rewrites skip leased sources individually
- non-missing completion paths prune empty lifecycle rows
- ordered lifecycle/finalization events prove the expected terminal result
  without asserting exact row counts

### MCP

- `brain_sync_move` returns the exact handled `lease_conflict` payload
- `brain_sync_remove` returns the exact handled `lease_conflict` payload
- `brain_sync_finalize_missing` rejects invalid canonical IDs through the
  shared validator
- `brain_sync_finalize_missing` preserves the existing handled result contract
  for `pending_confirmation`, `lease_conflict`, `not_missing`, and `not_found`

### System

- CLI `finalize-missing` after restart with an inherited row returns
  `pending_confirmation` first and does not delete the source
- CLI `move` under held lifecycle lease prints `Result: lease_conflict` and
  exits `1`
- CLI `remove` under held lifecycle lease prints `Result: lease_conflict` and
  exits `1`
- CLI invalid canonical-id input for `finalize-missing` prints the exact error
  contract and exits `1`

### Compatibility

- runtime DB `v27 -> v28` migration preserves existing lifecycle rows
- runtime DB rebuild still preserves portable source truth
- carried-forward lifecycle rows after migration remain non-authoritative until
  revalidated by the current lifecycle session

### E2E

- daemon materialization racing CLI move
- daemon materialization racing CLI remove
- process stop/start with reused lifecycle rows proving the new
  session-freshness rule
- overlap assertions use `operational_events` as ordered proof of terminal
  outcome without asserting exact-once delivery

## Review Focus

The next review pass should answer these exact questions:

1. Is every participating same-source write path enumerated, and is each one
   clearly classified as `acquire lease` or `revalidate and skip`?
2. Does the plan use one explicit freshness field and one exact finalization
   predicate, with no optional alternative mechanism?
3. Are `move` and `remove` lease conflicts now defined as deterministic product
   behavior at CLI and MCP boundaries?
4. Is the canonical-id validator now a single owned contract with named input
   grammar and named required surfaces?
5. Does the event-proof slice name the minimum event types, stable fields, and
   duplicate-tolerant semantics tightly enough that tests do not imply
   exact-once delivery?

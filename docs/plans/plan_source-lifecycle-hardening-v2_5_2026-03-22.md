# plan_source-lifecycle-hardening-v2_5_2026-03-22: Finalization Simplification Follow-up Revision 3

## Status

Planning artifact only.

This revision supersedes:

- `docs/plans/plan_source-lifecycle-hardening-v2_3_2026-03-22.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_4_2026-03-22.md`

for this follow-up topic. It does not approve implementation by itself.

This revision resolves the remaining planning ambiguity by choosing a clean
runtime-schema end state for the unreleased `0.7` line: remove the
session-confirmation fields that no longer belong in the simplified
explicit-finalization model rather than carrying them forward as dead
observational baggage.

## Objective

Resolve the remaining `finalize-missing` product/implementation mismatch
without reopening the broader v2 source lifecycle hardening package.

This revision must:

- keep `missing` as a durable non-destructive holding state
- keep destructive cleanup explicit rather than automatic
- remove lifecycle-session identity as a functional gate for
  `finalize-missing`
- make command-time revalidation the single freshness check before destructive
  cleanup
- define the exact post-change CLI and MCP result contract
- remove the now-unneeded runtime confirmation/session fields from the shipped
  `0.7` runtime schema
- update docs, versioning, compatibility, and tests to match one coherent
  released contract
- keep the rest of the v2 same-source serialization and conflict model
  unchanged

## Relationship To Prior Artifacts

This revision is derived from:

- `docs/plans/PLAN_source-lifecycle-hardening-v2.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_2_approved_2026-03-20T22-05-57.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_2_notes.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_3_review_1_2026-03-22.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_4_2026-03-22.md`

It preserves the same bounded product simplification direction introduced in
revisions 3 and 4:

- `missing` remains a non-destructive holding state
- explicit `finalize-missing` remains the user-driven cleanup action
- command-time revalidation replaces same-session freshness as the functional
  deletion gate

This revision changes the schema/versioning choice from revision 4. Because
`0.7` has not yet shipped, the cleaner contract is to remove the no-longer-used
fields now rather than freeze them into the release as observational-only
legacy.

This revision does not reopen:

- same-source lease ownership for move/remove/materialize
- commit fences for soft paths
- daemon startup guard behavior
- source-scoped move/remove cleanup semantics

## Authoritative Inputs

Primary authority for this revision:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/sync/README.md`
- `README.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_2_approved_2026-03-20T22-05-57.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_2_notes.md`

Implementation and review must align with these code and test seams:

- `src/brain_sync/sync/finalization.py`
- `src/brain_sync/sync/lifecycle_policy.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/runtime/paths.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `tests/unit/test_lifecycle_policy.py`
- `tests/integration/test_source_finalization.py`
- `tests/system/test_finalize_missing_cli.py`
- `tests/mcp/test_finalize_missing_mcp.py`
- `tests/mcp/test_mcp.py`

## Problem Statement

The approved v2.2 contract used lifecycle-session freshness as part of explicit
finalization eligibility. That model works for long-lived daemon and MCP
processes, but it does not work for one-shot CLI invocations:

- each CLI `finalize-missing` call starts in a fresh process
- each fresh process receives a fresh lifecycle session ID
- the old `pending_confirmation` model therefore cannot complete in normal
  repeated CLI usage

The product model we actually want is simpler:

- `missing` is a durable non-destructive holding state
- explicit `finalize-missing` is the user's cleanup action for already-missing
  sources
- that cleanup should succeed when the source remains absent at command time
- that cleanup should fail closed to `not_missing`/`stale` when the source is
  found again

Once that simplification is chosen, the v28 runtime fields created only to
support same-session destructive eligibility no longer belong in the released
schema for `0.7`.

## Product Decisions For This Revision

### 1. Explicit finalization is single-call for already-missing sources

If a registered source is already in durable `knowledge_state = missing`,
`finalize-missing <canonical-id>` is a single explicit cleanup command.

The normal success path is:

- acquire the source lease
- revalidate current source presence
- if the source is still absent, finalize immediately in that same invocation

There is no residual multi-invocation or same-session confirmation gate.

Repeated CLI subprocess usage remains supported, but it is not a required extra
confirmation mechanism.

### 2. `pending_confirmation` is removed from the explicit finalization contract

After this revision, explicit `finalize-missing` no longer returns
`pending_confirmation`.

The exact terminal result set becomes:

- `finalized`
- `not_missing`
- `lease_conflict`
- `not_found`

This applies to both CLI and MCP.

### 3. Runtime schema advances to v29 and removes the now-dead confirmation/session fields

Because `0.7` has not yet shipped, the release should not carry forward the
intermediate v28 session-confirmation fields as dead compatibility baggage.

This revision therefore chooses:

- runtime schema bump from `v28` to `v29`
- removal from `source_lifecycle_runtime` of:
  - `missing_confirmation_count`
  - `last_missing_confirmation_session_id`
- removal of any runtime-schema semantics that describe those fields as part of
  explicit-finalization authorization

Related missing-observation timestamps may remain only if they still serve an
independent supported purpose outside explicit-finalization gating. If not,
they should be removed in the same schema cleanup rather than left as
unexplained residue. The implementation must make one explicit choice and
document it.

### 4. App version 0.7 ships with the cleaned schema, not the intermediate one

The released `0.7` contract should describe one coherent runtime story:

- Brain Format remains `1.2`
- runtime schema becomes `v29`
- explicit finalization no longer depends on lifecycle-session freshness

`docs/VERSIONING.md` and `docs/COMPATIBILITY.md` must describe `v29` as the
released `0.7` runtime schema.

### 5. The rest of the v2 lifecycle hardening package remains unchanged

This follow-up does not alter the previously landed contracts for:

- same-source lease ownership
- soft-path commit fences
- move/remove handled conflict behavior
- source-scoped move/remove cleanup
- daemon startup exclusion

## Fixed Scope

In scope for this follow-up:

- simplify `finalize-missing` eligibility so it is driven by:
  - manifest existence
  - `knowledge_state == missing`
  - no conflicting active lease
  - current source-file revalidation outcome
- remove `pending_confirmation` from explicit finalization results and
  transport contracts
- update CLI and MCP result shaping to the simplified contract
- bump runtime schema to `v29`
- remove the unneeded session-confirmation fields from
  `source_lifecycle_runtime`
- update migration logic and migration tests for the schema cleanup
- update all owning docs, including versioning and compatibility docs, so they
  describe the cleaned `0.7` contract
- add proof that real CLI subprocess usage can finalize an already-missing
  source in one explicit call
- add proof that rediscovery during explicit finalization still restores to
  `stale` and does not delete the source

## Non-goals

- no automatic deletion of missing sources
- no time-threshold or age-based finalization policy
- no change to the `missing` holding-state semantics outside explicit
  finalization
- no change to same-source lease ownership rules for move/remove/materialize
- no redesign of daemon or watcher behavior
- no reopening of broader v2 lifecycle-hardening scope

## Normative Contract Changes

### 1. Missing state remains durable and non-destructive

`knowledge_state = missing` remains a registered holding state. A source in
`missing`:

- stays registered
- is excluded from active polling
- may later be rediscovered and restored to `stale`
- may later be explicitly finalized by user action

No process may automatically unregister a source solely because it remains in
`missing`.

### 2. Explicit finalization freshness is current revalidation only

`finalize-missing` must acquire the source lease before finalization work and
must revalidate source presence immediately before destructive cleanup.

Destructive finalization is permitted only when all of the following are true
at commit time:

1. the manifest still exists
2. the manifest still has `knowledge_state = missing`
3. no conflicting active source lease exists
4. current source-file revalidation still finds the source absent

If current revalidation finds the source present again, finalization must not
delete it. Instead it must restore the source to `stale` through the existing
rediscovery repair path and return the handled `not_missing` result.

### 3. Post-change explicit-finalization result contract

The exact explicit-finalization result contract after this revision is:

- `finalized`
  - destructive cleanup completed
- `not_missing`
  - the source was found during finalization revalidation and restored to
    registered non-missing state
- `lease_conflict`
  - another lifecycle owner currently holds the source lease
- `not_found`
  - the source manifest no longer exists

`pending_confirmation` is no longer a supported explicit-finalization result.

CLI behavior must be updated to match:

- `Result: finalized` on success
- `Result: not_missing` when rediscovered during finalization revalidation
- `Result: lease_conflict` on held conflicting lease
- `Result: not_found` when the source manifest does not exist
- exit `0` for `finalized`
- exit `1` for `not_missing`, `lease_conflict`, and `not_found`

MCP behavior must be updated to match:

- success / handled results use the existing `status: "ok"` pattern with
  `result_state` in `{ "finalized", "not_missing", "lease_conflict" }`
- `not_found` remains `status: "error"` with the existing source-not-found
  shape
- `pending_confirmation` is removed from the supported payload contract

### 4. Runtime schema cleanup contract

Runtime schema `v29` must remove the explicit-finalization confirmation/session
fields that existed only for the unreleased intermediate v28 policy:

- `missing_confirmation_count`
- `last_missing_confirmation_session_id`

If `local_missing_first_observed_utc` and
`local_missing_last_confirmed_utc` are retained, the docs must state the
independent supported purpose they still serve. If no such supported purpose
remains after this simplification, they must also be removed in `v29`.

The revision must not leave behind ambiguous fields whose only prior meaning
was the removed same-session deletion gate.

## Acceptance Criteria

Implementation is not complete unless all of the following are true:

1. Real CLI `brain-sync finalize-missing <canonical-id>` can finalize an
   already-missing, still-absent source in one explicit invocation.
2. Real CLI `brain-sync finalize-missing <canonical-id>` returns
   `Result: not_missing` and preserves registration when the source is found
   during finalization revalidation.
3. MCP `brain_sync_finalize_missing` follows the same simplified result
   contract and no longer exposes `pending_confirmation`.
4. Runtime DB schema is bumped to `v29`, and the removed
   confirmation/session-gate fields are no longer present in the shipped
   schema.
5. Migration and compatibility tests cover the supported upgrade path to `v29`
   and prove that older runtime DBs migrate or rebuild cleanly without
   changing durable portable source truth.
6. `docs/RULES.md`, `docs/sync/README.md`, `docs/runtime/README.md`,
   `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`,
   `docs/VERSIONING.md`, `docs/COMPATIBILITY.md`, and `README.md` no longer
   describe same-session confirmation as a required finalization gate.
7. Those docs describe `0.7` as shipping with runtime schema `v29`, not the
   intermediate `v28` contract.
8. Tests no longer rely on injected stable lifecycle-session IDs to prove the
   normal success path for explicit finalization.
9. The implementation notes file records that this follow-up intentionally
   simplified explicit finalization and cleaned the unreleased `0.7` runtime
   schema to remove dead session-confirmation semantics.

## Test Expectations

### Unit

- finalization policy tests reflect the simplified single-call predicate
- unit tests prove `pending_confirmation` is no longer part of the explicit
  finalization contract
- runtime migration tests cover the new `v29` shape and removed columns

### Integration

- explicit finalization of a still-missing source succeeds without injected
  same-session orchestration
- rediscovery before finalization commit restores to `stale` and does not
  delete source-owned artifacts

### MCP

- explicit finalization success path works without a same-session confirmation
  gate
- handled `not_missing`, `lease_conflict`, and `not_found` contracts remain
  intact
- `pending_confirmation` is no longer returned by the explicit finalization
  surface

### System

- one normal CLI subprocess invocation can move a source from `missing` to
  `finalized` when it remains absent
- one normal CLI subprocess invocation returns `not_missing` and preserves
  registration when the source is rediscovered before destructive cleanup
- CLI exit-code and printed-result behavior matches the exact contract above

### Compatibility

- the supported upgrade path for `0.7` now ends at runtime schema `v29`
- compatibility docs explain that the unreleased v28 confirmation/session gate
  was replaced before release and is not the shipped `0.7` contract
- migration/rebuild behavior preserves portable truth during upgrade to `v29`

## Review Focus

The review pass for the implementation derived from this revision should answer
these exact questions:

1. Did the implementation remove lifecycle-session identity from the
   functional finalization predicate rather than merely patching around the CLI
   bug?
2. Is `finalize-missing` now explainable as a single explicit cleanup command
   for an already-missing source, gated only by current revalidation and lease
   ownership?
3. Did the implementation remove `pending_confirmation` cleanly from the
   explicit-finalization CLI/MCP contract?
4. Did the runtime schema cleanup remove the dead confirmation/session fields
   rather than merely rebranding them?
5. Did docs, versioning, compatibility notes, and tests converge on one
   coherent `0.7`/`v29` contract?
6. Did the change stay bounded to finalization semantics rather than reopening
   broader lifecycle-hardening work?

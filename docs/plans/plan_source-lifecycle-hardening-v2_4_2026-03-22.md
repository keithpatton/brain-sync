# plan_source-lifecycle-hardening-v2_4_2026-03-22: Finalization Simplification Follow-up Revision 2

## Status

Planning artifact only.

This revision supersedes
`docs/plans/plan_source-lifecycle-hardening-v2_3_2026-03-22.md` for this
follow-up topic. It does not approve implementation by itself.

This revision resolves the blocking review findings against revision 3 by
choosing one exact explicit-finalization product model, one exact post-change
result contract, and one exact runtime-schema/versioning/compatibility posture.

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
- define the exact runtime-schema/versioning/compatibility posture for
  retained confirmation/session fields
- keep the rest of the v2 same-source serialization and conflict model
  unchanged

## Relationship To Prior Artifacts

This revision is derived from:

- `docs/plans/PLAN_source-lifecycle-hardening-v2.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_2_approved_2026-03-20T22-05-57.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_2_notes.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_3_2026-03-22.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_3_review_1_2026-03-22.md`

It responds specifically to the post-implementation adversarial review finding
that real CLI `finalize-missing` invocations cannot progress from
`pending_confirmation` to destructive completion because each CLI invocation
starts with a fresh lifecycle session.

This revision changes the approved v2 finalization freshness contract only for
the explicit `finalize-missing` path. It does not reopen:

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
- `src/brain_sync/application/sources.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `tests/unit/test_lifecycle_policy.py`
- `tests/integration/test_source_finalization.py`
- `tests/system/test_finalize_missing_cli.py`
- `tests/mcp/test_finalize_missing_mcp.py`
- `tests/mcp/test_mcp.py`

## Problem Statement

The current approved v2 contract uses lifecycle-session freshness as part of
explicit finalization eligibility. That model is coherent for long-lived daemon
and MCP processes, but it is not coherent for one-shot CLI invocations:

- `brain-sync finalize-missing <canonical-id>` runs in a new process each time
- each invocation receives a new lifecycle session ID
- the first invocation safely returns `pending_confirmation`
- the second invocation cannot satisfy the "same current session" predicate
  because it already belongs to a different session

That means the current approved contract is not just awkward; it is unusable at
the real CLI product boundary.

The intended product model is simpler:

- `missing` is a durable non-destructive holding state
- explicit `finalize-missing` is the user's cleanup action for already-missing
  sources
- that cleanup should succeed when the source remains absent at command time
- that cleanup should fail closed to `not_missing`/`stale` when the source is
  found again

## Product Decisions For This Revision

### 1. Explicit finalization becomes single-call for already-missing sources

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

### 3. Session and confirmation metadata become observational-only for finalization

Lifecycle-session identity, missing confirmation counts, and
`last_missing_confirmation_session_id` may still be retained in runtime state
and events for:

- diagnostics
- compatibility
- operational history

They are no longer part of the authorization predicate for explicit
finalization.

### 4. Runtime schema remains at v28 for this follow-up

This revision does not introduce a runtime schema bump.

The v28 runtime schema remains physically unchanged in this round, including
the retained `source_lifecycle_runtime` confirmation/session columns. Their
meaning changes:

- they remain supported runtime fields
- they remain populated where current code still records missing observations
- they are no longer normative gates for explicit finalization eligibility

This semantic change must be documented explicitly in:

- `docs/runtime/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/sync/README.md`
- `README.md`

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
- retain or simplify runtime confirmation/session tracking as observational-only
- update all owning docs, including versioning and compatibility docs, so they
  stop describing session freshness as a deletion gate
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
- no runtime schema bump in this round
- no removal migration for retained confirmation/session fields in this round

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

### 4. Retained session/confirmation fields are observational-only

For runtime schema `v28` after this revision:

- `missing_confirmation_count`
- `last_missing_confirmation_session_id`
- related missing-confirmation timestamps

remain valid runtime fields, but they are observational-only with respect to
explicit finalization.

They may still appear in:

- runtime rows
- `source.missing_confirmed` and related operational events
- diagnostics or internal observability helpers

They must not be documented or tested as required authorization inputs for
destructive finalization.

## Acceptance Criteria

Implementation is not complete unless all of the following are true:

1. Real CLI `brain-sync finalize-missing <canonical-id>` can finalize an
   already-missing, still-absent source in one explicit invocation.
2. Real CLI `brain-sync finalize-missing <canonical-id>` returns
   `Result: not_missing` and preserves registration when the source is found
   during finalization revalidation.
3. MCP `brain_sync_finalize_missing` follows the same simplified result
   contract and no longer exposes `pending_confirmation`.
4. `docs/RULES.md`, `docs/sync/README.md`, `docs/runtime/README.md`,
   `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`,
   `docs/VERSIONING.md`, `docs/COMPATIBILITY.md`, and `README.md` no longer
   describe same-session confirmation as a required finalization gate.
5. Tests no longer rely on injected stable lifecycle-session IDs to prove the
   normal success path for explicit finalization.
6. Runtime schema remains `v28`, and the retained confirmation/session fields
   are documented as observational-only rather than as functional deletion
   gates.
7. Compatibility and versioning docs explicitly record that this is a runtime
   semantics simplification without a schema bump.
8. The implementation notes file records that this follow-up intentionally
   simplified the approved v2 finalization contract for product coherence at
   the CLI boundary.

## Test Expectations

### Unit

- finalization policy tests reflect the simplified single-call predicate
- unit tests prove `pending_confirmation` is no longer part of the explicit
  finalization contract
- any retained session/confirmation helpers are tested only for observational
  behavior where still relevant

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

- existing `v28` runtime rows with retained confirmation/session fields remain
  readable without migration change
- compatibility docs explain that those fields remain supported but are no
  longer used as explicit-finalization gates

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
4. Did docs, versioning, compatibility notes, and tests stop overstating
   same-session confirmation as a required finalization contract?
5. Did the change stay bounded to finalization semantics rather than reopening
   broader lifecycle-hardening work?

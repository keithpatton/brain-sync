# plan_source-lifecycle-hardening-v2_3_2026-03-22: Finalization Simplification Follow-up

## Status

Planning artifact only.

This revision narrows the remaining post-implementation issue in the v2 source
lifecycle hardening work. It does not approve implementation by itself.

The purpose of this revision is to replace the currently approved
session-gated `finalize-missing` eligibility rule with a simpler explicit
revalidation contract that matches the supported CLI/MCP product model.

## Objective

Resolve the remaining `finalize-missing` product/implementation mismatch
without reopening the broader v2 lifecycle hardening work.

This revision must:

- keep `missing` as a non-destructive holding state
- keep destructive cleanup explicit rather than automatic
- remove lifecycle-session identity as a functional gate for
  `finalize-missing`
- make command-time source revalidation the single freshness check before
  destructive cleanup
- align docs, tests, and notes to the simplified contract

## Relationship To Prior Artifacts

This revision is derived from:

- `docs/plans/PLAN_source-lifecycle-hardening-v2.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_2_approved_2026-03-20T22-05-57.md`
- `docs/plans/plan_source-lifecycle-hardening-v2_2_notes.md`

It responds specifically to the post-implementation adversarial review finding
that real CLI `finalize-missing` invocations cannot progress from
`pending_confirmation` to destructive completion because each invocation starts
with a fresh lifecycle session.

This revision changes the approved finalization freshness contract only for the
explicit `finalize-missing` path. It does not reopen the same-source lease,
commit-fence, daemon-guard, or source-scoped move/remove work completed in the
v2 implementation series.

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
- `tests/integration/test_source_finalization.py`
- `tests/system/test_finalize_missing_cli.py`
- `tests/mcp/test_finalize_missing_mcp.py`

## Problem Statement

The current approved v2 contract uses lifecycle-session freshness as part of
explicit finalization eligibility. That model is coherent for the daemon and
MCP server because they have naturally long-lived process sessions, but it is
not coherent for one-shot CLI invocations:

- `brain-sync finalize-missing <canonical-id>` runs in a new process each time
- each invocation receives a new lifecycle session ID
- the first invocation can safely return `pending_confirmation`
- the second invocation cannot satisfy the "same current session" predicate
  because it is already a new session

This produces a real product break at the CLI boundary. The current
implementation can satisfy the session rule only in injected/in-process test
conditions, not in normal repeated command use.

The user-facing intent is simpler than the session-gated rule:

- `missing` is a durable, non-destructive holding state
- explicit `finalize-missing` is the user's cleanup action for already-missing
  sources
- that cleanup should succeed when the source is still missing at command time
  and should fail closed to `not_missing`/`stale` when the source is found
  again

## Product Decision For This Revision

The finalization freshness contract is simplified:

- lifecycle-session identity remains useful for diagnostics, event attribution,
  and other runtime observation
- lifecycle-session identity is no longer a functional gate for
  `finalize-missing`
- explicit `finalize-missing` freshness is defined by current command-time
  revalidation against the portable brain and filesystem, not by matching the
  prior missing confirmation to the current session ID

This preserves the important safety properties:

- explicit user action is still required
- destructive cleanup still revalidates current source absence at commit time
- rediscovery still wins over destructive cleanup
- watcher/reconcile remain non-destructive with respect to missing-source
  cleanup

It intentionally removes the two-step same-session confirmation requirement for
explicit finalization.

## Fixed Scope

In scope for this follow-up:

- simplify `finalize-missing` eligibility and result flow to remove
  session-gated confirmation
- update lifecycle policy logic, if needed, so finalization is driven by:
  manifest existence, `knowledge_state == missing`, no conflicting lease, and
  current revalidation outcome
- update CLI/MCP behavior and docs to match the simplified explicit-finalize
  model
- keep or simplify missing-confirmation/session tracking where it remains
  diagnostically useful without preserving it as a functional gate
- add proof that real CLI subprocess invocation can finalize after prior
  missing state when the source remains absent
- add proof that rediscovery during explicit finalization still restores to
  `stale` and does not delete the source

## Non-goals

- no automatic deletion of missing sources
- no time-threshold or age-based finalization policy
- no change to the `missing` holding-state semantics outside explicit
  finalization
- no change to same-source lease ownership rules for move/remove/materialize
- no redesign of daemon or watcher behavior
- no broad runtime-schema redesign unless implementation proves one field is
  now dead and safe to remove under normal compatibility rules

## Normative Contract Changes

### 1. Missing State Remains Explicitly Non-destructive

`knowledge_state = missing` remains a registered holding state. A source in
`missing`:

- stays registered
- is excluded from active polling
- may later be rediscovered and restored to `stale`
- may later be explicitly finalized by user action

No process may automatically unregister a source solely because it remains in
`missing`.

### 2. Explicit Finalization Freshness Is Command-Time Revalidation

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

### 3. Session Metadata Becomes Observational For Missing Confirmation

Missing confirmations and lifecycle session IDs may still be recorded in
runtime state and `operational_events`, but they are no longer part of the
authorization predicate for explicit finalization.

Implementation may retain the fields for compatibility or diagnostics, but
docs/tests must stop describing them as required for destructive eligibility.

## Acceptance Criteria

Implementation is not complete unless all of the following are true:

1. Real CLI `brain-sync finalize-missing <canonical-id>` can finalize a still-missing
   source through normal repeated subprocess usage.
2. Real CLI `brain-sync finalize-missing <canonical-id>` returns `not_missing`
   instead of deleting the source when the file is rediscovered before the
   destructive commit point.
3. MCP `brain_sync_finalize_missing` follows the same simplified explicit
   revalidation contract.
4. `docs/RULES.md`, `docs/sync/README.md`, `docs/runtime/README.md`,
   `docs/runtime/SCHEMAS.md`, `docs/architecture/ARCHITECTURE.md`, and
   `README.md` no longer describe same-session confirmation as the
   finalization gate.
5. Tests no longer rely on injected stable lifecycle-session IDs to prove the
   normal success path for explicit finalization.
6. If session/confirmation fields remain in runtime schema, they are described
   as observational or compatibility-retained rather than as functional
   deletion gates.
7. The implementation notes file records that this follow-up intentionally
   simplified the approved v2 finalization contract for product coherence at
   the CLI boundary.

## Test Expectations

### Unit

- finalization policy tests reflect the simplified predicate
- any retained session/confirmation helpers are tested only for observational
  behavior where still relevant

### Integration

- explicit finalization of a still-missing source succeeds without injected
  same-session orchestration
- rediscovery before finalization commit restores to `stale` and does not
  delete source-owned artifacts

### MCP

- explicit finalization success path works without assuming a same-session
  confirmation gate
- handled `not_missing`, `lease_conflict`, and `not_found` contracts remain
  intact

### System

- two normal CLI subprocess invocations can move a source from `missing` to
  `finalized` when it remains absent
- a CLI invocation against a rediscovered source returns `not_missing` and
  preserves registration

## Review Focus

The review pass for the implementation derived from this revision should answer
these exact questions:

1. Did the implementation remove lifecycle-session identity from the
   functional finalization predicate rather than merely patching around the CLI
   bug?
2. Is `finalize-missing` now explainable as explicit command-time revalidation
   plus destructive cleanup only when the source is still absent?
3. Did docs and tests stop overstating same-session confirmation as a required
   finalization contract?
4. Did the change stay bounded to finalization semantics rather than reopening
   broader lifecycle-hardening work?

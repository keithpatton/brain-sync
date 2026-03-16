# PLAN_portable-state-write-discipline: Portable State No-Op Write Discipline

## Status

Planning artifact only. This document defines the implementation plan for
ensuring that portable brain state is only rewritten when the durable portable
content has actually changed.

This stage does **not** implement the fix. It records the diagnosis, intended
invariant, scope, workstreams, and acceptance gates for later review and
implementation.

## Objective

Establish and enforce a repository-wide invariant:

> Portable brain state must only be altered when a real portable state change
> has occurred.

In practical terms, the implementation must ensure that:

- machine-local runtime repair operations do not rewrite portable state when
the portable bytes are unchanged
- lifecycle-only updates do not create git-visible changes in the brain root
- no-op or runtime-only operations do not create "ghost" portable diffs that
can later propagate across machines
- portable sidecars, manifests, and similar durable artifacts remain stable
across no-op operations

This matters not only for cleanliness of the working tree, but for correctness:
ghost portable changes can create confusion, mislead operators, trigger
unnecessary regen work, and cause unnecessary LLM cost.

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/brain-format/README.md`
- `docs/brain-format/RULES.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`

Implementation must also align with the current code seams that already own
portable-vs-runtime persistence and write behavior:

- `src/brain_sync/sidecar.py`
- `src/brain_sync/state.py`
- `src/brain_sync/regen.py`
- `src/brain_sync/commands/doctor.py`
- `src/brain_sync/fileops.py`
- `src/brain_sync/manifest.py`

## Context

The architecture and spec already define a durable/runtime split:

- portable insight hashes live in
`knowledge/**/.brain-sync/insights/insight-state.json`
- runtime regen lifecycle lives in `regen_locks`
- runtime DB state is rebuildable and machine-local

The current implementation violates the spirit of that separation in an
important way:

- `save_insight_state()` writes portable sidecar hashes and runtime lifecycle in
one operation
- some callers use that function for lifecycle transitions such as
`running`, `failed`, or `idle`
- `doctor --rebuild-db` loops through exported insight states and calls
`save_insight_state()` for every state, even when sidecar content is already
identical
- several regen paths call `save_insight_state()` and then separately call
`write_regen_meta()` again in the same flow

That means portable state can be rewritten:

- for runtime-only repair operations
- for lifecycle-only transitions
- for duplicate writes in the same logical operation
- even when the serialized sidecar content is unchanged

Observed effect:

- a runtime repair command can leave the brain repo showing modified portable
sidecar files
- those diffs can then be mistaken for meaningful portable changes and can be
pulled onto other machines

## Confirmed Diagnosis

The confirmed diagnosis to preserve during implementation review is:

1. Portable insight hash state and runtime regen lifecycle are currently
  persisted through a shared `save_insight_state()` path.
2. `save_insight_state()` writes the sidecar whenever `content_hash` is
  present, regardless of whether the portable sidecar bytes would actually
   change.
3. `doctor --rebuild-db` currently rewrites portable sidecars as part of a
  runtime DB rebuild even when the sidecar content is unchanged.
4. normal regen has a safe unchanged fast-path, but several non-no-op regen
  flows still write the sidecar redundantly through both `save_insight_state()`
   and direct `write_regen_meta()` calls.
5. the current behavior can produce git-visible portable changes that do not
  reflect any meaningful durable state transition.

## Scope

In scope for the implementation stage:

- defining an explicit no-op write invariant for portable state
- separating runtime lifecycle persistence from portable hash persistence where
needed
- making portable sidecar writes content-sensitive and no-op when serialized
bytes are unchanged
- ensuring `doctor --rebuild-db` rebuilds runtime state without rewriting
unchanged portable sidecars
- auditing regen flows for duplicate or unnecessary sidecar writes
- adding regression tests that prove no-op and runtime-only operations leave
portable files untouched
- documenting the invariant in the appropriate authoritative docs if review
concludes it should be explicit

## Non-goals

- no change to the Brain Format schema itself
- no weakening of sidecar authority for portable insight hashes
- no change to the portable location of insight-state files
- no change to the fact that actual portable hash changes must still be written
- no broad refactor of unrelated persistence APIs
- no attempt to eliminate all file rewrites during real portable changes

## Fixed Design Decisions

These decisions should be treated as settled unless review finds a material
architectural problem.

### 1. Portable no-op writes are correctness bugs, not cosmetic annoyances

This is not just a working-tree cleanliness issue.

If a runtime-only or no-op operation rewrites portable state, that can:

- create misleading git diffs
- cause confusion across machines
- make later diagnosis harder
- trigger unnecessary follow-on work

The implementation should therefore treat ghost portable rewrites as behavior
to eliminate, not as benign churn.

### 2. Portable and runtime persistence concerns should not be coupled by default

The current `save_insight_state()` coupling is too broad for the authority
model described in the docs.

The implementation should move toward an explicit separation between:

- portable hash persistence
- runtime lifecycle persistence

Callers should not have to write portable sidecars merely to record a
machine-local lifecycle transition.

### 3. Portable writes must be content-sensitive

Portable files may be rewritten only when their serialized durable content
actually changes.

The implementation should use a content-sensitive write path for sidecars,
whether by:

- teaching `write_regen_meta()` to skip identical bytes
- or introducing a shared "write bytes if changed" helper and routing sidecar
writes through it

This rule should apply even when the call site is otherwise valid.

### 4. `doctor --rebuild-db` should rebuild runtime state, not churn portable files

`doctor --rebuild-db` is conceptually a runtime repair command. It may read
portable state and reseed runtime state from it, but it should not rewrite
portable sidecars unless the portable sidecar content truly needs correction.

### 5. Duplicate sidecar writes in a single logical operation should be removed

A number of regen paths currently persist via `save_insight_state()` and then
call `write_regen_meta()` directly again. That pattern increases churn risk and
obscures the true persistence contract.

The implementation should reduce those flows to a single intentional portable
write per logical state transition.

### 6. The invariant may warrant documentation, not just code changes

If review agrees that "portable brain state changes only for meaningful durable
changes" is a long-lived system rule, it should be captured in the highest
appropriate authority document rather than existing only as an implementation
detail.

## Planned Workstreams

### Workstream 1: Persistence boundary analysis

Map the current persistence operations for insight state and classify them as:

- portable hash writes
- runtime lifecycle writes
- combined writes
- duplicate writes

This must cover at least:

- `state.save_insight_state()`
- `sidecar.write_regen_meta()`
- regen success, rename, similarity, running, and failure paths
- `doctor --rebuild-db`

Outcome:

- a concrete call-site inventory that shows which paths are supposed to mutate
portable state and which are runtime-only

### Workstream 2: API boundary redesign

Refine the persistence API so callers can express intent clearly.

Likely directions:

- split lifecycle-only DB persistence from portable sidecar persistence
- or preserve one façade but route it through narrower internal helpers with
explicit portable/runtime semantics

The chosen design must make it hard for a runtime-only operation to rewrite a
portable sidecar accidentally.

### Workstream 3: Content-sensitive sidecar writes

Update sidecar persistence so unchanged serialized content is not rewritten.

Candidate implementation directions:

- add a bytes-oriented no-op write helper in `fileops.py`
- update `write_regen_meta()` to compare existing serialized bytes before
writing
- ensure the behavior remains correct on Windows long paths as well as normal
paths

Outcome:

- portable sidecars are stable under no-op writes even if a caller reaches the
write path

### Workstream 4: Rebuild-db write discipline

Update `doctor --rebuild-db` so it reconstructs runtime DB state from portable
sidecars and manifests without rewriting unchanged portable sidecars.

Outcome:

- a runtime DB rebuild leaves the portable working tree clean when no portable
correction is needed

### Workstream 5: Regen flow cleanup

Audit regen flows for unnecessary portable rewrites and duplicate writes.

This must cover:

- structure-only rename handling
- backfill handling
- failure handling
- similarity-skip handling
- successful regen completion

Outcome:

- each logical regen outcome performs only the portable writes that outcome
actually requires

### Workstream 6: Tests

Add targeted regression tests that prove the invariant holds.

Candidate coverage:

- unit: sidecar write helper does not rewrite unchanged bytes
- unit or integration: lifecycle-only state persistence does not touch sidecar
- integration: `doctor --rebuild-db` preserves sidecar content and leaves
unchanged portable files untouched
- integration: regen unchanged path leaves sidecar untouched
- integration: real portable changes still update sidecar as expected
- integration: flows that previously double-wrote now perform a single durable
write

Tests should prefer observable outcomes such as:

- unchanged blob bytes
- unchanged `mtime` where appropriate
- clean git-compatible semantics

All test data must use placeholder values only.

## Proposed Implementation Strategy

1. Inventory all current call sites that write portable sidecars and classify
  whether each write is conceptually portable, runtime-only, or duplicate.
2. Introduce a content-sensitive sidecar write path that can no-op safely when
  bytes are unchanged.
3. Separate runtime lifecycle persistence from portable hash persistence at the
  API level or through narrower internal helpers.
4. Update `doctor --rebuild-db` to reseed runtime state without rewriting
  unchanged sidecars.
5. Remove or collapse duplicate sidecar writes in regen flows.
6. Add regression tests around rebuild-db, runtime-only transitions, and
  no-op sidecar writes.
7. If review agrees the invariant is long-lived, update the appropriate docs to
  state it explicitly.

## Verification

The implementation is complete only when all of the following hold:

1. `doctor --rebuild-db` resolves runtime drift without producing portable
  sidecar rewrites when the existing sidecar bytes are already correct.
2. Runtime-only lifecycle transitions do not rewrite portable sidecars.
3. A no-op sidecar persistence call leaves the file bytes unchanged and does
  not create a ghost durable diff.
4. Real portable hash changes still persist correctly.
5. Regen paths that previously double-wrote no longer perform redundant
  portable writes.
6. Existing behavior that depends on sidecar authority remains intact.
7. Windows-safe path handling remains correct for any new no-op write helper.
8. Tests cover both no-op and true-change cases.

## Risks and Review Focus

Reviewers should pay particular attention to:

- whether the proposed API split is clear enough to prevent future coupling
regressions
- whether content-sensitive writes preserve atomicity and crash safety
- whether mtime-based tests are robust enough or should be backed by direct
byte/hash assertions
- whether any failure path still rewrites portable state unnecessarily
- whether the plan should codify this invariant in `docs/brain-format/RULES.md`
or keep it as architecture/implementation guidance

## Open Questions

These should be resolved during review before implementation begins:

1. Should the fix primarily be an API separation change, a content-sensitive
  sidecar write change, or both? My expectation is both.
2. Should the invariant be documented in the Brain Format rules, or only in
  architecture documentation?
3. Is there any legitimate runtime-only scenario where rewriting an unchanged
  portable sidecar is still desirable? The current expectation is no.

## Expected Documentation Impact

No schema or versioning change is expected.

If review concludes this is a long-lived system invariant, documentation
updates may be appropriate in:

- `docs/architecture/ARCHITECTURE.md` for state authority behavior
- possibly `docs/brain-format/RULES.md` if the invariant should become a
normative portable-brain guarantee


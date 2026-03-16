# plan_portable-state-write-discipline_2: Insight-State Portable No-Op Write Discipline

Revision incorporating review feedback from
`docs/plans/plan_portable-state-write-discipline_review_1_2026-03-17.md`.

This revision keeps the original diagnosis, but closes the three blocking
review gaps:

1. the terminology and invariant are now explicitly defined against the Brain
   Format contract
2. the scope is intentionally narrowed from a repository-wide claim to the
   concrete insight-state / regen / doctor seam the diagnosis actually covers
3. the previous review-critical open questions are now settled decisions with
   explicit documentation homes

---

## Status

Planning artifact only. This document is the current revised plan for fixing
portable no-op writes in the insight-state persistence seam.

This stage does **not** implement the fix. It records the implementation
requirements, design boundaries, workstreams, and acceptance gates for a later
execution stage.

## Objective

Ensure that the durable portable insight-state manifest under
`knowledge/**/.brain-sync/insights/insight-state.json` is rewritten only when
that portable manifest has actually changed.

The implementation must ensure that, for this seam:

- machine-local lifecycle updates do not rewrite unchanged portable
  insight-state bytes
- `doctor --rebuild-db` reseeds runtime state without churning unchanged
  portable insight-state files
- regen paths do not double-write the same portable insight-state content in a
  single logical outcome
- real durable insight-state changes still persist correctly and atomically

This is a correctness issue, not merely a cleanliness issue: rewriting
portable state for runtime-only reasons creates misleading durable diffs and
can propagate ghost state across machines.

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/brain-format/README.md`
- `docs/brain-format/GLOSSARY.md`
- `docs/brain-format/RULES.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`

Implementation must also align with the current code seams that own this
specific persistence boundary:

- `src/brain_sync/state.py`
- `src/brain_sync/sidecar.py`
- `src/brain_sync/regen.py`
- `src/brain_sync/commands/doctor.py`
- `src/brain_sync/fileops.py`

## Terminology And Invariant

This revision adopts the following definitions directly from the Brain Format
contract and makes their implementation consequence explicit.

### Portable brain state

Portable brain state means durable filesystem state inside the brain root.

For this plan, the affected portable state is specifically the per-area
insight-state manifest at:

- `knowledge/**/.brain-sync/insights/insight-state.json`

### Runtime state

Runtime state means machine-local state outside the brain root, including the
runtime DB and its `regen_locks` lifecycle rows.

### Real portable change

A real portable change is a durable change to a portable filesystem entry.

For this plan's seam, that means one of:

- creating a previously absent insight-state file
- deleting an obsolete insight-state file
- moving or renaming the file because the area itself moved or renamed
- changing the serialized insight-state bytes because one of its durable fields
  actually changed

Merely opening and rewriting the same bytes is **not** a real portable change.

### No-op portable rewrite

A no-op portable rewrite is any write path that rewrites the portable
insight-state file even though the resulting serialized durable bytes are
identical to the existing portable file.

In this seam, no-op portable rewrites are correctness bugs.

### Git-visible diffs

Git-visible diffs are an operator-facing signal that the bug is happening, but
they are not the authority. The authority is whether the durable portable
filesystem state actually changed.

### Excluded transport effects

This plan is not attempting to control external transport effects such as
line-ending normalization or other git-side transformations that occur outside
brain-sync's own write paths.

## Scope Alignment

This revision intentionally narrows the plan.

The original revision 1 wording claimed a repository-wide invariant spanning
all portable mutators. The confirmed diagnosis and named workstreams do not
support that broader claim. This revision therefore scopes the implementation
to the insight-state seam where the current bug is actually diagnosed:

- `state.save_insight_state()`
- `sidecar.write_regen_meta()`
- regen call sites that update insight-state and lifecycle together
- `doctor --rebuild-db`
- closely related doctor baseline-adoption paths that use the same persistence
  seam

The broader repository principle still matters, but this plan does **not**
attempt to audit or change every portable writer under the brain root in one
step.

## Context

The architecture and Brain Format docs already define the durable/runtime
boundary:

- durable portable brain state lives inside the brain root
- runtime DB state is machine-local and rebuildable
- insight hashes belong to the portable insight-state manifest
- regen lifecycle belongs to runtime `regen_locks`

The current implementation violates that boundary in this seam:

- `save_insight_state()` writes portable insight-state data and runtime
  lifecycle in one operation
- `save_insight_state()` writes the portable manifest whenever
  `content_hash` is present, even if the serialized bytes are unchanged
- `doctor --rebuild-db` currently loops through exported insight states and
  replays them back through `save_insight_state()`
- multiple regen outcomes call `save_insight_state()` and then directly call
  `write_regen_meta()` again in the same logical flow

The result is that portable insight-state can be rewritten:

- during runtime-only lifecycle transitions such as `running` and `failed`
- during runtime DB rebuild/repair work
- during duplicate writes in the same regen outcome
- even when the durable portable bytes do not change

## Confirmed Diagnosis

The confirmed diagnosis to preserve during implementation review is:

1. portable insight-state persistence and runtime regen lifecycle persistence
   are currently coupled through `save_insight_state()`
2. `save_insight_state()` currently rewrites the portable manifest whenever
   `content_hash` is present, without checking whether the serialized portable
   bytes would change
3. `doctor --rebuild-db` currently replays portable insight-state through that
   shared path even though its primary purpose is runtime-state reconstruction
4. several regen flows currently perform duplicate durable writes by calling
   both `save_insight_state()` and `write_regen_meta()` in the same logical
   outcome
5. this behavior can create durable portable diffs that do not correspond to a
   real portable change

## Fixed Design Decisions

These decisions are settled in this revision unless a later review artifact
finds a material architectural problem.

### 1. This plan is seam-specific, not repository-wide

This implementation is specifically about portable no-op write discipline for
insight-state persistence in regen and doctor flows.

Other portable mutators such as source manifests, materialized documents,
summaries, journals, and attachments are outside this plan unless they are
required only as comparison context.

### 2. The fix requires both API separation and content-sensitive writes

This should not be treated as an "either/or" choice.

The implementation must:

- separate runtime lifecycle persistence from portable insight-state
  persistence strongly enough that runtime-only callers do not accidentally
  mutate portable state
- make the portable insight-state write path content-sensitive so unchanged
  serialized bytes are not rewritten even when a caller reaches the write path

Either change by itself would leave avoidable risk behind.

### 3. There is no justified runtime-only reason to rewrite unchanged portable bytes in this seam

For the insight-state seam covered by this plan, there is no valid runtime-only
scenario where rewriting identical portable bytes is desirable.

If a runtime transition changes only `regen_locks`, the portable
insight-state file should remain untouched.

### 4. `doctor --rebuild-db` is a runtime repair path

`doctor --rebuild-db` may read portable insight-state and use it to reconstruct
runtime state, but it should not rewrite unchanged portable insight-state as a
normal part of that repair.

### 5. Atomic durable writes must be preserved

The no-op-write fix must preserve the existing crash-safety expectations of the
portable write path. A content-sensitive check must not silently downgrade
atomicity for real portable changes.

### 6. Documentation homes are fixed

If implementation codifies this invariant in docs, the authority split is:

- `docs/brain-format/GLOSSARY.md` and `docs/brain-format/RULES.md` for the
  normative portable-vs-runtime boundary and the statement that portable brain
  state changes only when the durable portable state changes
- `docs/architecture/ARCHITECTURE.md` for the code-seam explanation of how
  runtime lifecycle and portable insight-state persistence are separated in the
  implementation

## Scope

In scope for the implementation stage:

- explicit no-op write discipline for the portable insight-state manifest
- classification of current insight-state write call sites as:
  - portable change required
  - runtime-only
  - duplicate write
- separating runtime lifecycle persistence from portable insight-state
  persistence in the affected API seam
- making portable insight-state writes content-sensitive and no-op when the
  serialized durable bytes are unchanged
- updating `doctor --rebuild-db` and related baseline-adoption uses of the same
  seam so runtime repair does not churn unchanged portable state
- removing duplicate portable writes from affected regen outcomes
- regression tests that prove runtime-only and no-op operations leave portable
  insight-state files untouched
- documentation updates for this invariant if implementation lands it as a
  long-lived rule

## Non-goals

- no Brain Format schema change
- no change to the portable location or schema of `insight-state.json`
- no repository-wide audit of every portable write surface in this change
- no redesign of source manifest persistence
- no redesign of source materialization, attachment writes, summary writes, or
  journal writes
- no weakening of portable insight-state authority
- no attempt to eliminate rewrites when durable insight-state bytes truly
  change

## Explicitly Deferred Surfaces

The following portable write surfaces are not part of this plan revision and
should not be silently pulled in under the old "repository-wide" wording:

- `.brain-sync/sources/*.json` manifest writes
- synced-source materialization writes under `knowledge/`
- `summary.md` writes
- journal writes
- attachment writes
- unrelated doctor repair paths that do not use the insight-state persistence
  seam

If implementation uncovers a second bug in one of those seams, that should be
tracked separately unless the user explicitly expands the plan.

## Planned Workstreams

### Workstream 1: Seam inventory and intent classification

Inventory all current call sites in this seam and classify each as:

- portable change required
- runtime-only
- duplicate durable write

This must cover at least:

- `state.save_insight_state()`
- `sidecar.write_regen_meta()`
- `doctor --rebuild-db`
- doctor baseline-adoption paths that currently call `save_insight_state()`
- regen rename-only, backfill, running, failure, similarity-skip, and success
  outcomes

Outcome:

- a concrete per-call-site map of which paths should be able to mutate
  portable insight-state and which should not

### Workstream 2: Persistence API boundary redesign

Refine the persistence seam so callers can express intent clearly.

The end state must make these two actions distinct:

- persist portable insight-state durable fields
- persist runtime lifecycle fields only

The exact API shape may vary, but the implementation must make it hard for a
runtime-only caller to rewrite portable insight-state accidentally.

### Workstream 3: Content-sensitive portable writes

Update the portable insight-state write path so unchanged serialized content is
not rewritten.

Candidate implementation directions:

- add a shared "write bytes if changed" helper in `fileops.py`
- update `write_regen_meta()` to compare existing bytes before calling the
  atomic writer
- keep the implementation compatible with the repository's Windows-safe
  filesystem access rules

Outcome:

- even if a valid portable write path is reached, unchanged insight-state bytes
  remain untouched

### Workstream 4: Doctor runtime-repair discipline

Update `doctor --rebuild-db` and related doctor uses of the same persistence
seam so they rebuild runtime state from portable insight-state without
rewriting unchanged portable bytes.

Outcome:

- runtime repair leaves the portable working tree unchanged when no durable
  correction is required

### Workstream 5: Regen flow cleanup

Audit regen outcomes that currently write through both
`save_insight_state()` and `write_regen_meta()`.

This must cover:

- structure-hash backfill
- rename-only handling
- running-state transitions
- failure transitions
- similarity-skip handling
- successful regeneration completion

Outcome:

- each logical regen outcome performs only the portable write, if any, that
  the outcome actually requires

### Workstream 6: Documentation updates

If the implementation lands the invariant as a long-lived rule, update:

- `docs/brain-format/GLOSSARY.md`
- `docs/brain-format/RULES.md`
- `docs/architecture/ARCHITECTURE.md`

The docs update must describe the durable/runtime boundary in stable terms and
must not depend on temporary helper names such as `write_regen_meta()`.

### Workstream 7: Tests

Add targeted regression tests that prove the invariant holds in this seam.

Candidate coverage:

- unit: content-sensitive portable write helper does not rewrite unchanged
  bytes
- unit or integration: runtime-only lifecycle persistence does not touch the
  portable insight-state file
- integration: `doctor --rebuild-db` preserves portable insight-state bytes
  when no correction is needed
- integration: rename-only and similarity-skip paths do not double-write the
  same durable content
- integration: real durable hash changes still update portable insight-state
  correctly

Tests should prefer byte equality and durable observable behavior over fragile
timing-only assertions. `mtime` may be used only as a supporting signal, not
as the sole proof.

## Proposed Implementation Strategy

1. Lock the seam terminology and documentation targets so implementation is
   grounded in the Brain Format contract.
2. Inventory the current regen and doctor call sites and classify their
   intended write semantics.
3. Introduce a clearer persistence boundary between portable durable fields and
   runtime lifecycle fields.
4. Add content-sensitive behavior to the portable insight-state write path
   while preserving atomic real-change writes.
5. Convert `doctor --rebuild-db` and related repair flows to use the narrowed
   persistence boundary.
6. Remove duplicate portable writes from affected regen outcomes.
7. Add regression tests for runtime-only, no-op, and true-change cases.
8. Update glossary/rules/architecture docs if the final implementation lands
   the invariant as a documented system rule.

## Verification

The implementation is complete only when all of the following hold:

1. runtime-only lifecycle transitions do not rewrite unchanged portable
   `insight-state.json` bytes
2. a no-op portable persistence call leaves the existing durable bytes
   untouched
3. `doctor --rebuild-db` reconstructs runtime state without rewriting
   unchanged portable insight-state files
4. regen outcomes that formerly double-wrote portable insight-state no longer
   perform redundant durable writes
5. real durable insight-state changes still persist correctly
6. the content-sensitive write path preserves crash-safe behavior for real
   durable changes
7. any new helper respects the repository's Windows-safe filesystem access rule
8. tests cover no-op, runtime-only, duplicate-write, and true-change cases in
   this seam

## Reviewer / Approver Focus

The reviewer or approver should mainly confirm that this revision now:

- defines portable brain state and real portable change precisely enough to
  guide implementation
- aligns its scope with the actual diagnosed seam instead of claiming a
  broader repository-wide audit
- settles the API-separation, content-sensitive-write, and documentation-home
  decisions clearly enough for approval

## Next Step

If no further changes are needed, the next required action is a separate
approval artifact under the `docs/plans/` workflow. This file is not approval
and does not authorize implementation by itself.

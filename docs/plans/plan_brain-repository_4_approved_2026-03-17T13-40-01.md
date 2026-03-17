# Approval

Approved: 2026-03-17T13-40-01
Approved by: codex-gpt-5

Notes:
- Revision 4 correctly preserves revision 2 as the authoritative base while tightening the correction scope around write-boundary closure.
- The corrected target layering is sound: `brain_repository.py` for portable state, `state.py` for runtime state, and primitive storage helpers beneath those seams.
- Observability should resume only after the explicit portable-write inventory, exception handling, and dependency-direction cleanup gates in this revision are satisfied.

---

# plan_brain-repository_4: Brain Repository Boundary Correction With Carry-Forward And Closure Gates

Revision 4 of the brain repository plan.

This revision responds to
`plan_brain-repository_3_review_1_2026-03-17.md`.

Revision 3 correctly diagnosed the implementation drift, but the review found
two remaining gaps before approval:

1. it did not explicitly preserve the still-valid requirements from approved
   revision 2
2. it described a write-first rule without turning that rule into a strong
   enough closure gate for implementation and for the later observability work

This revision keeps the correction direction from revision 3, while making the
carry-forward rules and the write-boundary closure requirements explicit.

---

## Status

Planning artifact only.

This revision does **not** authorize implementation. It is the next plan
revision for review under the `docs/plans/` workflow.

---

## Revision Basis And Carry-Forward Rule

Approved
`plan_brain-repository_2_approved_2026-03-17T11-13-59.md`
remains the authoritative base for this work.

This revision should be read as a **narrowing and correction layer** on top of
revision 2, not as a replacement of its still-valid requirements.

Unless this revision explicitly tightens, narrows, or replaces a requirement,
all non-conflicting constraints from revision 2 remain in force.

That includes, in particular:

- Brain Format `1.0` remains unchanged by default
- no portable schema, compatibility, or versioning changes are implied by this
  work
- journal durability and append-only preservation remain fixed design
  decisions
- `attachments.py` and `commands/doctor.py` remain in scope for repository
  boundary migration
- repository operations remain expected to return structured semantic outcomes
  suitable for later observability
- the watcher remains an edge observer and must not remain an independent
  semantic authority path
- doctor repair semantics must converge onto the same repository-owned
  portable-state rules as mainline flows
- the work remains sequenced before runtime observability and before the larger
  regeneration refactor

Where revision 4 is more specific than revision 2, revision 4 should be taken
as the controlling interpretation for this correction stage.

---

## Problem Statement

The approved direction from revision 2 was sound. The implementation drift was
not.

Two things must now be corrected together:

1. **portable write authority is still porous**

Normal runtime code still mutates portable brain state through scattered paths
outside the intended repository seam.

2. **repository scope is drifting upward**

`brain_repository.py` has started to absorb or depend on workflow-shaped logic
instead of remaining a portable persistence/control boundary.

If left unresolved, those two problems will undermine the next planned stages:

- runtime event-ledger observability will have no small trusted mutation seam
- regeneration refactoring will continue to inherit mixed persistence/workflow
  responsibilities

---

## Revised Objective

Restore the repository work to the shape revision 2 intended:

- `brain_repository.py` is the portable-brain persistence/control seam
- `state.py` is the runtime-plane persistence/control seam
- primitive storage modules remain lower-level implementation detail beneath
  those seams
- workflow logic remains above those seams
- all normal runtime portable-brain writes converge on the repository seam
  before observability resumes

This revision continues the write-first scope from revision 3, but it now adds
an explicit closure gate so "write-first" is verifiable rather than aspirational.

---

## Boundary Model

### 1. Portable plane

`src/brain_sync/brain_repository.py` is the single runtime persistence/control
boundary for portable brain state under the brain root.

It is:

- brain-specific
- persistence-oriented
- policy-enforcing
- allowed to know stable portable artifact patterns and layout rules

It is **not**:

- a generic filesystem API
- a generic path CRUD wrapper
- the place where source sync, reconcile, doctor, or regen workflow logic
  should live

### 2. Runtime plane

`src/brain_sync/state.py` is the current runtime-plane persistence/control
boundary for machine-local state under `~/.brain-sync/`.

This includes:

- runtime DB access
- daemon/runtime lifecycle persistence
- runtime rebuild/reset operations

An eventual rename such as `runtime_repository.py` remains attractive but is
not required for approval of this plan.

### 3. Primitive layer

The following remain lower-level implementation modules beneath the
repositories:

- `src/brain_sync/fileops.py`
- `src/brain_sync/manifest.py`
- `src/brain_sync/sidecar.py`

They may continue to contain write helpers.

The architectural rule is about **call direction**, not about deleting those
helpers:

- repository modules may call them
- narrow bootstrap, migration, and test/SUT code may call them where justified
- normal runtime application logic should not directly use them for portable
  brain semantics once the repository seam exists

### 4. Service/orchestration layer

Application and workflow logic remains above the repository seams.

Examples:

- source reconciliation and lifecycle orchestration
- materialization workflow
- doctor repair orchestration
- regen planning and execution
- future semantic event emission

These modules should depend on `brain_repository.py` and `state.py`, not on
portable primitive storage modules for normal runtime mutation behavior.

---

## Write-First Rule, Clarified

### Immediate enforcement target

All normal runtime **portable-brain writes** under the brain root must be
mediated through `brain_repository.py`.

All normal runtime **runtime-state writes** under `~/.brain-sync/` must be
mediated through `state.py`.

### Important clarification

This does **not** mean "reads do not matter".

Portable reads that determine the semantic meaning of a durable write or
transition must move with the corrected seam when they are part of mutation
authority.

Examples include:

- source resolution that decides whether a source is missing, reappeared, or
  moved
- area-state load decisions that determine cleanup or persistence behavior
- write-adjacent classification reads used to select a durable portable-state
  transition

Broad read centralization is still future-state, but write-adjacent authority
reads are in scope now.

---

## Closure Gate For Observability

Observability remains parked until the repository correction produces a
trustworthy write seam.

For this plan, "trustworthy" means all of the following:

- there is an explicit inventory of normal runtime portable-write paths
- every inventoried path is either:
  - migrated behind `brain_repository.py`, or
  - recorded in an explicit temporary exception list with justification
- no remaining direct portable-write path is left merely because it was not in
  the original hotspot list
- dependency direction no longer allows `brain_repository.py` to depend on
  higher-level workflow modules for durable semantics

Observability should not resume on a hotspot-only closure argument.

It should resume only after the write boundary is treated as a real,
reviewable closure condition.

---

## Current Known Portable-Write Risk Areas

The currently known normal runtime portable-write areas still outside the
desired seam are:

- `src/brain_sync/commands/sources.py`
- `src/brain_sync/pipeline.py`
- `src/brain_sync/attachments.py`
- `src/brain_sync/regen.py`
- portable helper paths in `src/brain_sync/state.py`
- portable repair paths in `src/brain_sync/commands/doctor.py`

This list is the starting point, not the closure definition.

Implementation must still inventory the full remaining portable-write surface.

---

## Additional Constraint: Dependency Direction Cleanup

The correction must also clean up repository dependency direction.

In particular:

- `brain_repository.py` must not depend on higher-level workflow modules for
  durable portable semantics
- any helper logic currently imported upward from workflow modules must either:
  - move down into a neutral lower layer, or
  - be re-expressed inside the repository/persistence layer if it is truly a
    persistence concern

The goal is to make the layering legible:

- workflow calls repository
- repository calls primitive storage helpers
- not the reverse

---

## Planned Workstreams

### Workstream 1: Portable-write authority inventory

Goals:

- enumerate the full remaining normal runtime portable-write surface
- make the closure target explicit before migration begins

Implementation requirements:

- inventory all normal runtime code paths that:
  - write portable brain artifacts
  - delete portable brain artifacts
  - move or rename managed portable paths
  - perform write-adjacent authority reads that determine portable transitions
- classify each path as:
  - repository-mediated already
  - migration required
  - temporary exception candidate
- produce an explicit exception list if any temporary bypasses remain

Expected outcome:

- a verifiable closure map for portable write authority rather than a
  hotspot-only migration list

### Workstream 2: Carry-forward documentation and guardrails

Goals:

- make the repository and runtime seams explicit in long-lived repo rules
- prevent further spread of direct portable mutation outside the seam

Implementation requirements:

- update `AGENTS.md`
- update `docs/architecture/ARCHITECTURE.md`
- add module-level responsibility docstrings where useful
- add lightweight architecture guard tests that:
  - prevent new direct primitive portable-mutation imports
  - help freeze the approved temporary exception set

Expected outcome:

- future contributors and agents see the intended call direction clearly

### Workstream 3: Correct repository surface and dependency shape

Goals:

- keep `brain_repository.py` persistence-oriented
- remove upward workflow entanglement

Implementation requirements:

- tighten `brain_repository.py` around durable portable artifact mediation
- remove or relocate imports from higher-level workflow modules
- ensure the repository surface reflects durable artifact semantics rather than
  workflow orchestration
- preserve revision 2 requirements for structured outcomes and journal safety

Expected outcome:

- repository seam is smaller, clearer, and lower in the dependency graph

### Workstream 4: Migrate all normal runtime portable writes

Goals:

- converge the remaining portable-write surface on the repository seam

Implementation requirements:

- migrate portable write paths from:
  - `commands/sources.py`
  - `pipeline.py`
  - `attachments.py`
  - `regen.py`
  - portable helper paths in `state.py`
  - portable repair paths in `commands/doctor.py`
- migrate associated write-adjacent authority reads where needed
- record any approved temporary exceptions explicitly

Expected outcome:

- normal runtime portable mutation no longer depends on scattered durable write
  paths

### Workstream 5: Purify the runtime plane

Goals:

- remove portable-brain mutation concerns from `state.py`

Implementation requirements:

- relocate portable helper responsibilities out of `state.py`
- leave `state.py` representing runtime-plane concerns only
- optionally rename `state.py` to `runtime_repository.py` if low risk and if
  it materially improves clarity

Expected outcome:

- only two visible persistence mediators remain in normal runtime code:
  portable and runtime

### Workstream 6: Resume observability on the corrected seam

Goals:

- restart the approved runtime observability work on a trustworthy foundation

Implementation requirements:

- confirm closure of the portable-write inventory and any temporary exceptions
- refresh observability notes if the final seam differs materially from the
  earlier audit
- resume event-ledger implementation only after the closure gate is satisfied

Expected outcome:

- semantic eventing can attach to a small number of trustworthy boundaries

---

## Proposed Execution Order

1. Carry forward revision 2 explicitly in docs and plan framing.
2. Inventory all remaining normal runtime portable-write paths and authority
   reads.
3. Add guardrails and document the temporary exception set.
4. Correct the repository surface and remove upward dependency drift.
5. Migrate the inventoried portable-write paths behind the repository seam.
6. Clean `state.py` back to runtime-only responsibility.
7. Optionally rename `state.py` if the migration remains low risk.
8. Resume observability after the closure gate is satisfied.

---

## Acceptance Criteria

This correction is complete only when all of the following are true:

1. Revision 2's still-valid requirements remain explicitly in force unless
   superseded by this revision.
2. Brain Format `1.0`, portable schemas, and compatibility/versioning remain
   unchanged by this work.
3. `brain_repository.py` is clearly the portable-brain persistence/control
   seam, and `state.py` is clearly the runtime-plane persistence/control seam.
4. Primitive modules are documented and treated as lower-level implementation
   dependencies rather than primary runtime semantic entry points.
5. An explicit inventory exists for **all** remaining normal runtime
   portable-write paths and write-adjacent authority reads.
6. Every inventoried normal runtime portable-write path is either:
   - mediated through `brain_repository.py`, or
   - documented in an explicit temporary exception list with justification
7. `brain_repository.py` no longer depends on higher-level workflow modules for
   durable portable semantics.
8. `state.py` no longer serves as a mixed portable/runtime mutation boundary
   for normal runtime code.
9. Structured semantic outcomes remain available for later observability work.
10. Journal append-only durability remains preserved through repository-owned
    cleanup and persistence paths.
11. Doctor repair and attachment lifecycle behavior remain within the boundary
    migration scope and use repository-owned portable semantics.
12. Observability is resumed only after the portable-write closure gate is
    satisfied.

---

## Risks And Mitigations

### Risk: Revision 4 still weakens revision 2 by omission

Mitigation:

- carry revision 2 forward explicitly
- treat revision 4 as a correction layer rather than a replacement narrative

### Risk: The closure gate still turns into a hotspot-only migration

Mitigation:

- require a full portable-write inventory
- require an explicit exception list for anything not yet migrated
- do not treat "we fixed the known files" as sufficient evidence by itself

### Risk: Repository cleanup still leaves workflow logic entangled with persistence

Mitigation:

- make dependency direction cleanup a first-class requirement
- remove upward repository imports from workflow modules

### Risk: Write-first is interpreted as ignoring semantic reads

Mitigation:

- keep write-adjacent authority reads in scope
- defer only broad read centralization, not reads that determine durable
  transition meaning

### Risk: Observability is delayed too long

Mitigation:

- keep the correction tightly focused on write authority and dependency shape
- resume observability immediately once the closure gate is satisfied

---

## Reviewer Focus

The reviewer should concentrate on these questions:

1. Does revision 4 preserve revision 2's still-binding constraints clearly
   enough?
2. Is the write-first rule now turned into a real closure gate rather than a
   hotspot migration note?
3. Is the dependency-direction cleanup explicit enough to prevent repository
   scope drift?
4. Is the treatment of write-adjacent authority reads scoped correctly?
5. Is the resulting correction narrow enough to stay practical before
   observability and the later regen refactor?

---

## Next Step

If review feedback identifies issues, the planner should create a further
revision artifact rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

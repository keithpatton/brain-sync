# plan_brain-repository_3: Brain Repository Boundary Correction

Revision 3 of the brain repository plan.

This revision is prompted by implementation-time learning after
`plan_brain-repository_2_approved_2026-03-17T11-13-59.md`.

The approved revision 2 was directionally and architecturally sound. It
already described the repository as a seam, kept low-level helpers beneath the
boundary, and did not call for business logic to be absorbed into the
repository layer.

The problem was execution drift during the first implementation attempt:

1. direct portable-state mutation still remained spread across multiple runtime
   modules instead of fully converging on the repository write boundary
2. implementation began pulling workflow/business logic toward
   `brain_repository.py`, which is the opposite of the intended repository seam

This revision therefore records an **execution correction**, not a repudiation
of revision 2. Its purpose is to restate the intended layering in a form that
another agent can review and execute safely before runtime observability
proceeds.

---

## Status

Planning artifact only.

This revision does **not** implement the correction. It records the clarified
boundary, the narrowed repository role, the staged migration, and the reason
runtime observability should pause until this foundation is tightened.

---

## Problem Statement

The approved repository direction was correct, but the first implementation
attempt drifted away from it in ways that matter for both correctness and
observability.

### What revision 2 got right

- there should be a single runtime boundary for portable brain state
- portable brain state and machine-local runtime state must be separate
- low-level modules such as `fileops.py`, `manifest.py`, and `sidecar.py`
  should sit beneath that boundary rather than acting as the boundary
- this work should land before event-ledger observability and before the larger
  regeneration refactor

### What execution got wrong

The failure mode was not primarily that revision 2 was unclear. The failure
mode was that the implementation did not stay aligned with what revision 2 was
already trying to do.

1. **Write mediation invariant**

The implementation did not complete the repository write mediation implied by
revision 2. All normal runtime **portable-brain writes** under the brain root
should converge on the repository boundary.

That allowed a partial migration where some portable mutation paths still live
in:

- `commands/sources.py`
- `pipeline.py`
- `attachments.py`
- `regen.py`
- portable helper paths in `state.py`
- some repair paths in `commands/doctor.py`

2. **Repository scope invariant**

The implementation started drifting toward a persistence-plus-workflow god
object rather than the repository seam revision 2 actually intended.

That creates a risk that `brain_repository.py` grows into a persistence-plus-
workflow god object instead of staying a clean boundary that mediates durable
brain access while leaving business logic above it.

---

## Revised Objective

Establish a tighter two-plane persistence architecture that is explicit enough
to support later event-ledger observability and a regeneration refactor.

The corrected end state for this revision is:

- all normal runtime writes to portable brain state under the brain root are
  mediated through `brain_repository.py`
- all normal runtime writes to machine-local runtime state under
  `~/.brain-sync/` are mediated through `state.py`
- `brain_repository.py` remains a **brain-specific persistence boundary**, not
  a generic filesystem API and not an application workflow service
- application/business logic remains in service/orchestration modules above the
  repository layer
- low-level primitive modules remain beneath the repositories and are clearly
  documented as implementation detail rather than approved runtime access paths

This revision intentionally does **not** require full read-side centralization
before observability. The immediate enforcement target is write mediation.

---

## Revised Layering Model

### 1. Portable brain repository

`src/brain_sync/brain_repository.py` should be the primary runtime gateway to
portable brain state under the brain root.

In Python terms, this should be a product-specific persistence boundary, not a
generic CRUD-over-paths utility and not the home for application workflow
logic.

Its responsibilities should stay close to:

- safe location and access to portable brain artifacts
- persistence of durable portable artifacts
- path / naming / managed-namespace enforcement
- schema-location and durable-write policy enforcement
- portable cleanup operations where the cleanup is inherently about persisted
  brain artifacts

It may know about stable brain structures such as:

- source manifests
- area summaries
- insight-state sidecars
- journal files
- managed attachment locations
- managed artifact tree layout

It should **not** become the place where the full business workflow for sync,
reconcile, doctor, or regeneration is implemented.

### 2. Runtime repository

`src/brain_sync/state.py` is effectively the machine-local runtime repository
today. It owns:

- runtime DB access
- daemon status persistence
- runtime lifecycle rows
- machine-local runtime rebuild/reset semantics

This revision treats that as the correct architectural role even if the module
name stays `state.py` for now.

An eventual rename such as `runtime_repository.py` is attractive because it
makes the two-plane architecture more legible:

- `brain_repository.py`
- `runtime_repository.py`

That rename is in scope only if it remains low-risk during implementation. It
is not required for the architectural correction itself.

### 3. Primitive modules beneath the repositories

The following modules should remain lower-level implementation primitives:

- `src/brain_sync/fileops.py`
- `src/brain_sync/manifest.py`
- `src/brain_sync/sidecar.py`

These modules may still contain write helpers.

That is acceptable.

The important rule is **who is allowed to call them directly**:

- repository modules may call them
- narrow bootstrap / migration code may call them
- tests and SUT-style test harness code may call them
- normal runtime application modules should not use them directly for portable
  brain semantics if a repository path should exist

This is the Pythonic equivalent of "internal lower layer with convention and
guardrails" rather than C#-style hard visibility.

### 4. Application/service layer above the repositories

Workflow and business logic should live above the repository layer in command,
service, or orchestration modules.

Examples:

- source registration / reconcile workflow
- sync materialization workflow
- doctor repair workflow
- regen decision and propagation workflow
- future semantic event emission

These modules may depend on `brain_repository.py` and `state.py`, but should
not depend directly on the lower-level storage primitives for portable-state
mutation.

---

## Write-First Scope Rule

This revision intentionally narrows the immediate enforcement target.

### Enforce now

All normal runtime **portable-brain writes** under the brain root must be
mediated through `brain_repository.py`.

All normal runtime **runtime-state writes** under `~/.brain-sync/` must be
mediated through `state.py`.

### Future target, not immediate gate

Portable-brain **reads** should also converge on repository mediation over
time, but this revision does not require centralizing every read path before
the observability work can resume.

Reason:

- write mediation is the critical foundation for clean event emission
- full read mediation is architecturally desirable, but substantially broader
  and lower leverage for the immediate observability milestone

---

## Why Observability Is Parked

Runtime observability should pause until this repository correction lands.

Reason:

- event-ledger work needs a small number of trusted mutation boundaries
- without the corrected write mediation rule, semantic events would still need
  to be emitted from many scattered write paths
- if `brain_repository.py` continues drifting toward business workflow logic,
  observability risks binding to the wrong abstraction and becoming harder to
  maintain during the later regeneration refactor

Observability is therefore not rejected. It is being **sequenced behind the
repository correction** so it lands on a cleaner foundation.

---

## Confirmed Current Mutation Gaps

The main portable-brain write seams still outside the desired repository
boundary are:

- `src/brain_sync/commands/sources.py`
- `src/brain_sync/pipeline.py`
- `src/brain_sync/attachments.py`
- `src/brain_sync/regen.py`
- portable helper paths in `src/brain_sync/state.py`
- some portable repair paths in `src/brain_sync/commands/doctor.py`

This revision treats those write paths as the primary migration targets.

Read-side exceptions may remain temporarily.

---

## Design Constraints For The Corrected Repository

The corrected repository should satisfy all of the following:

1. It is **brain-specific**, not generic.
2. It is **persistence-oriented**, not workflow-oriented.
3. It may expose artifact-oriented CRUD-like operations for durable brain
   structures.
4. It should avoid Unix-like low-level method proliferation as the public
   repository API.
5. It should avoid becoming the home of source/reconcile/regen business rules.
6. It should make policy enforcement and future eventing easier by keeping
   durable writes on a small surface.

### Repository API shape guidance

Good repository surface examples:

- read/write/delete source manifest or source registration artifact
- read/write/delete area summary artifact
- read/write/delete insight-state artifact
- append journal entry
- read/write/delete managed attachment artifact
- safe move/remove operations on managed durable artifact locations

Less suitable as repository public API:

- full source reconciliation workflow
- source polling logic
- retry logic
- watcher semantics
- regen decision logic
- queue / propagation logic
- interface-specific orchestration

---

## Python-Specific Modularity Guidance

Because Python does not provide C#-style access modifiers for modules, this
revision uses Python-appropriate mechanisms:

- explicit repository boundary modules
- lower-level primitive modules documented as internal implementation detail
- module docstrings that declare responsibility and dependency direction
- AGENTS.md rules that state the layering invariant clearly
- lightweight architecture guard tests that freeze the allowed exception set
  and prevent spread of new direct primitive-mutation imports

This should be treated as the Python best-practice equivalent of stronger
layering, without overarchitecting around language features Python does not
have.

---

## Planned Workstreams

### Workstream 1: Clarify the written boundary

Update repository rules and architecture-facing documentation so they state:

- portable brain writes go through `brain_repository.py`
- runtime-state writes go through `state.py`
- `fileops.py`, `manifest.py`, and `sidecar.py` are primitive modules beneath
  those repositories
- full read mediation is future-state; write mediation is enforced now

Expected outputs:

- `AGENTS.md`
- `docs/architecture/ARCHITECTURE.md`
- stronger module-level docstrings where useful

### Workstream 2: Freeze primitive mutation sprawl

Add a lightweight architecture guard that prevents new runtime modules from
directly importing portable-state mutation helpers from:

- `fileops.py`
- `manifest.py`
- `sidecar.py`

The guard should permit only a documented, temporary exception set so the
current migration can proceed incrementally without pretending it is complete.

Expected outputs:

- one or more unit-level architecture guard tests

### Workstream 3: Define the corrected repository surface

Refactor `brain_repository.py` toward a tighter, persistence-oriented,
artifact-focused API.

The goal is not maximum genericity. The goal is a small, product-specific,
brain-artifact persistence boundary that service/orchestration modules can call.

Expected outcome:

- repository API is smaller, clearer, and less workflow-shaped than the
  implementation attempt that triggered this revision

### Workstream 4: Migrate portable writes behind the repository

Move the current portable-brain mutation paths from:

- `commands/sources.py`
- `pipeline.py`
- `attachments.py`
- `regen.py`
- portable helper paths in `state.py`
- relevant portable repair paths in `commands/doctor.py`

onto the corrected repository surface.

The target is **write centralization**, not total behavioral redesign.

### Workstream 5: Clean up `state.py` into a purer runtime repository

Remove or relocate portable-brain helper responsibilities from `state.py` so it
more clearly represents machine-local runtime state only.

Candidate follow-up:

- rename `state.py` to `runtime_repository.py` if the change remains low-risk
  and materially improves layering clarity

Expected outcome:

- only two top-level persistence mediators are visible in normal runtime code:
  one for the brain, one for runtime state

### Workstream 6: Re-establish the observability seam

After the write boundary is corrected:

- refresh the observability implementation notes
- resume the runtime event-ledger work against the cleaner repository/service
  layering

Expected outcome:

- event emission attaches to a smaller number of trustworthy mutation seams

---

## Proposed Execution Order

1. Tighten the written rule in `AGENTS.md` and architecture docs.
2. Add guardrails that stop new primitive mutation bypasses.
3. Correct the public shape of `brain_repository.py` so it is persistence-
   oriented rather than workflow-oriented.
4. Migrate the known portable write hotspots behind that corrected boundary.
5. Shrink `state.py` back toward runtime-only responsibility.
6. Optionally rename `state.py` to `runtime_repository.py` if low risk.
7. Resume observability work on the corrected foundation.

---

## Acceptance Criteria

This correction is complete only when all of the following are true:

1. The repository rules explicitly state that portable brain writes are
   mediated through `brain_repository.py`.
2. The repository rules explicitly state that runtime-state writes are
   mediated through `state.py` (or a renamed runtime repository module).
3. Primitive storage modules are documented as lower-level implementation
   dependencies, not primary runtime access paths.
4. `brain_repository.py` exposes a tighter persistence-oriented API rather than
   absorbing application workflow logic.
5. The known portable-brain write hotspots outside the repository boundary have
   been migrated or intentionally documented as temporary exceptions.
6. `state.py` no longer acts as a mixed portable/runtime persistence boundary
   for normal runtime code.
7. Lightweight guardrails prevent new direct primitive portable-state mutation
   imports from spreading across runtime modules.
8. Runtime observability work can resume with a small number of trustworthy
   write seams rather than scattered low-level write hooks.

---

## Risks And Mitigations

### Risk: The repository becomes too generic and loses policy value

Mitigation:

- keep the repository brain-specific
- expose artifact/persistence operations, not arbitrary path CRUD
- preserve schema and managed-layout knowledge where it reflects stable brain
  structure

### Risk: The repository remains too workflow-shaped

Mitigation:

- move source/reconcile/regen business logic into service/orchestration modules
- keep the repository focused on mediated durable access

### Risk: Full read centralization expands scope too much

Mitigation:

- enforce writes first
- treat read mediation as future-state unless a read path is tightly coupled to
  durable policy enforcement

### Risk: Python conventions are too soft to hold the boundary

Mitigation:

- combine documentation, module docstrings, naming clarity, and architecture
  guard tests
- freeze an exception list instead of relying on contributor memory alone

### Risk: Observability is delayed unnecessarily

Mitigation:

- keep the correction focused on the write boundary and repository shape
- resume observability immediately after the write seams are made trustworthy

---

## Reviewer Focus

The reviewer should concentrate on these questions:

1. Does this revision correct the ambiguity between "repository as persistence
   boundary" and "repository as workflow service" clearly enough?
2. Is the write-first scope rule the right compromise before observability?
3. Does the plan preserve the value of a single portable-brain control layer
   without turning the repository into a god object?
4. Is the treatment of `state.py` as the runtime repository directionally
   correct, including the possible later rename?
5. Is the observability pause justified and properly scoped?

---

## Next Step

If review feedback identifies issues, the planner should create a further
revision artifact rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

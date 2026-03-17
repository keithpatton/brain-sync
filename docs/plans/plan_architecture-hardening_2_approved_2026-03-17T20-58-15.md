# Approval

Approved: 2026-03-17T20-58-15
Approved by: codex-gpt-5

Notes:
- Revision 2 resolves the prior blocking decisions explicitly: child-discovery is runtime-only request state, cross-plane projection moves out of `runtime/`, and this hardening stage is single-brain by design.
- The phased workstreams and acceptance criteria now describe a coherent steady state without leaving the architectural boundary choices to implementation-time guesswork.
- Brain Format `1.0` remains intentionally fixed, while multi-brain runtime isolation and event-ledger work stay clearly deferred to later approved plans.

---

# plan_architecture-hardening_2: Post-Refactor Architecture Hardening

## Status

Approved plan revision 2.

This artifact records approval of
`docs/plans/plan_architecture-hardening_2_2026-03-17.md` as the authoritative
implementation handoff for this work.

## Objective

Raise the architecture to a state where further investment is predictable,
bounded, and materially easier to review.

The implementation must:

- preserve Brain Format `1.0`
- remove known concept drift at subsystem boundaries
- give REGEN a narrow public service boundary
- reduce runtime and transport blast radius
- establish clear seams for later operational observability

## Review and Plan Inputs

This revision is grounded in these upstream artifacts:

- `docs/architecture/reviews/TEMPLATE.md`
- `docs/architecture/reviews/2026-03-17-baseline.md`
- `docs/plans/PLAN_architecture-hardening.md`
- `docs/plans/plan_architecture-hardening_review_1_2026-03-17.md`

The baseline architecture review remains the problem statement and scorecard.
Review 1 is the approval gate this revision satisfied.

## Authoritative Inputs

Implementation must treat these documents as primary constraints:

- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/architecture/reviews/TEMPLATE.md`
- `docs/architecture/reviews/2026-03-17-baseline.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `AGENTS.md`

## Problem Statement

The baseline architecture review identified five critical findings:

1. child-discovery intent is structurally inconsistent
2. REGEN does not have a real public boundary
3. runtime ownership is too monolithic and mixes cross-plane projection with
   runtime ownership
4. transports still own application policy directly
5. root scoping and runtime isolation are underdefined

This plan addresses all five, but it does so by making three design decisions
explicit now rather than leaving them for implementation-time guesswork:

- child-discovery survives only as runtime-only request state
- cross-plane projection leaves `runtime/` and becomes application-owned
- this hardening stage is explicitly single-brain by design

## Fixed Design Decisions

### 1. Brain Format `1.0` stays unchanged in this plan

This plan does not change the portable contract. No manifest, brain layout, or
portable sidecar change is allowed unless a later approved plan explicitly
changes that decision.

### 2. Child-discovery intent survives as runtime-only request state

The current portable modeling of `fetch_children` and `child_path` is removed.

Approved steady state:

- child-discovery intent is **not** part of the portable brain contract
- source manifests do **not** persist `fetch_children` or `child_path`
- child-discovery intent is stored only in the runtime plane as one-shot
  machine-local request state
- the runtime owner is a dedicated runtime-owned request surface, not
  `SourceManifest` and not a transport-local variable
- application commands write that request state through a runtime-owned API
- daemon processing reads and clears that request state through the same
  runtime-owned API

Caller migration rules:

- CLI and MCP may continue to expose the feature for now, but only as a
  runtime request against the active local runtime
- no code may infer child-discovery intent by reading manifests
- tests must stop asserting contradictory "accepted but discarded portable
  field" behavior and instead assert explicit runtime-only semantics

This preserves Brain Format `1.0` while removing the current split-brain model.

### 3. Cross-plane projection leaves `runtime/`

`runtime/` owns machine-local storage and runtime-state mutation only. It does
not own the assembly of portable manifests or portable sidecars into combined
read models.

Approved steady state:

- `brain/` owns portable manifests, sidecars, and portable-brain mutation
- `runtime/` owns sync cache, request state, regen locks, daemon status, and
  token-event persistence
- cross-plane projection moves to an application-owned read/service layer that
  composes portable and runtime inputs into use-case views

Allowed dependency shape for this concern:

- `application -> brain / runtime`
- `runtime` must not remain the owner of manifest or sidecar projection logic

This decision is specifically intended to retire the current ambiguity in
`runtime/repository.py`.

### 4. This hardening stage is explicitly single-brain by design

This plan does **not** introduce true root-isolated runtime storage.

Approved steady state for this stage:

- the runtime directory remains a single active runtime for one configured
  brain per config directory
- APIs that pretend to be root-scoped while actually using global runtime
  storage should be simplified or made explicit
- misleading unused `root` parameters should be removed where the runtime is
  intentionally global within the config directory
- true per-brain runtime isolation is deferred to a later approved plan

Required documentation outcome:

- docs must describe the current architecture as single-brain at the runtime
  layer, not ambiguously "root-aware"

### 5. REGEN must become a subsystem, not a barrel export

Sync, watcher, queue, CLI, and MCP code should depend on a narrow REGEN service
surface, not on engine internals or re-exported private helpers.

### 6. Application owns shareable workflows

If a workflow should behave the same in CLI and MCP, its orchestration belongs
in `application/` unless there is a strong transport-specific reason not to.

### 7. Observability hooks belong at semantic boundaries

This plan should leave the codebase ready for structured event emission at:

- repository boundaries
- application-owned orchestration boundaries
- long-running lifecycle transitions

It should not leave observability dependent on transport-local or engine-local
best-effort hooks.

## Scope

In scope for the implementation stage:

- removal of the current portable child-discovery abstraction
- creation of runtime-only child-discovery request ownership
- extraction of cross-plane projection out of `runtime/`
- decomposition of runtime ownership into focused modules or owners
- creation of a narrow REGEN public service boundary
- migration of shared transport-owned workflows into `application/`
- cleanup of misleading root-scoping APIs to match the explicitly
  single-brain runtime model
- targeted invalidation and observability-ready seams at repository and
  orchestration boundaries
- architecture-boundary, compatibility, and regression tests needed to ratchet
  the new shape
- documentation updates required by any ownership or dependency change

## Non-goals

- no Brain Format `1.0` bump
- no true multi-brain runtime isolation in this plan
- no event ledger implementation in this plan
- no broad redesign of source adapters unless required by ownership cleanup
- no UI or CLI redesign unrelated to architectural ownership
- no speculative plugin system or public SDK work
- no performance micro-optimization outside architecture-level hot spots

## Phased Workstreams

## Phase 1. Replace Portable Child-Discovery With Runtime Request State

Goal:
Eliminate the current concept drift around `fetch_children` and `child_path`.

Required outcomes:

- `SourceManifest` no longer acts as the carrier for child-discovery intent
- runtime request state has one owner and one lifecycle
- CLI and MCP feature wiring targets runtime-only request state
- daemon processing reads and clears runtime request state explicitly

Expected code pressure:

- `src/brain_sync/application/sources.py`
- `src/brain_sync/brain/manifest.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/`
- `src/brain_sync/sync/daemon.py`
- related CLI, MCP, and tests

Acceptance criteria:

- no durable model field is intentionally dropped at the portable write
  boundary
- no manifest read path is used to infer child-discovery requests
- runtime request semantics are documented as machine-local and one-shot
- compatibility tests still prove Brain Format `1.0` is unchanged

## Phase 2. Move Cross-Plane Projection to Application and Split Runtime Owners

Goal:
Separate runtime persistence from cross-plane state assembly.

Required outcomes:

- an application-owned state/view layer composes manifests, portable sidecars,
  and runtime tables into use-case views
- runtime owners are split into focused modules or equivalent narrow surfaces
- no-op compatibility stubs are removed or replaced with truthful APIs

Approved ownership target:

- `brain/`: portable source and insight state
- `runtime/`: machine-local tables and runtime-only request state
- `application/`: merged state views and orchestration-facing read models

Expected code pressure:

- `src/brain_sync/application/`
- `src/brain_sync/runtime/`
- direct callers of `runtime/repository.py`

Acceptance criteria:

- `runtime/` no longer owns manifest or sidecar projection logic
- the application-owned projection layer can be named and tested directly
- runtime modules can be understood as machine-local owners without reference
  to portable state authority
- compatibility stubs such as no-op target-path or flag updates are gone

## Phase 3. Create a Narrow REGEN Service Boundary

Goal:
Replace broad REGEN exports with a small, durable service API.

Required outcomes:

- `brain_sync.regen` exposes a narrow public surface
- queue, sync, and transports stop depending on engine internals
- architecture-boundary tests ratchet the narrower dependency shape

Expected code pressure:

- `src/brain_sync/regen/__init__.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/sync/watcher.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`

Acceptance criteria:

- REGEN call sites can be enumerated through a small public API
- REGEN refactor work can be scoped without touching transport internals
- no new transitional debt entries are needed for REGEN imports

## Phase 4. Move Shared Orchestration Into Application

Goal:
Make CLI and MCP thin transports over shared workflows.

Required outcomes:

- shared query, regen, reconcile, reporting, and source-management workflows
  move into `application/` where they are transport-independent
- transport code focuses on parsing, request shaping, and result presentation
- policy changes stop requiring parallel edits in CLI and MCP

Expected code pressure:

- `src/brain_sync/application/`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`

Acceptance criteria:

- transport modules stop importing broad sets of lower subsystem packages
- shared behavior lives behind application-owned functions
- architecture-boundary exceptions shrink rather than expand

## Phase 5. Make Single-Brain Runtime Semantics Explicit and Prepare Scale Seams

Goal:
Remove misleading root-scoping behavior and prepare observability and scale
work on truthful architectural seams.

Required outcomes:

- runtime APIs match the explicit single-brain runtime model
- misleading unused `root` parameters are removed or replaced with truthful API
  names and docs
- event-emission points are clear at repository and application boundaries
- obvious whole-tree refresh patterns are replaced with targeted invalidation
  where feasible

Expected code pressure:

- `src/brain_sync/application/roots.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/runtime/paths.py`
- `src/brain_sync/runtime/token_tracking.py`
- `src/brain_sync/query/area_index.py`
- repository and application layers touched by earlier phases

Acceptance criteria:

- docs describe the runtime layer as single-brain for this stage
- tests prove the chosen single-brain semantics instead of implying future
  root isolation
- root-agnostic APIs no longer accept unused root parameters
- architecture review rerun shows measurable improvement in observability and
  scale-readiness scores

## Sequencing

Recommended order:

1. phase 1: child-discovery runtime-only request state
2. phase 2: application-owned projection and runtime split
3. phase 3: REGEN service boundary
4. phase 4: transport thinning through application workflows
5. phase 5: explicit single-brain semantics and scale seams

Rationale:

- phase 1 removes the clearest architectural lie immediately
- phase 2 resolves the highest-blast-radius ownership ambiguity before deeper
  subsystem refactors
- phase 3 should land after ownership boundaries are cleaner but before the
  major REGEN redesign
- phase 4 is safer once lower seams are more truthful
- phase 5 hardens the resulting architecture for observability and later scale
  work without pretending to solve multi-brain support in the same pass

## Required Test and Review Ratchets

Each implemented phase should add or tighten at least one of:

- architecture-boundary tests
- compatibility tests protecting Brain Format `1.0`
- integration tests for runtime-only child-discovery request handling
- integration tests for application-owned cross-plane projection
- regression tests for watcher, reconcile, and regen flow ownership
- tests that lock in the explicit single-brain runtime semantics

The plan is not complete if code merely moves files without increasing the
ability to detect architectural regression.

## Exit Criteria

This plan should be considered complete when all of the following are true:

- the architecture review can be rerun with the same template and shows no
  score below `6`
- `Contract and concept integrity`, `Dependency direction and orchestration`,
  and `State authority and persistence integrity` all score at least `7`
- Brain Format `1.0` remains unchanged
- REGEN refactor work can proceed without relying on broad transitional debt
  exceptions
- docs and tests no longer imply that runtime state is root-isolated when it is
  still single-brain by design

## Next Step

Implementation may proceed under this approved revision.

If execution clarifications become material, record them in
`docs/plans/plan_architecture-hardening_2_notes.md`.

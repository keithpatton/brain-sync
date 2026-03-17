# PLAN_architecture-hardening: Post-Refactor Architecture Hardening

## Status

Planning artifact only. This document defines the implementation plan for
hardening brain-sync after the package refactor so the next REGEN refactor and
future observability work land on stable subsystem boundaries instead of
carrying forward hidden architectural debt.

This stage does **not** authorize implementation by itself. Work should follow
the normal `docs/plans/` review and approval trail.f

## Objective

Raise the architecture to a state where further investment is predictable,
bounded, and materially easier to review.

The implementation must:

- preserve Brain Format `1.0` unless a later review proves a contract change is
unavoidable
- remove known concept drift at subsystem boundaries
- give REGEN a narrow public service boundary
- reduce runtime and transport blast radius
- establish clear seams for later operational observability

## Review Baseline

This plan is grounded in the repeatable architecture review artifacts under
`docs/architecture/reviews/`.

Primary review inputs:

- `docs/architecture/reviews/TEMPLATE.md`
- `docs/architecture/reviews/2026-03-17-baseline.md`

The baseline review should be treated as the current architecture scorecard and
risk map. Implementation work in this plan is intended to move those scores
upward without changing the review rubric between iterations.

## Authoritative Inputs

Implementation must treat these documents as the primary constraints:

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

The current architecture is not broken everywhere. It is broken in a few
specific places that contaminate the rest of the system:

- child-discovery intent is modeled across `application`, `brain`, `runtime`,
and `sync` with contradictory durability semantics
- REGEN is still exposed through a broad barrel export rather than a narrow
subsystem API
- `runtime/repository.py` remains a mixed-responsibility control point with
compatibility stubs and projection logic
- CLI and MCP still own important orchestration and policy directly
- root scoping and runtime isolation remain underdefined for future multi-brain
or observability work

These issues matter now because they directly increase the blast radius of the
next REGEN refactor and will make event observability less trustworthy if added
before subsystem ownership is tightened.

## Scope

In scope for the implementation stage:

- removal of current source-intent contract drift
- creation of a narrow REGEN public service boundary
- decomposition of runtime ownership into focused modules or owners
- migration of shared transport-owned workflows into `application/`
- targeted invalidation and observability-ready seams at repository and
orchestration boundaries
- architecture-boundary, compatibility, and regression tests needed to ratchet
the new shape
- documentation updates required by any ownership or dependency change

## Non-goals

- no Brain Format `1.0` bump by default
- no broad redesign of source adapters unless required by ownership cleanup
- no event ledger implementation in this plan
- no UI or CLI redesign unrelated to architectural ownership
- no speculative plugin system or public SDK work
- no performance micro-optimization outside architecture-level hot spots

## Fixed Design Decisions

### 1. Brain Format `1.0` stays fixed unless forced

Portable contract changes are out of scope for this plan unless a later review
proves that a correctness fix cannot be expressed within the current portable
format.

### 2. Child-discovery intent must have one owner

`fetch_children` and `child_path` must not continue as a split abstraction.
They need one of two outcomes:

- runtime-only, explicitly non-portable intent with one owner
- removal of the feature

The plan assumes the first choice only if it can be made unambiguous without a
Brain Format change.

### 3. REGEN must become a subsystem, not a barrel export

Sync, watcher, queue, CLI, and MCP code should depend on a narrow REGEN service
surface, not on engine internals or re-exported private helpers.

### 4. Application owns shareable workflows

If a workflow should behave the same in CLI and MCP, its orchestration belongs
in `application/` unless there is a strong transport-specific reason not to.

### 5. Observability hooks belong at semantic boundaries

This plan should leave the codebase ready for structured event emission at:

- repository boundaries
- orchestration boundaries
- long-running lifecycle transitions

It should not leave observability dependent on transport-local or engine-local
best effort hooks.

## Workstreams

## 1. Eliminate Source-Intent Contract Drift

Goal:
Make source registration and update intent internally coherent.

Required outcomes:

- one authoritative owner for child-discovery intent
- no durable model fields that are intentionally discarded on write
- no runtime APIs that imply persistence behavior they do not perform

Expected code pressure:

- `src/brain_sync/application/sources.py`
- `src/brain_sync/brain/manifest.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- related CLI, MCP, and tests

Acceptance criteria:

- source-intent behavior is explainable without caveats about dropped fields
- contract tests describe the actual surviving behavior
- any remaining one-shot behavior is explicitly runtime-only

## 2. Create a Narrow REGEN Service Boundary

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

## 3. Split Runtime Ownership

Goal:
Reduce `runtime/repository.py` from a monolithic control point to a stable set
of focused owners.

Required outcomes:

- sync cache, regen locks, daemon status, and token-event storage have clear
module ownership
- compatibility stubs are removed or replaced with truthful APIs
- runtime projection logic is easier to audit and test

Expected code pressure:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/runtime/paths.py`
- `src/brain_sync/runtime/token_tracking.py`
- all direct runtime callers

Acceptance criteria:

- runtime state responsibilities are separable by module without ambiguity
- no-op state mutation APIs are gone
- tests can target each runtime owner directly

## 4. Move Shared Orchestration Into Application

Goal:
Make CLI and MCP thin transports over shared workflows.

Required outcomes:

- shared query, regen, reconcile, and reporting flows move into `application/`
- transport code focuses on parsing, request shaping, and result presentation
- policy changes no longer require parallel edits in CLI and MCP

Expected code pressure:

- `src/brain_sync/application/`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`

Acceptance criteria:

- transport modules stop importing broad sets of lower subsystem packages
- shared behavior lives behind application-owned functions
- architecture-boundary exceptions shrink rather than expand

## 5. Prepare Observability and Scale Seams

Goal:
Leave the system structurally ready for event observability and larger brains.

Required outcomes:

- clear event-emission points at semantic boundaries
- targeted invalidation paths replace obvious whole-tree refresh patterns where
feasible
- root-scoping assumptions are made explicit

Expected code pressure:

- `src/brain_sync/query/area_index.py`
- `src/brain_sync/application/roots.py`
- `src/brain_sync/runtime/token_tracking.py`
- repository and orchestration boundaries touched by prior workstreams

Acceptance criteria:

- event hook locations are documented and testable
- obvious root-agnostic APIs stop accepting unused root arguments or become
genuinely root-aware
- architecture review rerun shows measurable improvement in observability and
scale-readiness scores

## Sequencing

Recommended order:

1. eliminate source-intent drift
2. create the REGEN service boundary
3. split runtime ownership
4. move shared orchestration into application
5. tighten observability and scale seams

Rationale:

- source-intent drift is the clearest architectural lie and should not survive
deeper refactors
- REGEN boundary cleanup should happen before the major REGEN redesign
- runtime decomposition is easier once REGEN ownership is clearer
- transport thinning is safer after the lower seams are more truthful
- observability and scale hooks should land on the cleaned-up seams, not the
old ones

## Required Test and Review Ratchets

Each implemented workstream should add or tighten at least one of:

- architecture-boundary tests
- compatibility tests protecting Brain Format `1.0`
- integration tests for write ordering and runtime rebuild behavior
- regression tests for watcher, reconcile, and regen flow ownership

The plan is not complete if code merely moves files without increasing the
ability to detect architectural regression.

## Exit Criteria

This plan should be considered complete when all of the following are true:

- the architecture review can be rerun with the same template and shows no
score below `6`
- `Contract and concept integrity`, `Dependency direction and orchestration`,
and `State authority and persistence integrity` all score at least `7`
- Brain Format `1.0` remains unchanged unless an explicit approved plan says
otherwise
- REGEN refactor work can proceed without relying on broad transitional debt
exceptions

## Next Step

The next required action is to review this plan and either:

- create `plan_architecture-hardening_review_1_<date>.md`, or
- if acceptable, create the corresponding approval artifact for the latest
revision per `docs/plans/README.md`


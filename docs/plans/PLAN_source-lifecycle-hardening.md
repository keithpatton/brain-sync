# PLAN_source-lifecycle-hardening: Source Lifecycle Hardening

## Status

Planning artifact only. This document defines the high-level implementation
plan for hardening source creation, update, movement, missing handling,
reconciliation, and finalization across portable brain state and machine-local
runtime state.

This stage does **not** approve implementation. It records the intended
contract, architectural direction, sequencing, and acceptance gates for later
review and approval.

## Objective

Make source lifecycle a durable, explicit subsystem so that:

- source truth is coordinated through one authoritative lifecycle surface
- portable brain state expresses durable source truth only
- runtime state owns volatile observation, timing, lease, and grace-window
  coordination only
- daemon, CLI, MCP, reconcile, watcher, and doctor stop performing private
  source lifecycle mutations
- regen can rely on source lifecycle state rather than compensating for
  inconsistent source handling elsewhere

The implementation should aim for "final form" within this layer of concern:
future source features should add new commands, observations, adapters, or
policies against the hardened lifecycle seam rather than reopening the
portable/runtime authority split.

## Authoritative Inputs

The implementation and review must treat these documents as the primary
constraints:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_source-state-boundary_2_approved_2026-03-19T19-05-47.md`
- `docs/plans/plan_source-fetch-hardening_2_approved_2026-03-18T11-00-51.md`

The implementation and review must also align with the current source, sync,
brain, runtime, and interface seams:

- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/application/source_state.py`
- `src/brain_sync/application/sync_events.py`
- `src/brain_sync/application/child_discovery.py`
- `src/brain_sync/application/reconcile.py`
- `src/brain_sync/application/doctor.py`
- `src/brain_sync/brain/manifest.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sources/base.py`
- `src/brain_sync/sources/confluence/attachments.py`

## Product Decisions Confirmed For This Plan

The following product decisions are confirmed and should be treated as settled
design input unless a later review artifact identifies a material conflict.

### 1. Portable missing timing leaves Brain Format `1.1`

`missing_since_utc` should be removed from portable source manifests.

It is observer-specific timing used for grace-window coordination and two-pass
deletion control. That makes it runtime coordination state, not portable brain
truth.

### 2. Portable `knowledge_state = missing` remains

Portable source manifests should continue to represent the durable source
lifecycle state, including `knowledge_state = missing`.

This is treated as durable lifecycle truth about whether the source is
currently settled, not as a machine-local timing detail.

### 3. Destructive finalization starts explicit-only

The daemon may determine eligibility for destructive finalization through
runtime coordination, but destructive finalization should initially require an
explicit lifecycle action rather than silently occurring inside background
convergence.

This is chosen because it is:

- safer under competing writers
- easier to reason about during hardening
- easier to test
- more auditable when something goes wrong

Future daemon auto-finalization may be considered only after the lifecycle
model proves stable and the policy can be expressed behind an explicit gate.

### 4. Portable `stale` stays compact

Portable `knowledge_state = stale` should remain one compact durable state.

The cause of staleness should live in runtime diagnostics, logs, and
operational events unless a future review proves that different stale causes
change cross-machine durable semantics.

### 5. Doctor remains non-destructive by default

Doctor may diagnose lifecycle drift and may invoke official non-private
lifecycle repair operations, but it should not auto-apply destructive source
finalization by default.

If current doctor behavior conflicts with this, the implementation should
tighten doctor authority to match the lifecycle contract rather than expanding
doctor authority further.

## Problem Statement

The current codebase has already improved portable/runtime state authority, but
source lifecycle correctness still depends on coordination spread across
multiple packages and call paths:

- interface-driven source commands
- daemon polling and scheduling
- watcher move and folder-change handling
- source reconciliation
- child discovery
- source materialization
- doctor repair flows

This creates several risks:

- competing writers can act against stale in-memory source projections
- destructive cleanup semantics are harder to reason about than they should be
- package boundaries are documented, but source lifecycle authority is still
  smeared across modules
- daemon currently uses upward imports into `application/` to reach lifecycle
  policy and source-state composition
- regen has to inherit and tolerate source lifecycle ambiguity

## Scope

In scope for the implementation stage:

- defining a source lifecycle contract expressed as:
  - lifecycle states
  - commands
  - observations
  - invariants
  - commit ordering rules
  - concurrency rules
  - failure semantics
- creating a sync-owned lifecycle surface for source operations
- moving source lifecycle ownership out of `application/` and into `sync/`
- removing or sharply reducing the current `sync -> application` upward
  pinhole
- moving portable missing timing from the manifest into runtime state
- hardening destructive finalization as a stricter protocol than ordinary
  transitions
- tightening doctor so it calls official lifecycle APIs rather than private
  source-management helpers
- updating architecture, schema, glossary, and rules docs as needed
- strengthening tests across unit, integration, system, and e2e tiers to
  chaos-test source lifecycle correctness

## Non-goals

- no broad redesign of regen policy or prompt behavior
- no broad redesign of query/search architecture
- no provider feature expansion beyond what source lifecycle hardening needs
- no portable stale-cause taxonomy unless later review proves a real durable
  need
- no immediate daemon auto-finalization policy
- no distributed multi-machine locking design beyond the supported single-brain
  / multi-runtime expectations already implied by the product

## Architectural Model

### Core ontology

This plan should treat the lifecycle architecture as reducer-first, not
event-first.

The intended concepts are:

- **commands**: intentional user or system requests
- **observations**: reported facts from watcher, reconcile, adapter checks,
  or repair scans
- **lifecycle policy**: valid transitions, state invariants, and trust rules
- **lifecycle orchestrator**: commit ordering, fresh-read revalidation,
  repository calls, and side effects
- **drivers**: daemon, reconcile, CLI, MCP, and doctor-repair entry points

The architecture should avoid turning "events" into an append-only authority
model. Commands and observations are inputs to deterministic lifecycle
reduction; they are not independently authoritative state.

### Package target

The desired ownership model is:

- `interfaces/` owns transport and command adaptation only
- `application/` owns thin transport-neutral use-case facades only
- `sync/` owns source lifecycle policy, orchestration, reconciliation, watcher
  reduction, and source materialization coordination
- `sources/` owns provider-specific remote behavior only
- `brain/` owns portable persistence
- `runtime/` owns machine-local coordination persistence

The likely code movement target inside `sync/` is conceptual rather than
prescriptive, but should separate at least:

- lifecycle policy
- lifecycle orchestration / transactions
- drivers / observer reducers

The implementation should avoid replacing today's sprawl with a single
god-object "manager."

## Lifecycle Invariants

The formal plan revision derived from this artifact must define and preserve at
least the following invariants:

1. Only official sync lifecycle APIs may mutate portable source lifecycle
   truth.
2. Watcher, reconcile, daemon loop code, CLI, MCP, and doctor must not mutate
   source manifests directly.
3. Portable source state must not depend on machine-local timing, grace-window
   state, or observer-specific pass counters.
4. `knowledge_state = stale` means the durable anchor exists, but the current
   materialized representation is not trusted for downstream use until a
   successful full re-materialization.
5. `knowledge_state = missing` is durable source lifecycle truth, not a
   deletion order by itself.
6. Destructive finalization must revalidate against the latest portable and
   runtime state before cleanup commits.
7. Regen must treat `missing` and `stale` as non-trustable source states
   without requiring special-case lifecycle mutation outside the sync layer.

## Portable vs Runtime State

### Portable source truth should contain

- identity
- type and URL
- durable settings such as `sync_attachments`
- `knowledge_path`
- `knowledge_state`
- last-settled baselines such as `content_hash`, `remote_fingerprint`, and
  `materialized_utc`

### Runtime source coordination should contain

- polling and scheduler state
- missing-observation timing and grace-window eligibility
- per-source operation lease / serialization state if needed
- one-shot child-discovery requests
- runtime diagnostics and operational event detail

The formal revision must inspect whether current runtime schema needs a new
table or fields to carry missing/finalization coordination after
`missing_since_utc` is removed from the manifest.

## Transition And Finalization Requirements

The formal revision derived from this artifact must include an explicit
transition table covering commands and observations.

At minimum it must specify, for each transition:

- allowed prior states
- resulting durable state
- portable mutations
- runtime mutations
- whether materialized files may remain, be replaced, or be deleted
- whether fresh-read revalidation is required

Finalization must be treated as stronger than an ordinary transition.

The implementation plan must define destructive finalization as requiring:

- source-level serialization or equivalent operation lease
- fresh manifest read
- fresh runtime coordination read
- revalidation that no move, reappearance, or repair invalidated the action
- idempotent cleanup semantics
- auditable operational recording

## Concurrency Model

The formal revision derived from this artifact must include an explicit
concurrency model covering:

- daemon versus CLI/MCP races
- watcher observations versus due-source polling
- reconcile versus explicit commands
- source-level serialization expectations
- shared-brain / multi-runtime expectations
- fresh-read-before-destructive-commit rules
- idempotency requirements for repeated commands or repeated observations

## Failure Model

The formal revision derived from this artifact must define the expected
consequences of process death or interruption at least at these points:

- after a manifest lifecycle write
- after a runtime coordination write
- after file materialization but before later lifecycle updates
- before destructive finalization completes
- during explicit finalization

The goal is that failures become restart-safe and diagnosable without leaving
portable and runtime state authority ambiguous.

## Workstreams

### Workstream 1: Contract And Rule Tightening

Goals:

- define lifecycle invariants, transition rules, concurrency rules, and
  failure semantics before topology changes
- update source manifest and glossary docs for removal of `missing_since_utc`
- tighten rules around doctor authority and destructive finalization

### Workstream 2: Sync-Owned Lifecycle Surface

Goals:

- create the sync-owned lifecycle policy and orchestration seams
- move source-state composition and lifecycle operations down from
  `application/`
- remove or reduce the current `sync -> application` upward pinhole

### Workstream 3: Runtime Coordination For Missing/Finalization

Goals:

- move grace-window and deletion eligibility out of the portable manifest
- add runtime support for missing observation timing and finalization
  eligibility
- make explicit-only destructive finalization the default path

### Workstream 4: Doctor And Driver Tightening

Goals:

- ensure doctor invokes official lifecycle APIs rather than private helpers
- ensure daemon, reconcile, watcher handling, and interfaces become drivers
  into lifecycle APIs rather than private state authorities

### Workstream 5: Fortress Testing

Goals:

- strengthen tests around lifecycle invariants and concurrency
- create explicit race and restart scenarios across the test matrix
- prove the hardened lifecycle seam under daemon on/off, CLI commands,
  competing demands, and restart recovery

## Acceptance Criteria

The implementation should not be considered complete unless it demonstrates at
least the following:

1. Portable source manifests no longer store `missing_since_utc`.
2. Portable `knowledge_state = missing` remains supported and documented.
3. Source lifecycle mutations are performed through official sync-owned APIs
   rather than private mutations spread across drivers.
4. The current `sync -> application` upward pinhole has been removed or
   sharply reduced with intentional rule/test updates.
5. Destructive finalization is explicit-only by default and revalidation-safe.
6. Doctor no longer performs destructive source finalization by default.
7. Existing source lifecycle behavior is preserved or intentionally revised
   with corresponding docs and tests.
8. The test matrix includes explicit contention, restart, and competing-writer
   scenarios for source lifecycle.

## Test Matrix Expectations

The implementation and review should plan coverage at these levels:

- **unit**: transition rules, invariants, command/observation reduction,
  stale/missing handling, revalidation rules, and architecture boundary tests
- **integration**: portable/runtime composition, explicit finalization flow,
  restart-safe lifecycle sequencing, and doctor/lifecycle interaction
- **system**: CLI behavior for source lifecycle commands and daemon process
  behavior under the new runtime coordination model
- **e2e**: daemon on/off scenarios, explicit commands competing with daemon
  work, move/delete/reappear flows, and shared-brain / isolated-runtime
  scenarios where practical

## Review Focus

The first review pass for the revision derived from this artifact should focus
especially on:

- whether explicit-only destructive finalization is specified tightly enough
- whether `stale` semantics remain compact but sufficiently sharp
- whether the proposed package movement creates a clean lifecycle seam without
  a new monolith
- whether the concurrency and failure model are explicit enough that the
  implementer will not have to guess through races or partial commits

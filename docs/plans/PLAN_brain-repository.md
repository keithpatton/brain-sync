# PLAN_brain-repository: Brain Repository Layer and State-Authority Boundary

## Status

Planning artifact only. This document defines the implementation plan for
introducing an internal brain repository layer that centralizes access to
portable brain state and managed filesystem mutations.

This stage does **not** change Brain Format `1.0`, portable schemas, or user
visible product behavior. It records the intended architecture, sequencing,
and acceptance gates for later implementation.

## Objective

Introduce a single internal boundary for correctness-critical work on the
portable brain so that brain-sync code no longer mutates or interprets brain
state through many ad hoc call sites.

The implementation must ensure that:

- portable brain reads and writes flow through a dedicated intermediary layer
- filesystem, manifest, sidecar, and managed-area operations share one
  authority model in code
- portable state and runtime state are expressed as separate concerns in the
  API surface, not only in documentation
- Windows-safe and portability-safe filesystem access becomes implicit in the
  boundary rather than a rule each caller must remember
- the resulting seam becomes the foundation for the planned runtime
  observability work and the later regeneration refactor

## System Boundary Context

At a higher level, the brain should be treated as a filesystem unit with only
two meaningful external actors:

- the **user**, including any user-mediated tool or process that can modify the
  brain on disk
- the **brain-sync process**, including daemon, CLI, MCP, sync, reconcile, and
  regeneration work performed by brain-sync itself

This model matters because brain-sync does not control the brain in the way an
application controls an internal database. The user is allowed to do anything
to their own filesystem:

- create, edit, move, rename, or delete knowledge files
- move or rename directories
- delete managed files
- partially corrupt portable state
- use external tools that perform these actions while brain-sync is running or
  offline

The system therefore must not assume that user behavior is constrained. The
portable brain contract defines what brain-sync supports and how it recovers or
reports drift, but user modification itself is not a violation that should make
the system crash. Some user actions may lead to warnings, drift findings, loss
of regenerable artifacts, or unrecoverable situations for specific features,
but they should still be handled as filesystem reality rather than as illegal
input.

Within brain-sync itself, the watcher is a special case. The watcher has direct
contact with the filesystem while the daemon is running because it must observe
raw changes at the edge of the system. That raw observation path is not, by
itself, the repository boundary.

The repository layer proposed in this plan should instead own the **runtime
brain contact that interprets or mutates portable brain state** after those raw
signals are observed. In other words:

- the watcher may continue to receive filesystem events directly
- the watcher should become a signal producer, not a portable-state authority
- the semantic consequences of watcher observations should flow through the
  repository boundary
- non-watcher brain-sync code paths should not bypass the repository when they
  read, interpret, repair, or mutate portable brain state

## Why This Matters Now

brain-sync has recently hardened its terminology and contract around the
meaning of the word "brain":

- the **brain** is the portable durable state rooted at the brain root
- **brain state** includes both `knowledge/` and portable managed files under
  `.brain-sync/`
- **runtime state** is machine-local, rebuildable, and outside the portable
  contract
- the filesystem is authoritative
- [generated meaning](../GLOSSARY.md) only makes sense if the underlying brain
  state is guarded correctly

That terminology is now clearer in the docs than in the code.

Today, important brain-state rules are still enforced from many different
places:

- watcher-driven folder moves update manifests and runtime state directly
- source reconciliation performs identity resolution and path healing itself
- sync/materialization updates manifests directly after write
- regeneration reads, classifies, cleans up, writes summaries, and persists
  state in one large orchestration module
- transitional no-op APIs still exist where old DB authority assumptions were
  only partially removed

This is the deeper issue beneath recent hardening work such as Windows long
path correctness and portable-state write discipline: the invariants are known,
but the system still relies on many callers to apply them consistently.

## Sequencing Context

This plan is intended to land **before** the approved runtime observability
work in [PLAN_runtime-observability.md](./PLAN_runtime-observability.md), and
before a larger regeneration refactor.

Planned sequencing:

1. brain repository layer
2. runtime observability and event ledger
3. regeneration refactor and algorithmic optimization

Rationale:

- observability is most valuable when it can instrument semantic state changes
  at a small number of trusted boundaries rather than many scattered call sites
- regeneration refactoring is safer once portable-brain IO and mutation rules
  are centralized behind a stable interface
- token-burn optimization work should be done after state authority and support
  visibility are easier to reason about

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/architecture/ARCHITECTURE.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/plans/PLAN_runtime-observability.md`
- `AGENTS.md`

Implementation must also align with the current code seams that already own
portable brain persistence, runtime state, and convergence behavior:

- `src/brain_sync/fileops.py`
- `src/brain_sync/layout.py`
- `src/brain_sync/manifest.py`
- `src/brain_sync/sidecar.py`
- `src/brain_sync/state.py`
- `src/brain_sync/pipeline.py`
- `src/brain_sync/commands/sources.py`
- `src/brain_sync/reconcile.py`
- `src/brain_sync/watcher.py`
- `src/brain_sync/regen.py`

## Context

The current architecture already describes the right durable/runtime split, but
the implementation still spreads brain-state logic across multiple modules.

Examples of current pressure points:

- folder move handling updates insight paths, source intent, and manifests from
  watcher logic rather than from a single state-authority boundary
- source reconciliation duplicates identity resolution, missing-file protocol,
  and path-healing behavior
- sync materialization owns part of the durable registration update path after
  file writes
- regen classification and regen execution mix filesystem discovery,
  portability rules, prompt assembly, and persistence
- runtime-oriented modules still expose transitional APIs that reflect prior DB
  authority assumptions

This creates several classes of architectural risk:

- invariants are easy to document but harder to enforce uniformly
- supportability work must instrument many call sites to reconstruct one
  logical state transition
- regen refactoring risks re-encoding filesystem and durable-state rules in yet
  another place
- future correctness fixes may become another cross-cutting audit rather than a
  focused change inside one boundary

## Scope

In scope for the implementation stage:

- a new internal repository layer for portable brain state and managed
  filesystem operations
- repository ownership of brain-sync runtime contact that interprets or mutates
  portable brain state after raw filesystem observation
- an explicit API split between portable brain mutations and runtime-only state
  coordination
- consolidation of source identity resolution and materialized-path healing
- consolidation of folder-move and missing/reappeared source handling
- consolidation of area-state reads/writes for summaries, sidecars, journals,
  and cleanup paths where appropriate
- migration of current callers to use the repository layer instead of directly
  coordinating manifests, sidecars, and managed paths
- structured operation results designed to support later observability
  instrumentation
- documentation and tests needed to establish the new boundary as a durable
  engineering rule

## Non-goals

- no Brain Format version bump
- no portable schema change for `brain.json`, source manifests, insight state,
  or managed frontmatter
- no relocation of summaries, journals, attachments, or source manifests
- no runtime event ledger implementation in this change
- no direct token-burn or prompt-quality optimization work in this change
- no broad redesign of query surfaces or source-adapter capabilities
- no attempt to make the repository layer a public plugin or SDK interface
- no attempt to route raw watchdog event capture itself through the repository
  layer

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material architectural problem.

### 1. Brain Format `1.0` stays unchanged by default

This work should be treated as an internalization of existing rules, not as a
reason to revise the portable contract.

The threshold for a portable contract change should remain high. If a later
review finds one is necessary, it should be justified as a correctness need,
not as a convenience for refactoring.

### 2. The repository layer is about authority, not abstraction for its own sake

The point of the repository layer is not to add ceremony. It is to make the
portable brain contract executable in one place.

The design should make it difficult for a caller to:

- bypass Windows-safe managed-file access
- blur portable and runtime state
- partially apply a filesystem convergence rule
- perform a durable write without returning a meaningful semantic outcome

### 3. Portable and runtime concerns must be separate in the boundary

One of the core architectural values now expressed in the docs is that
portable brain state and runtime state are not the same thing.

The new boundary should reinforce that distinction explicitly. Portable-brain
operations should not be hidden behind runtime-oriented helper names, and
runtime lifecycle writes should not require portable writes as a side effect.

### 4. Existing low-level helpers remain, but move below the boundary

Modules such as `fileops.py`, `manifest.py`, `sidecar.py`, and `layout.py`
remain useful. The change is not to delete them, but to make them supporting
primitives under a higher-level repository/service API.

### 5. Repository operations should be observability-ready

This plan does not implement the runtime event ledger, but it should make that
work easier.

Repository operations should therefore return structured semantic outcomes that
later observability code can record centrally, for example:

- source materialized
- source rediscovered
- source marked missing
- source deregistered after grace period
- area structure updated
- summary rewritten
- stale managed artifacts cleaned

### 6. Regeneration should become a client of the repository boundary

The later regeneration refactor should not continue to own raw portable-brain
persistence rules inside `regen.py`.

This plan should create the seam that lets regen focus more narrowly on:

- deterministic change classification
- prompt/context planning
- LLM invocation
- quality policy
- propagation logic

while relying on the repository layer for correctness-critical IO and durable
mutation behavior.

### 7. The watcher remains an edge observer, not a state-authority bypass

The watcher should continue to observe the filesystem directly because it is
the daemon's online signal path.

However, direct watcher contact with the filesystem must not imply that watcher
logic continues to own semantic brain-state interpretation or durable portable
state mutation. The repository boundary should absorb those responsibilities so
the watcher becomes closer to:

- raw event intake
- coarse event filtering and debouncing
- handoff of semantic follow-up work

rather than a place where convergence rules are independently implemented.

## Proposed Boundary Shape

The exact module split may evolve during implementation, but it should remain
equivalent to:

- `src/brain_sync/brain_repository.py`
- optional supporting domain types in a nearby neutral module

Tentative responsibility split:

### Brain repository responsibilities

- knowledge-area path normalization and managed-path resolution
- Windows-safe managed filesystem access for correctness-critical brain paths
- source identity lookup and materialized-path rediscovery
- durable source registration mutations
- portable area-state load/save helpers
- summary and journal write helpers
- managed-state cleanup for disappeared or emptied areas
- convergence operations such as move application, missing protocol, and path
  healing

### Runtime state responsibilities

`state.py` should remain the runtime-plane owner for:

- `sync_cache`
- `regen_locks`
- runtime DB lifecycle
- `daemon.json`
- later runtime event history from the observability plan

### Caller responsibilities after refactor

High-level modules should orchestrate behavior, not perform low-level
portable-brain coordination themselves.

Expected examples:

- `pipeline.py` asks the repository to commit a source materialization result
- `watcher.py` reports a move and receives structured effects
- `commands/sources.py` invokes a reconcile operation rather than inlining
  three-tier identity resolution logic
- `regen.py` asks the repository for area snapshots and persists semantic
  outcomes through repository calls

## Planned Workstreams

### Workstream 1: State-authority inventory

Goals:

- map all current portable-brain read/write paths
- classify each one against the hardened terminology

Implementation requirements:

- inventory where code currently reads or writes:
  - source manifests
  - managed summaries
  - insight-state sidecars
  - managed journals
  - attachment directories
  - portable path/identity state
- classify each call site as:
  - portable read
  - portable write
  - convergence/repair operation
  - runtime-only write
  - mixed portable/runtime path

Expected outcome:

- a concrete migration map showing which callers must be moved behind the new
  boundary first

### Workstream 2: Repository API and domain model

Goals:

- define the minimal stable internal boundary
- encode the portable/runtime split directly in code

Implementation requirements:

- add the repository module and domain result types
- define explicit APIs for:
  - source lookup and identity resolution
  - source registration/path updates
  - area snapshot loading
  - summary/journal/sidecar persistence
  - cleanup and convergence operations
- ensure APIs reflect durable intent and semantic result, not just raw file
  mutation

Expected outcome:

- a boundary that can be adopted incrementally by existing callers

### Workstream 3: Source and convergence migration

Goals:

- move source/materialization/convergence rules behind the repository

Implementation requirements:

- migrate relevant logic from:
  - `pipeline.py`
  - `commands/sources.py`
  - `watcher.py`
  - `reconcile.py`
- centralize:
  - three-tier source location resolution
  - target/materialized path healing
  - missing/reappeared source transitions
  - move application for folder-level convergence

Expected outcome:

- one coherent implementation of source convergence rules rather than multiple
  near-duplicates
- watcher-driven online detection remains at the edge, but its semantic
  consequences stop being implemented as a separate authority path

### Workstream 4: Area-state and managed-artifact migration

Goals:

- move correctness-critical area artifact behavior behind the repository

Implementation requirements:

- centralize loading and saving of:
  - summaries
  - insight-state sidecars
  - journals
  - managed cleanup paths
- make cleanup semantics explicit for:
  - deleted areas
  - empty areas
  - stale managed artifacts
- reduce direct summary/sidecar handling in regen and doctor flows

Expected outcome:

- one area-state owner for portable generated-meaning artifacts

### Workstream 5: Observability-ready outcomes

Goals:

- prepare the ground for [PLAN_runtime-observability.md](./PLAN_runtime-observability.md)
  without implementing it yet

Implementation requirements:

- ensure repository operations return structured outcomes suitable for later
  event emission
- identify the semantic transitions that should become observability events in
  the follow-on work
- avoid introducing a design that would force observability instrumentation
  back into many callers later

Expected outcome:

- the observability plan can instrument a small number of trusted state-change
  boundaries rather than reconstructing them from scattered call sites

### Workstream 6: Regen-facing seam preparation

Goals:

- make the later regen refactor smaller, safer, and more focused

Implementation requirements:

- update regen call paths so `regen.py` depends on repository operations for
  portable state access and durable writes where practical
- preserve existing behavior and on-disk artifacts while narrowing regen's
  responsibilities
- identify which remaining responsibilities should be addressed in the later
  dedicated regen refactor

Expected outcome:

- the later regen work starts from clearer boundaries and fewer mixed
  responsibilities

### Workstream 7: Tests and closeout

Goals:

- prove the new boundary protects the contract it is meant to encode

Implementation requirements:

- add unit tests for repository operations and outcome objects
- add integration coverage for:
  - moved source rediscovery
  - missing and reappeared sources
  - folder move convergence
  - deleted/empty area cleanup
  - portable vs runtime write separation
- add regression coverage for Windows-safe managed-path access where relevant
- update existing tests that currently depend on old scattered mutation paths

Primary test areas:

- `tests/unit/`
- `tests/integration/`
- selected `tests/e2e/` regressions where the boundary affects behavior

## Proposed Implementation Strategy

1. Inventory existing portable-brain mutation paths and classify them by
   authority type.
2. Introduce the repository module with a minimal internal API and domain
   result types.
3. Migrate source reconciliation and move/missing logic behind the repository.
4. Migrate area-state load/save/cleanup behavior behind the repository.
5. Update regen and adjacent orchestrators to consume the new boundary.
6. Add structured outcome types that later observability work can instrument.
7. Add tests and documentation updates that make the new boundary durable.

## Documentation and Versioning Obligations

This work is intended to change implementation boundaries, not the portable
brain contract.

Therefore:

- Brain Format remains `1.0`
- no portable manifest or sidecar schema change is expected
- no compatibility row change is expected from this plan alone
- no runtime DB schema change is expected from this plan alone

Expected documentation updates, if implementation lands as planned:

- `docs/architecture/ARCHITECTURE.md`
- possibly `AGENTS.md` if the repository-boundary rule should become an
  explicit long-lived engineering rule

Updates to `docs/brain/` or the shared contract docs should occur only if
review later concludes that a currently implicit invariant must become a
normative contract statement. That should be treated as an exception, not the
default outcome.

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. Brain Format `1.0` remains unchanged.
2. Portable brain mutations no longer depend on scattered multi-module
   coordination for core convergence paths.
3. Source materialization, rediscovery, missing/reappeared handling, and
   folder-move healing use the repository boundary.
4. Area summary/sidecar/journal and cleanup behavior have a single portable
   owner in code.
5. Runtime-only state remains outside the repository boundary or is clearly
   represented as a separate collaborator.
6. Correctness-critical managed filesystem access uses the shared safe path
   discipline through the boundary rather than by caller memory.
7. Repository operations return structured semantic outcomes suitable for later
   observability instrumentation.
8. Regen is measurably less responsible for raw portable-brain persistence than
   before, without changing current user-visible behavior.
9. The watcher remains a raw observation path, but no longer acts as an
   independent portable-state authority for semantic convergence behavior.
10. Tests cover the main convergence and state-authority scenarios affected by
   the boundary change.

## Risks and Mitigations

### Risk: The repository layer becomes a vague god object

Mitigation:

- keep responsibilities narrowly tied to portable-brain authority
- preserve runtime state as a separate concern
- use explicit domain operations rather than generic "save everything" helpers

### Risk: Migration leaves half-old, half-new authority paths

Mitigation:

- perform a concrete call-site inventory first
- migrate by behavior slice rather than by file ownership alone
- update tests alongside each migrated responsibility

### Risk: Overdesign delays observability and regen follow-on work

Mitigation:

- prefer the smallest boundary that centralizes current invariants
- optimize for practical adoption by current callers
- avoid speculative public abstractions or plugin-oriented design

### Risk: Review pressure pushes the work into an unnecessary schema change

Mitigation:

- keep the default rule explicit: internalize first, change contract only if
  correctness truly requires it
- document any proposed contract change separately if one emerges later

## Reviewer Focus

The reviewer should concentrate on these questions:

1. Does the proposed repository boundary encode the durable/runtime split
   clearly enough?
2. Is the scope small enough to be practical, but strong enough to eliminate
   the current scattered authority problem?
3. Are the proposed responsibilities in the right place between
   `brain_repository.py`, low-level helpers, and `state.py`?
4. Does the plan create the right foundation for
   [PLAN_runtime-observability.md](./PLAN_runtime-observability.md)?
5. Does it reduce the later regen refactor to a more focused problem without
   taking on too much regen redesign in this phase?
6. Is the commitment to avoid Brain Format or schema changes stated strongly
   enough?

## Next Step After Review

If review feedback identifies issues, the planner should create a revised plan
artifact rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

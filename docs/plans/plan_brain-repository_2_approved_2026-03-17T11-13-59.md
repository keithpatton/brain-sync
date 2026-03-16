# Approval

Approved: 2026-03-17T11-13-59
Approved by: codex-gpt-5

Notes:
- Revision 2 closes the prior scope gap by explicitly treating `attachments.py` and `commands/doctor.py` as part of the repository-boundary migration.
- The journal durability and append-only contract is now preserved as a fixed design decision, a cleanup constraint, and a testable acceptance gate.
- During implementation, keep doctor repair semantics aligned with the same repository-owned portable-state rules used by mainline convergence paths.

---

# plan_brain-repository_2: Brain Repository Layer and State-Authority Boundary

## Status

Revision 2 of the brain repository plan. This revision responds to
`plan_brain-repository_review_1_2026-03-17.md` by:

- explicitly including `attachments.py` and `commands/doctor.py` in the
  repository-boundary migration scope
- strengthening the journal durability and append-only contract so repository
  cleanup cannot regress the current portable-brain rules
- clarifying the separation between portable brain state and runtime state,
  including the fact that the current `state.py` module name is a legacy source
  of ambiguity rather than a statement that runtime DB state is brain state

This stage still does **not** change Brain Format `1.0`, portable schemas, or
user visible product behavior. It records the intended architecture,
sequencing, and acceptance gates for later implementation.

## Objective

Introduce a single internal boundary for correctness-critical work on the
portable brain so that brain-sync code no longer mutates or interprets brain
state through many ad hoc call sites.

The implementation must ensure that:

- portable brain reads and writes flow through a dedicated intermediary layer
- filesystem, manifest, sidecar, attachments, and managed-area operations
  share one authority model in code
- portable state and runtime state are expressed as separate concerns in the
  API surface, not only in documentation
- Windows-safe and portability-safe filesystem access becomes implicit in the
  boundary rather than a rule each caller must remember
- the resulting seam becomes the foundation for the approved runtime
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
- attachments handling writes and migrates durable managed attachment trees
- doctor directly reads and repairs manifests, managed identity, sidecars,
  attachment directories, and runtime rebuild state
- regeneration reads, classifies, cleans up, writes summaries, and persists
  state in one large orchestration module
- transitional runtime APIs still reflect prior DB-heavy authority assumptions

This is the deeper issue beneath recent hardening work such as Windows long
path correctness and portable-state write discipline: the invariants are known,
but the system still relies on many callers to apply them consistently.

## Sequencing Context

This plan is intended to land **before** the approved runtime observability
work in
`docs/plans/plan_runtime-observability_3_approved_2026-03-16T15-57-33.md`,
and before a larger regeneration refactor.

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
- `docs/plans/plan_runtime-observability_3_approved_2026-03-16T15-57-33.md`
- `AGENTS.md`

Implementation must also align with the current code seams that already own
portable brain persistence, runtime state, convergence behavior, and repair:

- `src/brain_sync/fileops.py`
- `src/brain_sync/layout.py`
- `src/brain_sync/manifest.py`
- `src/brain_sync/sidecar.py`
- `src/brain_sync/attachments.py`
- `src/brain_sync/state.py`
- `src/brain_sync/pipeline.py`
- `src/brain_sync/commands/sources.py`
- `src/brain_sync/commands/doctor.py`
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
- attachments handling owns part of the durable managed-files write path under
  `knowledge/**/.brain-sync/attachments/`
- doctor owns part of the portable-brain repair and convergence path when the
  brain is in drift or partial corruption
- regen classification and regen execution mix filesystem discovery,
  portability rules, prompt assembly, cleanup, and persistence
- the module name `state.py` still suggests generic "state" ownership even
  though in practice it is the runtime-plane owner for DB, daemon status, and
  related machine-local state

This creates several classes of architectural risk:

- invariants are easy to document but harder to enforce uniformly
- supportability work must instrument many call sites to reconstruct one
  logical state transition
- regen refactoring risks re-encoding filesystem and durable-state rules in yet
  another place
- repair logic can remain a durable-state bypass even if mainline flows are
  cleaned up
- runtime state can be confused with brain state by future contributors and
  agents if the boundary is not made explicit in both API shape and docs

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
- consolidation of attachment-directory handling and durable attachment
  lifecycle operations
- consolidation of area-state reads/writes for summaries, sidecars, journals,
  and cleanup paths where appropriate
- migration of `commands/doctor.py` repair flows onto repository-owned portable
  state semantics
- migration of current callers to use the repository layer instead of directly
  coordinating manifests, sidecars, attachments, and managed paths
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
- no required immediate rename of `state.py` in this plan revision, though the
  naming ambiguity should be treated as real architectural debt

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

Modules such as `fileops.py`, `manifest.py`, `sidecar.py`, `attachments.py`,
and `layout.py` remain useful. The change is not to delete them, but to make
them supporting primitives under a higher-level repository/service API.

### 5. Repository operations should be observability-ready

This plan does not implement the runtime event ledger, but it should make that
work easier.

Repository operations should therefore return structured semantic outcomes that
later observability code can record centrally, for example:

- source materialized
- source rediscovered
- source marked missing
- source deregistered after grace period
- attachments materialized
- attachments cleaned for a deregistered source
- area structure updated
- summary rewritten
- stale managed artifacts cleaned
- portable repair applied

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

### 8. Journals retain their current durable and append-only contract

Repository ownership of managed area artifacts must not weaken the existing
portable-brain rules for journals.

The repository design must preserve all of the following:

- journals are durable portable brain state
- journals are append-only in normal automated flows
- journals are not regenerable
- journals are not cleanup candidates in normal convergence, orphan cleanup, or
  deleted-area/empty-area cleanup flows

Repository journal APIs should therefore be append-oriented and preservation
oriented, not generic rewrite/delete helpers.

### 9. Runtime state naming ambiguity is real, but secondary to authority cleanup

The current `state.py` module is part of the runtime plane, not the portable
brain plane. That needs to be explicit in the repository design and in related
docs so agents and contributors do not treat runtime DB or daemon state as
brain state.

An eventual rename such as `runtime_state.py`, `runtime_store.py`, or similar
may be useful, but this plan should first make the boundary unambiguous in API
ownership and documentation. Naming cleanup can then be handled as a follow-on
if it still adds value.

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
- durable attachment lifecycle operations under managed attachment trees
- portable area-state load/save helpers
- summary and journal write helpers
- managed-state cleanup for disappeared or emptied areas
- repair helpers for doctor-facing portable-brain drift/convergence operations
- convergence operations such as move application, missing protocol, and path
  healing

### Runtime state responsibilities

The current `state.py` module should remain the runtime-plane owner for:

- `sync_cache`
- `regen_locks`
- runtime DB lifecycle
- `daemon.json`
- config/runtime-user-directory concerns already in the runtime plane
- later runtime event history from the observability plan

The important design rule is that runtime-plane ownership stays separate from
portable-brain ownership, regardless of whether the module name remains
`state.py` for a time.

### Caller responsibilities after refactor

High-level modules should orchestrate behavior, not perform low-level
portable-brain coordination themselves.

Expected examples:

- `pipeline.py` asks the repository to commit a source materialization result
- `attachments.py` becomes primarily a lower-level attachment-processing helper
  or collaborator under repository-owned durable semantics
- `watcher.py` reports a move and receives structured effects
- `commands/sources.py` invokes a reconcile operation rather than inlining
  three-tier identity resolution logic
- `commands/doctor.py` uses repository-owned portable repair/convergence rules
  rather than independently mutating manifests, sidecars, and attachments
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
- explicitly include the current authority surface in:
  - `attachments.py`
  - `commands/doctor.py`
  - `state.py` runtime ownership points that are often confused with brain
    state

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
  - attachment lifecycle operations
  - area snapshot loading
  - summary/journal/sidecar persistence
  - cleanup and convergence operations
  - doctor-facing repair helpers for portable brain drift
- ensure APIs reflect durable intent and semantic result, not just raw file
  mutation
- ensure journal APIs are append-only and preservation oriented

Expected outcome:

- a boundary that can be adopted incrementally by existing callers

### Workstream 3: Source, attachment, and convergence migration

Goals:

- move source/materialization/convergence rules behind the repository

Implementation requirements:

- migrate relevant logic from:
  - `pipeline.py`
  - `attachments.py`
  - `commands/sources.py`
  - `watcher.py`
  - `reconcile.py`
- centralize:
  - three-tier source location resolution
  - target/materialized path healing
  - missing/reappeared source transitions
  - move application for folder-level convergence
  - attachment directory lifecycle tied to source durability rules

Expected outcome:

- one coherent implementation of source and attachment convergence rules rather
  than multiple near-duplicates
- watcher-driven online detection remains at the edge, but its semantic
  consequences stop being implemented as a separate authority path

### Workstream 4: Area-state, journal, and managed-artifact migration

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
- preserve the journal durability contract during repository-owned cleanup
- reduce direct summary/sidecar handling in regen and doctor flows

Expected outcome:

- one area-state owner for portable generated-meaning artifacts
- cleanup behavior cannot accidentally treat journals as disposable managed
  files

### Workstream 5: Doctor and repair migration

Goals:

- move portable-brain repair semantics behind the same authority boundary used
  by mainline flows

Implementation requirements:

- migrate relevant `commands/doctor.py` portable-state reads and repairs onto
  repository operations
- ensure doctor uses the same portable-brain interpretation rules as normal
  convergence behavior
- preserve the distinction between:
  - portable-brain repair
  - runtime rebuild/reset
  - drift reporting without automatic mutation

Expected outcome:

- doctor no longer remains a material bypass around the repository boundary for
  portable state

### Workstream 6: Observability-ready outcomes

Goals:

- prepare the ground for
  `docs/plans/plan_runtime-observability_3_approved_2026-03-16T15-57-33.md`
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

### Workstream 7: Regen-facing seam preparation

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

### Workstream 8: Tests and closeout

Goals:

- prove the new boundary protects the contract it is meant to encode

Implementation requirements:

- add unit tests for repository operations and outcome objects
- add integration coverage for:
  - moved source rediscovery
  - missing and reappeared sources
  - folder move convergence
  - attachment lifecycle under source add/remove/move scenarios
  - deleted/empty area cleanup
  - journal preservation during cleanup
  - portable vs runtime write separation
  - doctor repair behavior through repository-owned portable semantics
- add regression coverage for Windows-safe managed-path access where relevant
- update existing tests that currently depend on old scattered mutation paths

Primary test areas:

- `tests/unit/`
- `tests/integration/`
- selected `tests/e2e/` regressions where the boundary affects behavior

## Proposed Implementation Strategy

1. Inventory existing portable-brain mutation paths and classify them by
   authority type, explicitly including attachments and doctor repair paths.
2. Introduce the repository module with a minimal internal API and domain
   result types.
3. Migrate source, attachment, and move/missing logic behind the repository.
4. Migrate area-state load/save/cleanup behavior behind the repository, with
   journal preservation rules encoded directly.
5. Migrate doctor-facing portable repair/convergence behavior onto the same
   boundary.
6. Update regen and adjacent orchestrators to consume the new boundary.
7. Add structured outcome types that later observability work can instrument.
8. Add tests and documentation updates that make the new boundary durable.

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
- possibly an architecture note clarifying that `state.py` is the runtime-plane
  owner and does not define brain-state authority

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
4. Attachment-directory durable lifecycle behavior uses the repository
   boundary.
5. Area summary/sidecar/journal and cleanup behavior have a single portable
   owner in code.
6. Doctor-facing portable repair behavior uses the repository boundary rather
   than remaining a material durable-state bypass.
7. Runtime-only state remains outside the repository boundary or is clearly
   represented as a separate collaborator.
8. Correctness-critical managed filesystem access uses the shared safe path
   discipline through the boundary rather than by caller memory.
9. Repository operations return structured semantic outcomes suitable for later
   observability instrumentation.
10. Regen is measurably less responsible for raw portable-brain persistence
    than before, without changing current user-visible behavior.
11. The watcher remains a raw observation path, but no longer acts as an
    independent portable-state authority for semantic convergence behavior.
12. Journal preservation is verified for deleted-area, empty-area, and stale
    managed-artifact cleanup flows.
13. Tests cover the main convergence and state-authority scenarios affected by
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

### Risk: Repair paths stay semantically different from mainline flows

Mitigation:

- treat `commands/doctor.py` as part of the repository-boundary migration, not
  as a follow-up convenience task
- ensure doctor uses the same portable-brain interpretation rules as the rest
  of the system

### Risk: Journal durability regresses under generalized cleanup helpers

Mitigation:

- encode journal preservation as a fixed design decision and acceptance gate
- expose append-oriented journal APIs rather than generic mutable helpers
- verify deleted/empty-area cleanup against journal preservation tests

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

### Risk: The `state.py` name continues to mislead contributors and agents

Mitigation:

- make runtime-plane ownership explicit in the repository plan and architecture
  docs
- treat a later rename as an optional cleanup once authority boundaries are in
  place

## Reviewer Focus

The reviewer should concentrate on these questions:

1. Does the proposed repository boundary encode the durable/runtime split
   clearly enough?
2. Is the scope small enough to be practical, but strong enough to eliminate
   the current scattered authority problem?
3. Are the proposed responsibilities in the right place between
   `brain_repository.py`, low-level helpers, `commands/doctor.py`,
   `attachments.py`, and the runtime-plane `state.py` layer?
4. Does the plan preserve the current journal durability and append-only
   contract strongly enough?
5. Does the plan create the right foundation for the approved observability
   work?
6. Does it reduce the later regen refactor to a more focused problem without
   taking on too much regen redesign in this phase?
7. Is the commitment to avoid Brain Format or schema changes stated strongly
   enough?

## Next Step After Review

If review feedback identifies issues, the planner should create a revised plan
artifact rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

# PLAN_move-semantics: Area Move Preservation And Source Move Cleanup

## Status

Planning artifact only. This document defines the implementation plan for
separating two different move operations in brain-sync:

- semantic area moves that preserve a knowledge path as a whole
- single-source moves that reclassify one source into a different area

This artifact does **not** authorize implementation by itself. Work should
follow the normal `docs/plans/` review and approval trail before code changes
begin.

## Objective

Introduce a first-class `move-path` operation for whole-area moves and tighten
the semantics of the existing single-source `move` operation so brain-sync
stops leaving stale managed artifacts behind when a source move empties an
area.

The implementation must ensure that:

- `move-path` means "this knowledge area moved as a whole"
- `move-path` preserves area-scoped meaning by moving the whole
  `knowledge/<path>/.brain-sync/` subtree together with manual and synced
  content
- `move-path` is the highest-value addition for current operator workflows and
  should land before any destructive path-removal command
- single-source `move` remains a source-scoped reclassification operation, not
  a whole-area preservation operation
- after a successful single-source move, brain-sync checks whether the old
  area is now devoid of real content
- if the old area is content-empty, brain-sync removes stale regenerable
  managed artifacts there and prunes attachment remnants that no longer have a
  valid owner in that emptied area
- journals are intentionally left in place during single-source move cleanup
  because they are area-scoped historical artifacts and automatic relocation or
  deletion would be overly destructive
- single-source `move` reports the old-path cleanup outcome explicitly so users
  are told whether the old path was removed, preserved because managed content
  remains, or left alone because real content still exists
- docs and operator-facing contracts explicitly explain that piecemeal moves
  can strand journal history in the old area

## Authoritative Inputs

Implementation and review must treat these documents as primary authority:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`

Implementation must also align with the current owning seams for source moves,
folder moves, regen cleanup, runtime path tracking, and public command
surfaces:

- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/interfaces/cli/parser.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/brain/fileops.py`
- `src/brain_sync/brain/tree.py`
- `src/brain_sync/regen/evaluation.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/runtime/repository.py`

Implementation must prove behavior in the relevant test seams:

- `tests/unit/test_watcher_moves.py`
- `tests/unit/test_regen.py`
- `tests/unit/test_fileops.py`
- `tests/integration/`
- `tests/mcp/`
- `tests/system/`

## Context

The current design mixes two materially different meanings under the same
intuitive umbrella of "move":

- watcher/reconcile folder moves already behave like whole-area moves
- explicit `brain-sync move` is source-scoped and moves only source-owned
  artifacts

That mismatch is currently visible in three ways.

First, journals are bound to knowledge paths rather than to individual synced
sources. A single-source move therefore changes semantic context rather than
preserving it. The moved source file can relocate, but the old area's journal
history does not naturally follow.

Second, explicit single-source move can leave the old area with stale managed
artifacts such as summaries, sidecars, attachments, and `.brain-sync`
directories even when no real content remains there.

Third, the system already contains an internal folder-move path that updates
manifest and runtime knowledge-path prefixes and enqueues regen for the moved
area and affected parents. That existing behavior is closer to the semantics
operators expect when they mean "this area moved."

This plan treats those observations as one cohesive design correction:

- make whole-area moves first-class
- keep single-source move intentionally narrower
- make single-source cleanup remove stale derived state without guessing about
  journal ownership
- defer destructive path-removal work until the preservation-first move model
  is in place

## Problem Statement

brain-sync currently lacks a user-facing operation whose meaning is:

- move this knowledge path as a whole
- preserve the area's managed interpretation and journal history
- update all registered synced-source bookkeeping under that path

At the same time, the existing single-source move has an under-specified
cleanup story:

- it correctly moves the source-owned markdown file and source-owned
  attachments
- it does not clean up stale area-managed summaries or sidecars from the old
  path
- it can leave empty or semantically empty `.brain-sync` folders behind
- it leaves journals behind implicitly rather than by clearly documented policy

That makes source move feel more semantically destructive than the command
surface suggests, and it leaves operators with confusing leftover managed
state.

## Scope

In scope for the implementation stage:

- add a first-class `move-path` operation for knowledge-area moves
- expose `move-path` through the application layer, CLI, and MCP
- define `move-path` as moving:
  - manual knowledge files under the area
  - synced-source materialized files under the area
  - the co-located `.brain-sync/` subtree, including insights, journals, and
    attachments
- reuse the existing folder-move machinery where practical rather than
  duplicating move semantics
- update manifest and runtime knowledge-path references for sources and regen
  state affected by a path move
- enqueue regen for the moved path and the parent paths whose child structure
  changed
- make `move-path` support same-parent path changes cleanly so a later
  `rename-path` wrapper can reuse the same behavior without semantic drift
- preserve the existing single-source `move` operation, but document it as a
  source reclassification operation
- after successful single-source move, evaluate whether the old area is devoid
  of real content under the same content-discovery rules used by regen
- if the old area is content-empty after single-source move, remove stale
  regenerable insights and stale attachment remnants there
- leave journals intact during single-source move cleanup
- add explicit post-move status messaging for the old path, such as:
  - old path removed from disk because no content remained
  - old path still contains preserved managed content under `.brain-sync/`
  - old path still contains remaining knowledge content and was not cleaned
- document the semantic and operational difference between `move` and
  `move-path`

## Non-goals

- no attempt to make single-source `move` preserve journal continuity
- no automatic relocation of journal history during piecemeal source moves
- no automatic deletion of journals during single-source cleanup
- no `remove-path` command in this phase
- no destructive path-removal preview/confirm workflow in this phase
- no redesign of journal storage from area-scoped to source-scoped in this
  phase
- no change to watcher/reconcile folder-move semantics beyond what is required
  to align explicit `move-path` with the existing model
- no attempt to infer user intent and silently upgrade single-source moves into
  whole-area moves
- no hidden cleanup of manual files left in the old area after single-source
  move
- no requirement to ship a separate `rename-path` command in this phase if
  `move-path` already supports same-parent path changes cleanly

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material issue.

### 1. `move-path` and `move` are different semantic operations

The product model should distinguish:

- `move-path`: the area moved
- `move`: one source moved to a different area

They must remain separate commands and separate result contracts. `move-path`
must not be an implicit mode of the existing single-source move.

### 2. `move-path` preserves area-scoped managed meaning

`move-path` should preserve the whole area's co-located managed state by moving
the `.brain-sync/` subtree together with the content tree.

That includes:

- summaries and sidecars under `.brain-sync/insights/`
- journals under `.brain-sync/journal/`
- source-owned attachment directories under `.brain-sync/attachments/`

This is the operation users should use when their intent is "this area moved
without changing what it means."

### 3. `remove-path` is deferred until after preservation-first move semantics land

There is a real future use case for destructive path removal, but it should not
be part of this phase.

If added later, `remove-path` should mean actual removal from disk and should
use an explicit preview/confirm workflow because of its destructive nature.

For now, the implementation should focus on:

- making whole-area moves easy and correct
- making single-source moves clean up stale derived artifacts better

### 4. Single-source `move` remains a semantic reclassification

Single-source move should be treated as a reclassification of one source into a
new area, not as a neutral rename.

The implementation and docs should state plainly that:

- source-owned files move
- area-scoped journals do not follow
- regenerated meaning in the new area starts from the new area's context

### 5. Old-path cleanup for single-source move is gated by real-content emptiness

After a successful single-source move, brain-sync should check whether the old
path still has any real content.

The emptiness test must use the same effective content rules as regen and tree
discovery:

- readable knowledge files count as content
- non-hidden child content directories count as content
- dot-directories such as `.brain-sync/` do not count as content

Cleanup must happen only when the old area is devoid of content under that
definition.

### 6. Single-source cleanup removes stale derived artifacts, not journals

If the old area is content-empty after single-source move, cleanup should:

- remove stale regenerable insight artifacts and sidecar state
- prune stale attachment remnants that no longer correspond to valid
  source-owned content in that emptied area
- prune empty directories that become empty after that cleanup

Cleanup must not:

- relocate old journals to the new area
- delete journals automatically

Journals are left intact because deleting or migrating them during a piecemeal
move would guess at meaning the system cannot safely reconstruct.

### 7. Post-move user messaging should be explicit and generic

After single-source move, the command surface should report what happened to the
old path using user-facing outcome language rather than asking the user to
inspect disk manually.

Preferred messaging should stay generic about preserved managed content. It
should not force journal-specific terminology into the normal success path.

Representative outcomes:

- old path removed from disk because no remaining content was present
- old path still contains preserved managed content under `.brain-sync/`
- old path still contains remaining knowledge content and was not cleaned

### 8. The documentation must call out the piecemeal-move consequence explicitly

The user-facing contract should state that piecemeal source moves can leave old
area journal history behind even when the old area becomes otherwise empty.

The recommended operator guidance should be:

- use `move-path` when an area moved as a whole
- use source `move` when reclassifying one source

### 9. `path` is the right command-surface term; `area` remains the semantic term

CLI, MCP, result payloads, and path-manipulation APIs should use `path`
terminology because these operations target relative knowledge-tree paths,
including edge cases that may not currently qualify as meaningful areas.

Docs and architecture explanation may still use `area` when describing meaning,
summary generation, journals, and semantic ownership.

## Planned Workstreams

### Workstream 1: Define the command and result contracts

Goals:

- define the exact public meaning of `move-path`
- tighten and document the exact public meaning of single-source `move`
- define whether a separate user-facing `rename-path` wrapper is needed now or
  whether same-parent `move-path` support is sufficient for this phase

Implementation requirements:

- choose the application-layer function signatures and result payloads
- define accepted selectors and path arguments
- define CLI and MCP naming and result fields
- choose the user-facing naming relationship between:
  - `move-path`
  - an optional `rename-path` wrapper or alias
- define handled outcomes such as:
  - moved
  - not_found
  - lease_conflict
  - no_op or unchanged-path, if applicable

Primary modules:

- `src/brain_sync/application/sources.py`
- `src/brain_sync/interfaces/cli/parser.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`

### Workstream 2: Promote folder-move machinery into an explicit path-move operation

Goals:

- make whole-area move a first-class command rather than a watcher-only repair
  path

Implementation requirements:

- build an explicit application operation on top of the current folder-move
  ownership seam
- ensure same-parent path changes work cleanly so rename behavior does not need
  a separate storage model
- ensure runtime knowledge-path state is renamed consistently
- ensure affected manifests under the moved prefix are updated consistently
- ensure query index invalidation and operational events reflect explicit
  command use as well as watcher use
- enqueue regen for the moved path and its affected parent paths

Primary modules:

- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/application/sources.py`

### Workstream 3: Add post-move old-area cleanup for single-source move

Goals:

- remove stale managed residue after piecemeal source moves without deleting
  journals
- make the old-path outcome visible to users at command time

Implementation requirements:

- after the file move commits, evaluate the old path using the existing
  content-discovery rules
- if the old area is content-empty:
  - remove regenerable insights and sidecar state
  - remove stale source-owned attachment remnants left in the old area
  - prune empty directories that become empty
- if journals remain, leave the old area and `.brain-sync` subtree in place
- if manual files or child content directories remain, perform no old-area
  cleanup
- return or log explicit old-path cleanup status instead of leaving users to
  infer the result from disk state

Primary modules:

- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/brain/fileops.py`
- `src/brain_sync/regen/evaluation.py`
- `src/brain_sync/brain/tree.py`

### Workstream 4: Documentation and contract alignment

Goals:

- make the semantic distinction clear to operators and reviewers

Implementation requirements:

- update sync lifecycle docs for explicit `move-path`
- update user-facing command docs
- document the semantics of journal preservation for `move-path`
- document the semantics of journal non-migration for single-source `move`
- document that piecemeal moves can leave journal history in the old area

Primary docs:

- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`

## Acceptance Criteria

The implementation is acceptable only if all of the following are true.

### Path move preservation

- there is a first-class explicit `move-path` command or equivalent public
  operation
- invoking `move-path` moves the whole area tree, including `.brain-sync/`
- synced-source manifests under the moved prefix now point at the new path
- runtime regen-path tracking under the moved prefix is updated consistently
- the moved area and affected parent areas are queued or prepared for regen
  according to the established folder-move model
- same-parent path changes are supported cleanly, whether exposed directly
  through `move-path` or through a thin `rename-path` wrapper

### Single-source move cleanup

- single-source `move` still moves only source-owned artifacts
- after single-source move, the old path is evaluated for content emptiness
- if the old path is content-empty except for managed state, stale
  regenerable insights are removed
- stale attachments in that emptied old path are removed or pruned correctly
- journals are left untouched
- if journals are the only remaining artifacts, the old area may remain on
  disk and that behavior is documented
- the command reports whether the old path:
  - was removed from disk
  - retained preserved managed content
  - retained real knowledge content and therefore was not cleaned

### Semantics and docs

- docs distinguish clearly between path move and source move
- docs state that journals are knowledge-path-scoped
- docs tell operators to use `move-path` for whole-area moves
- docs warn that piecemeal source moves do not preserve journal continuity
- docs use `path` terminology for command surfaces and `area` terminology for
  semantic explanation where appropriate

### Proof

- tests prove `move-path` preserves `.brain-sync/journal/` and related managed
  artifacts
- tests prove single-source move cleanup removes stale insights in an emptied
  old area
- tests prove single-source move cleanup does not delete journals
- tests prove no cleanup runs when old-area manual content still exists
- CLI and MCP tests cover the new public command surface and handled outcomes

## Testing Strategy

At minimum, implementation should add or update proof in these layers:

- unit tests for path-prefix updates, old-area emptiness checks, cleanup
  gating, and journal preservation
- integration tests for explicit `move-path` and single-source `move`
  interactions with manifests, runtime state, and managed files
- system or MCP tests for command-surface behavior and result contracts

Representative scenarios that must be covered:

- path move of an area containing:
  - manual files
  - synced-source files
  - summaries
  - journals
  - attachments
- single-source move from an area that still contains another real content file
- single-source move that empties the old area except for stale insights
- single-source move that empties the old area except for journals
- single-source move where the old area still has a child content directory

## Risks And Review Focus

Review should challenge the plan on these points:

- whether explicit `move-path` should directly move filesystem content or
  should remain a metadata-repair command layered on top of a user-executed
  filesystem move
- whether a separate user-facing `rename-path` command materially improves
  operator clarity or whether same-parent `move-path` is sufficient initially
- whether attachment cleanup after single-source move can be defined narrowly
  enough to avoid deleting data that no longer belongs to the moved source
- whether any existing doctor or reconcile behaviors become redundant or
  contradictory after path-move introduction
- whether the docs draw a sufficiently sharp line between "preserve meaning"
  and "reclassify source"

## Implementation Notes For Later Phases

The intended implementation direction is:

- add `move-path` as the explicit preservation operation
- keep single-source move conservative
- prefer cleaning stale derived artifacts over trying to preserve historical
  meaning incorrectly

If review discovers that explicit filesystem-moving path commands are too risky
for the current surface, a narrower first phase may still be acceptable if it
lands:

- explicit path-prefix move semantics
- explicit docs steering users toward whole-area moves
- old-area cleanup for single-source move

But that fallback should be treated as a scoped revision decision, not as an
implicit weakening during implementation.

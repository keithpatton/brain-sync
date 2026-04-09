# plan_move-semantics_2_2026-03-27: Explicit Path Move Contract And Narrow Source-Move Cleanup

## Status

Planning artifact only.

This revision supersedes `docs/plans/PLAN_move-semantics.md` for this topic.
It incorporates the blocking feedback from:

- `docs/plans/plan_move-semantics_review_1_2026-03-27.md`

This revision does **not** approve implementation by itself.

## Objective

Define an approvable phase-1 move contract that:

- adds a first-class `move-path` command that performs an explicit on-disk move
  of a knowledge subtree and preserves its co-located managed meaning
- keeps single-source `move` as a source reclassification operation
- adds safe, narrow, registration-aware cleanup for old paths after
  single-source `move`
- defers destructive path deletion to a later feature

The implementation must ensure that:

- `move-path` is the primary operator tool for "this subtree moved"
- `move-path` performs the filesystem move itself and then applies the existing
  folder-move bookkeeping/update logic
- same-parent rename is supported in phase 1 through `move-path`; a separate
  `rename-path` wrapper is explicitly deferred
- single-source `move` cleans up only a narrowly defined safe target set in the
  old path
- single-source `move` never relocates or deletes journals
- move-related result contracts and docs use `path` terminology at the command
  surface

## Relationship To Prior Artifacts

This revision preserves the root plan's core direction:

- whole-path preservation and source reclassification are different semantic
  operations
- journals are knowledge-path-scoped durable history
- `remove-path` is not required for phase 1

This revision resolves the three reviewer-blocking gaps by choosing:

- one exact phase-1 `move-path` public contract
- one exact old-path cleanup algorithm for single-source `move`
- one explicit regen/proof contract for same-parent rename and pure path moves

## Authoritative Inputs

Primary authority for this revision:

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
- `docs/plans/PLAN_move-semantics.md`
- `docs/plans/plan_move-semantics_review_1_2026-03-27.md`

Implementation and review must align with these owning seams:

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

## Problem Statement

The current root plan got the semantics mostly right but left three
implementation-shaping decisions too open:

- whether `move-path` is a real command that moves disk content or only a
  metadata/path-repair command layered on top of a user-performed move
- what exact data single-source `move` may delete from the old path
- what exact regen outcome is expected for pure path moves and same-parent
  renames when semantic content is unchanged

Those are public-contract questions, not implementation trivia. This revision
chooses them explicitly.

## Scope

In scope for phase 1:

- add `move-path --from <old_path> --to <new_path>` to CLI and the equivalent
  MCP/application operation
- make `move-path` perform the on-disk subtree move within `knowledge/`
- preserve the moved subtree's `.brain-sync/` directory as part of the move
- update manifests, runtime path prefixes, query invalidation, and regen
  enqueueing using the existing folder-move ownership seam
- support same-parent rename via `move-path`
- keep single-source `move` as a source-only reclassification command
- after single-source `move`, run narrow old-path cleanup only when the plan's
  safety preconditions are met
- report single-source old-path cleanup status explicitly
- update docs and tests to the chosen path-based public contract

## Non-goals

- no `remove-path` command in this phase
- no `rename-path` command in this phase
- no metadata-only "adopt an already moved subtree" public command in this
  phase
- no automatic journal relocation or deletion during single-source `move`
- no generic "delete unowned managed artifacts under this path" sweep
- no change to the current area-scoped journal ownership model

## Fixed Design Decisions

### 1. `move-path` is an explicit filesystem-moving command in phase 1

The phase-1 public contract is:

- `move-path` performs the subtree move on disk under `knowledge/`
- after the move succeeds, it applies the existing folder-move bookkeeping:
  - rename runtime knowledge-path prefixes
  - update affected manifests under the moved prefix
  - invalidate query state for moved and affected parent paths
  - enqueue regen for the moved path and affected parent paths

It is **not** a metadata-repair command for an already moved folder in this
phase.

The existing watcher/reconcile repair path remains valuable internally and for
manual drift, but the new user-facing contract is an explicit command that does
the move itself.

### 2. Same-parent rename ships through `move-path`; `rename-path` is deferred

Phase 1 ships one path-moving public command:

- `move-path`

That command must support same-parent path changes cleanly, including leaf-name
changes that users would conceptually describe as renames.

`rename-path` is explicitly deferred. If added later, it should be only a thin
wrapper over the exact same semantics, not a separate implementation model.

### 3. Command-surface terminology uses `path`

CLI, MCP, and result payloads should use:

- `path`
- `old_path`
- `new_path`
- `from_path`
- `to_path`

Docs may still use `area` when explaining meaning, journals, summaries, and
 semantic ownership. The transport contract should stay path-based.

### 4. `remove-path` is deferred

`remove-path` has a real future use case, but it is not part of phase 1.

If later added, it should mean actual deletion from disk and should use an
explicit preview/confirm workflow because of its destructive nature.

Phase 1 does not depend on `remove-path` to make `move-path` or single-source
`move` safe.

### 5. Single-source `move` remains a semantic reclassification

Single-source `move` means:

- move the source-owned materialized file
- move the moved source's source-owned attachment directory when present
- update that source's registration target path

It does **not** mean:

- preserve area journal continuity
- preserve the old area's meaning as a whole
- move the old area's `.brain-sync/journal/` history to the new path

### 6. Old-path cleanup after single-source `move` is narrow and registration-aware

Old-path cleanup after single-source `move` is allowed only when **all** of the
following are true:

- the move committed successfully
- the old path is content-empty under the same discovery rules used by regen:
  - no readable knowledge files
  - no non-hidden child content directories
- there is no other still-registered source, besides the moved source, whose
  `target_path` is the old path or a descendant of the old path

When those preconditions hold, cleanup may touch only this exact target set:

- regenerable per-path insight artifacts for the old path
  - summary and sidecar state under `.brain-sync/insights/`
- the moved source's old attachment directory if it still exists there after
  the move and the moved source is no longer registered to that old path
- empty directories that become empty as a direct result of those permitted
  cleanup steps

Cleanup must not touch:

- journals
- attachment directories for any other source
- generic managed files under `.brain-sync/` that are not part of the narrow
  target set above

### 7. Old-path removal from disk is all-or-nothing and only after allowed cleanup

The old path itself may be removed from disk only if, after the permitted
cleanup above, the directory contains no remaining entries at all.

That means:

- if journals remain, the old path may remain on disk
- if any preserved managed artifacts remain, the old path may remain on disk
- if any real content remains, no old-path cleanup runs

The implementation must not treat journal-only or preserved-managed-only paths
as removable.

### 8. Post-move status messaging is explicit and generic

Single-source `move` must report the old-path outcome explicitly. Preferred
user-facing result language is:

- old path removed from disk because no remaining content was present
- old path still contains preserved managed content under `.brain-sync/`
- old path still contains remaining knowledge content and was not cleaned

The normal success path should stay generic about preserved managed content. It
should not use "orphaned journals" as the default operator-facing phrasing.

### 9. Regen contract for `move-path` and same-parent rename is explicit

For pure path moves and same-parent renames where semantic content is unchanged:

- moved journals stay under the moved subtree and are preserved by the path move
- the moved subtree must not get a journal append solely because the path moved
- the moved subtree must not be force-rewritten solely because the path moved

Expected regen settlement:

- moved subtree root:
  - expected to settle `unchanged` when its readable files, child summaries,
    and internal child/file names are unchanged
- descendants of the moved subtree:
  - expected to settle `unchanged` when untouched internally
- same-parent rename:
  - the common parent is expected to settle `structure_only` when child
    membership/content is unchanged but the child name changed
- reparent/path-depth move:
  - source and destination parents may legitimately settle `content_changed`
    when child-summary membership changes
  - they may settle `structure_only` only if the hash model supports that for
    the specific case

The approved contract is therefore:

- no forced content churn for the moved subtree itself solely because of path
  movement
- no journal creation solely because of rename/path movement
- parent paths follow normal evaluation based on their actual content/structure
  hashes after enqueueing

## Planned Workstreams

### Workstream 1: Ship one exact public path-move surface

Goals:

- expose one unambiguous phase-1 path-move contract

Implementation requirements:

- add one application-layer path-move operation
- add CLI `move-path --from <old_path> --to <new_path>`
- add the equivalent MCP path-move tool contract
- ensure the public result contract is path-based
- support same-parent rename through this same command surface

### Workstream 2: Reuse folder-move bookkeeping after explicit disk move

Goals:

- avoid duplicating ownership logic already present in folder-move repair paths

Implementation requirements:

- perform the on-disk subtree move under `knowledge/`
- reuse or extract the existing folder-move update logic so the explicit
  command and watcher/reconcile paths share one bookkeeping model
- update runtime path prefixes, affected manifests, query invalidation, and
  regen enqueueing consistently

### Workstream 3: Add narrow old-path cleanup to single-source `move`

Goals:

- remove stale derived residue without widening the deletion boundary

Implementation requirements:

- implement the exact cleanup preconditions from Decision 6
- implement the exact target set from Decision 6
- implement the exact old-path removal rule from Decision 7
- report the old-path outcome using the explicit generic statuses from
  Decision 8

### Workstream 4: Strengthen docs and proof to the chosen contract

Goals:

- align docs and tests with the exact public contract rather than leaving
  alternative surfaces acceptable

Implementation requirements:

- document `move-path` as the whole-subtree preservation operation
- document single-source `move` as source reclassification
- document that journals are path-scoped and therefore do not follow
  piecemeal source moves
- document that `rename-path` and `remove-path` are deferred in phase 1
- prove same-parent rename behavior through `move-path`

## Acceptance Criteria

The implementation is acceptable only if all of the following are true.

### Public contract

- CLI and MCP expose one exact phase-1 path-move surface: `move-path`
- `move-path` performs the disk move itself
- same-parent rename is supported through `move-path`
- no separate `rename-path` or `remove-path` command ships in this phase
- result payloads and command help use path terminology

### Path-move preservation

- `move-path` moves the whole subtree, including `.brain-sync/`
- `.brain-sync/journal/` moves with the subtree intact
- manifests under the moved prefix now point at the new path
- runtime knowledge-path state under the moved prefix is updated consistently
- moved and affected parent paths are enqueued for regen according to the
  folder-move model

### Same-parent rename regen behavior

- a same-parent rename through `move-path` does not append journals solely
  because of the rename
- the moved subtree itself does not undergo forced content rewrite solely
  because of the rename
- proof shows parent-path structure handling explicitly, with the expected
  `structure_only` settlement where hashes support it

### Single-source `move` cleanup

- cleanup runs only when the exact preconditions in Decision 6 are met
- cleanup removes regenerable per-path insights for the old path
- cleanup removes only the moved source's old attachment directory when that
  exact narrow condition applies
- cleanup never deletes attachment directories for other registered sources
- cleanup never deletes journals
- the old path is removed from disk only when it becomes fully empty after the
  allowed cleanup
- if journals or preserved managed artifacts remain, the old path may remain on
  disk and that outcome is reported explicitly

### Documentation

- docs distinguish path-move preservation from source-move reclassification
- docs say journals are knowledge-path-scoped
- docs tell operators to use `move-path` for whole-area or rename intent
- docs state that `remove-path` and `rename-path` are deferred in phase 1

## Testing Strategy

Required proof must include:

- path move of a subtree containing:
  - manual files
  - synced-source files
  - insights
  - journals
  - attachments
- same-parent rename through `move-path`
- proof that `.brain-sync/journal/` moved with the subtree
- proof that same-parent rename does not create journal churn
- proof that the moved subtree itself does not force summary rewrite solely
  because the path changed
- proof that parent-path regen settles according to the chosen contract for
  rename-only movement
- single-source move where old path is empty except stale insights
- single-source move where old path is empty except journals
- single-source move where old path still has manual content
- single-source move where old path still has a child content directory
- single-source move where another registered source remains anchored under the
  old path and cleanup therefore must not run
- CLI and MCP proof for the chosen command names and path-based result payloads

## Risks And Review Focus

Review should focus on:

- whether the explicit on-disk `move-path` command can safely reuse the current
  folder-move bookkeeping seam without duplicating logic
- whether the narrow attachment-cleanup rule is precise enough to avoid
  accidental deletion
- whether the renamed-path regen expectations are specific enough for approval
- whether the docs and result contracts make the path-vs-area distinction clear
  without confusing operators

## Implementation Notes

This revision intentionally chooses the conservative deletion boundary:

- preservation-first whole-subtree path moves
- narrow cleanup after source reclassification
- no destructive path-removal primitive in phase 1

That is the smallest coherent package that addresses the real operator pain
point while keeping journals and unrelated managed state safe.

# plan_move-semantics_3_2026-03-27: Explicit Path Move With Preflight Leases And Rollback

## Status

Planning artifact only.

This revision supersedes:

- `docs/plans/plan_move-semantics_2_2026-03-27.md`

for this topic. It incorporates the blocking feedback from:

- `docs/plans/plan_move-semantics_2_review_1_2026-03-27.md`

This revision does **not** approve implementation by itself.

## Objective

Define an approvable phase-1 move contract that:

- adds a first-class `move-path` command that performs an explicit on-disk move
  of a knowledge subtree and preserves its co-located managed meaning
- makes `move-path` safe in the presence of contained registered sources by
  preflighting and acquiring their leases before any disk mutation
- makes `move-path` all-or-nothing from the user's point of view, with
  rollback on mid-command failure
- keeps single-source `move` as a source reclassification operation with narrow
  old-path cleanup
- defers `rename-path` and `remove-path` as separate commands

## Relationship To Prior Artifacts

This revision preserves the phase-1 product direction from revision 2:

- `move-path` is the whole-subtree preservation operation
- same-parent rename is supported through `move-path`
- single-source `move` is source reclassification, not area preservation
- journals are knowledge-path-scoped and do not follow piecemeal source moves
- `remove-path` is deferred

This revision resolves the remaining blocking gap by choosing:

- the `move-path` conflict strategy for contained source leases
- the atomicity contract
- the rollback/failure contract
- the handled result states for the public surface

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
- `docs/plans/plan_move-semantics_2_2026-03-27.md`
- `docs/plans/plan_move-semantics_2_review_1_2026-03-27.md`

Implementation and review must align with these owning seams:

- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/interfaces/cli/parser.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/regen/evaluation.py`
- `src/brain_sync/brain/tree.py`

## Phase-1 Public Contract

Phase 1 ships one exact path-moving public command:

- `move-path --from <old_path> --to <new_path>`

Equivalent MCP and application-layer operations must expose the same semantics.

`move-path` means:

- move the subtree on disk under `knowledge/`
- move the whole co-located `.brain-sync/` subtree with it
- update contained registrations/runtime path rows consistently
- enqueue normal regen for the moved path and affected parents

Phase 1 explicitly does **not** ship:

- `rename-path` as a separate command
- `remove-path`
- a metadata-only "adopt an already moved subtree" variant

Same-parent rename is supported through `move-path`.

## Fixed Design Decisions

### 1. `move-path` is an explicit filesystem-moving command

`move-path` performs the disk move itself. It is not a repair/adoption command
for a folder the user already moved manually.

### 2. `move-path` preflights contained source leases before any disk mutation

Before moving anything on disk, `move-path` must:

- discover all registered sources whose `target_path` is the source path or a
  descendant of it
- sort them by canonical ID for deterministic behavior
- attempt to acquire each contained source lifecycle lease up front

If any contained source has an active conflicting lease:

- the command returns a handled `lease_conflict` result
- no filesystem move occurs
- any leases already acquired during preflight are released before returning

Phase 1 does not use watcher-style best-effort skip semantics for an explicit
user command.

### 3. `move-path` is all-or-nothing from the user's point of view

The approved user-facing contract is atomic in intent:

- either the subtree move and bookkeeping complete successfully
- or the command restores the prior state before returning a handled rollback
  outcome

The command must not intentionally leave the subtree moved on disk while
manifest/runtime bookkeeping remains partially committed.

### 4. `move-path` rolls back on mid-command failure after the disk move

After all contained leases are acquired, the command may:

- move the subtree on disk
- apply the bookkeeping phase:
  - runtime path-prefix rename
  - manifest updates under the moved prefix
  - query invalidation
  - regen enqueueing/event recording

If the disk move succeeds but bookkeeping cannot fully commit:

- the command must attempt rollback
- rollback means:
  - move the subtree back to the original path on disk
  - undo any partial bookkeeping updates made by the command
  - release all acquired contained source leases

If rollback succeeds:

- the command returns a handled `rolled_back` result
- the result must make clear that the move did not commit

If rollback fails:

- the command fails loudly rather than returning success
- the command must record enough operational context to make later reconcile or
  manual repair possible
- the command must invalidate both involved paths so stale indexes are not
  treated as authoritative

Rollback failure is the only phase-1 case where consistency may require later
repair; it is not an acceptable silent outcome.

### 5. `move-path` handled outcomes are explicit

Phase-1 handled outcomes for the public surface are:

- `moved`
- `not_found`
- `unchanged_path`
- `destination_conflict`
- `lease_conflict`
- `rolled_back`

Contract notes:

- `not_found`: source path does not exist under `knowledge/`
- `unchanged_path`: normalized source and destination are the same
- `destination_conflict`: destination already exists, overlaps illegally with
  the source path, or is otherwise not movable for this command
- `lease_conflict`: at least one contained registered source is actively leased
  by another owner
- `rolled_back`: the command started mutating but restored prior state after a
  failure before commit completed

CLI, MCP, docs, and tests should share these exact state names unless a review
artifact later changes them intentionally.

### 6. Same-parent rename ships through `move-path`; `rename-path` is deferred

Phase 1 supports same-parent renames through `move-path`. A separate
`rename-path` wrapper is deferred.

### 7. `remove-path` is deferred

`remove-path` is not part of phase 1. If added later, it should mean real disk
deletion and use a preview/confirm workflow.

### 8. Single-source `move` remains a semantic reclassification

Single-source `move` means:

- move the source-owned materialized file
- move that source's source-owned attachment directory when present
- update that source's registration target path

It does not preserve whole-area history or relocate journals.

### 9. Single-source old-path cleanup remains narrow and registration-aware

After single-source `move`, old-path cleanup is allowed only when all of the
following are true:

- the source move committed successfully
- the old path is content-empty under normal regen/tree discovery rules
- there is no other still-registered source, besides the moved source, whose
  `target_path` is the old path or a descendant of it

When those preconditions hold, cleanup may touch only:

- regenerable per-path insight artifacts for the old path
- the moved source's old attachment directory if it still exists there and the
  moved source is no longer registered to that old path
- empty directories that become empty as a direct result of those steps

Cleanup must never delete journals or attachment directories for other sources.

### 10. Old-path removal after single-source `move` remains all-or-nothing

The old path itself may be removed from disk only if, after the allowed
cleanup, it contains no remaining entries at all.

If journals or other intentionally preserved managed artifacts remain, the path
may remain on disk.

### 11. Regen contract for `move-path` and rename is unchanged from revision 2

For pure path moves and same-parent renames where semantic content is
unchanged:

- the moved subtree must not append journals solely because of the path move
- the moved subtree itself must not be force-rewritten solely because of the
  path move
- same-parent rename should result in parent-path structure handling under the
  normal hash model rather than forced content churn

## Planned Workstreams

### Workstream 1: Add the explicit path-move command surface

Implementation requirements:

- add one application-layer path-move operation
- add CLI `move-path --from <old_path> --to <new_path>`
- add the equivalent MCP operation
- expose the handled result states from Decision 5

### Workstream 2: Implement preflight lease acquisition and atomic move behavior

Implementation requirements:

- enumerate contained registered sources under the source path
- acquire their leases deterministically before disk mutation
- release acquired leases on every non-success exit path
- reject lease conflicts before filesystem mutation

### Workstream 3: Implement rollback-aware path move

Implementation requirements:

- perform the disk move only after preflight succeeds
- reuse/extract the existing folder-move bookkeeping seam
- if bookkeeping fails after the disk move, attempt full rollback
- return `rolled_back` on successful rollback
- fail loudly and record reconcile-oriented context if rollback itself fails

### Workstream 4: Keep single-source `move` conservative

Implementation requirements:

- preserve the narrow cleanup rules from revision 2
- report the explicit generic old-path outcomes after move

### Workstream 5: Align docs and proof to the chosen safety contract

Implementation requirements:

- document that `move-path` is an explicit moving command
- document that it preflights contained source leases
- document the handled result states
- prove lease-conflict, rollback, and destination-conflict behavior

## Acceptance Criteria

The implementation is acceptable only if all of the following are true.

### Public contract

- CLI and MCP expose one exact phase-1 path-move surface: `move-path`
- `move-path` performs the disk move itself
- same-parent rename is supported through `move-path`
- `rename-path` and `remove-path` do not ship in this phase
- result payloads and command help use path terminology and the exact handled
  states from Decision 5

### Conflict safety

- if any contained registered source has an active conflicting lease,
  `move-path` returns `lease_conflict`
- in that case, no disk mutation occurs
- any partially acquired leases from preflight are released before return

### Atomicity and rollback

- `move-path` behaves all-or-nothing from the user's point of view
- if bookkeeping fails after the disk move, rollback is attempted
- if rollback succeeds, the command returns `rolled_back`
- after a successful rollback, the subtree is back at the original path and
  manifests/runtime state are restored to their prior committed state
- if rollback fails, the command does not return success and records enough
  context for later repair

### Success behavior

- on success, `move-path` moves the whole subtree including `.brain-sync/`
- manifests under the moved prefix point at the new path
- runtime path-prefix state is updated consistently
- moved and affected parent paths are enqueued for regen according to the
  folder-move model

### Single-source `move`

- single-source `move` still moves only source-owned artifacts
- old-path cleanup remains narrow and registration-aware
- journals are left untouched
- old-path outcome messaging is explicit

## Testing Strategy

Required proof must include:

- `move-path` success for a subtree containing manual files, synced-source
  files, insights, journals, and attachments
- same-parent rename through `move-path`
- contained-source lease-conflict preflight with proof that no disk mutation
  occurred
- destination-conflict handling
- `unchanged_path` handling
- injected bookkeeping failure after the disk move with proof that rollback
  restored the original state and the command returned `rolled_back`
- explicit failure-path proof for rollback failure handling at the unit level,
  even if it is hard to exercise end-to-end
- single-source move scenarios from revision 2, including journal-preservation
  and negative cleanup cases

## Risks And Review Focus

Review should focus on:

- whether the per-source lease preflight is sufficient without introducing a
  new path-level lease model
- whether the rollback contract is realistic and specific enough for
  implementation
- whether the `rolled_back` handled outcome is the right public contract
- whether the success, conflict, and failure proofs are strong enough to treat
  `move-path` as the preservation-first operator path

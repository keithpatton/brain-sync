# Review

Plan under review: `docs/plans/plan_move-semantics_2_2026-03-27.md`
Reviewer: Codex GPT-5
Date: 2026-03-27

## Verdict

Changes required.

Create a new plan revision that resolves the blocking finding in this review.
This review artifact does not approve the plan and does not authorize
implementation.

## Summary

This revision resolves the three earlier blockers well.

The scope split is now clean:

- `move-path` is explicitly the whole-subtree preservation operation
- single-source `move` is explicitly the source reclassification operation
- `remove-path` and `rename-path` are both clearly deferred

The journal semantics are also much stronger now. The plan correctly treats
journals as knowledge-path-scoped durable artifacts, narrows old-path cleanup
to a registration-aware target set, and gives a substantially clearer regen
contract for same-parent rename and pure path moves.

I am still not approving it because one material implementation-shaping choice
remains open: the command-safety and failure contract for an explicit
filesystem-moving `move-path` command.

## Blocking Finding

### 1. The plan still does not choose the atomicity and conflict contract for explicit `move-path`

The revision now says `move-path` is a user-facing command that performs the
on-disk subtree move itself and then reuses the existing folder-move
bookkeeping seam.

That is the right product direction, but it creates a new safety question that
the current watcher/reconcile model never had to answer:

- what must happen if one or more registered sources inside the subtree are
  under active source lifecycle lease when `move-path` is invoked
- what must happen if the on-disk move succeeds but the follow-on manifest or
  runtime updates fail before the command completes

Current authority and code context make this a blocking contract gap rather
than an implementation detail:

- `docs/RULES.md` says lifecycle-owning command entrypoints must not silently
  proceed when they encounter an active conflicting source lease, and command
  surfaces should return handled `lease_conflict` outcomes
- those same rules say watcher/reconcile paths are softer and may skip leased
  sources after revalidation
- `src/brain_sync/sync/lifecycle.py::apply_folder_move()` is currently that
  softer watcher/reconcile-style path: it updates what it can and skips leased
  sources individually
- the runtime seam today provides only per-source lifecycle leases
  (`acquire_source_lifecycle_lease`, `source_lifecycle_commit_fence`), not a
  path-level lease model

An explicit `move-path` command cannot safely inherit watcher-style
best-effort/skip semantics without further choice. Once the command itself has
already moved the subtree on disk, "skip the leased source and continue" could
leave the portable filesystem, manifests, and runtime path rows intentionally
out of sync until later repair. That is not obviously acceptable for a
first-class command surface that is supposed to be the preservation-first
operator path.

The plan therefore still leaves the implementer to guess among materially
different command contracts, for example:

- preflight all contained registered sources, fail the command before the disk
  move if any conflicting lease exists, and return a handled conflict outcome
- move the subtree first and then attempt per-source updates, relying on later
  reconcile to repair any skipped or failed rows
- move the subtree first but require rollback if any contained source cannot be
  committed consistently

Those choices have different user-visible behavior, different failure safety,
and different proof obligations. They should be chosen in the plan.

Required revision:

- define the `move-path` conflict strategy explicitly for contained registered
  sources with active leases
- define whether `move-path` is required to be all-or-nothing from the user's
  point of view
- define the failure/rollback contract if the filesystem move succeeds but the
  bookkeeping/update phase cannot complete
- define the handled command outcomes for the new public surface at least for:
  - source path not found
  - destination path already exists or is otherwise not movable
  - conflicting contained source lease
  - no-op / unchanged path, if supported
- strengthen acceptance criteria and tests to prove the chosen failure model,
  not only the success cases

At minimum, the next revision should make clear whether phase 1 requires:

- preflight lease/conflict detection before any disk mutation
- rollback on mid-command failure after the disk move
- CLI and MCP handled outcome coverage for those cases

## Non-blocking Suggestions

- Keep the narrow old-path cleanup rule exactly as conservative as it is now.
  That part of the revision is much safer and clearer than the root plan.
- Preserve the explicit statement that journal-only old paths may remain on
  disk. That is an important clarification for both reviewers and operators.
- When revising the `move-path` result contract, mirror the existing source
  command style and name the payload fields and result states directly so CLI,
  MCP, and tests all share one surface.

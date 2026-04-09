# Review

Plan under review: `docs/plans/PLAN_move-semantics.md`
Reviewer: Codex GPT-5
Date: 2026-03-27

## Verdict

Changes required.

Create a new plan revision that resolves the blocking findings in this review.
This review artifact does not approve the plan and does not authorize
implementation.

## Summary

The direction is strong: the plan correctly separates whole-path preservation
from single-source reclassification, and it is also right to treat journals as
knowledge-path-scoped durable history rather than as source-owned artifacts.

I am not approving this root plan yet because three implementation-shaping
choices remain too open for an approvable handoff:

- the exact first-phase public contract for `move-path` versus a possible
  `rename-path` wrapper
- the precise old-path cleanup algorithm after single-source move
- the rename/path-move regen contract and the proof required to demonstrate it

Those are not code-level details. They change the public command surface,
destructive-cleanup boundary, and expected behavioral proof, so they should be
chosen in the plan rather than left to implementation judgment.

## Blocking Findings

### 1. The plan still does not choose the exact first-phase public contract for `move-path`

The plan says `move-path` should become a first-class operation, but it leaves
two core product decisions unresolved:

- whether `move-path` itself physically moves filesystem content or instead
  remains a metadata/path-repair operation layered on top of a user-executed
  folder move
- whether same-parent rename is exposed only through `move-path` in this phase
  or through a separate `rename-path` wrapper/alias

That ambiguity appears in multiple places:

- Workstream 1 says implementation should "define whether a separate
  user-facing `rename-path` wrapper is needed now"
- the review-focus section still asks whether `move-path` should directly move
  filesystem content or remain a metadata-repair command
- the acceptance criteria allow either direct `move-path` exposure or a thin
  `rename-path` wrapper without choosing one exact public surface

Current code reality makes this a real contract question rather than a naming
detail. `src/brain_sync/sync/lifecycle.py` currently has `apply_folder_move()`,
which assumes the filesystem move has already happened and then updates
manifests, runtime path prefixes, query invalidation, and regen enqueueing. It
is not yet an explicit user command that itself moves directories on disk.

Required revision:

- choose one exact phase-1 `move-path` contract:
  - explicit command that performs the filesystem move and then applies the
    folder-move repair/update logic, or
  - explicit command that adopts an already-moved path and never performs the
    disk move itself
- choose the rename surface for this phase:
  - `move-path` alone supports same-parent rename and `rename-path` is
    explicitly deferred, or
  - `rename-path` ships now as a thin wrapper/alias over the same behavior
- make the CLI, MCP, docs, and acceptance criteria name that one chosen public
  surface rather than leaving both variants acceptable

### 2. The old-path cleanup rules after single-source move are still too vague to be safe

The plan is directionally correct that journals are area-scoped history and
must not be relocated or deleted during a piecemeal source move. The unsafe
gap is everything around that rule.

The current cleanup language still leaves the implementer guessing what counts
as deletable managed residue:

- "prune stale attachment remnants that no longer have a valid owner"
- "remove stale regenerable insights and stale attachment remnants"
- "old path removed from disk because no remaining content was present"

That is not specific enough for an approval gate because the current repo
contains different ownership models:

- journals are knowledge-path-scoped durable artifacts
- attachments are per-source managed directories
- insights are per-path regenerable artifacts

Current code also does not provide one obvious generic primitive for "valid
owner" cleanup. `src/brain_sync/brain/repository.py` has narrowly scoped
source-artifact operations such as `remove_source_managed_artifacts()` and
per-source attachment-dir moves, but not a general "delete anything in this old
area that looks unowned" operation. Meanwhile `src/brain_sync/regen/evaluation.py`
and `src/brain_sync/brain/tree.py` treat `.brain-sync/` as excluded from real
content discovery, so a path can be content-empty while still containing
journals or managed attachment directories.

That creates concrete unresolved cases the implementer should not have to
decide alone:

- if the old path is content-empty but still contains journals, exactly which
  directories may be pruned and which must remain
- whether cleanup may touch attachment directories for any source other than
  the moved source
- what happens if another registered source is still anchored under the old
  path in `awaiting` or `missing`
- what exact condition allows the old path itself to be removed from disk

Required revision:

- define the cleanup target set exactly
- define the ownership rule for attachment cleanup exactly
- define the old-path removal rule exactly
- state explicitly that when journals remain, the directory may remain on disk
  even if it is no longer a current semantic knowledge area

The safest likely direction is to make cleanup intentionally narrow and
registration-aware rather than "best effort":

- remove regenerable per-path insights only when the old path is content-empty
- remove only attachment directories that the plan can prove are no longer
  owned by any still-registered source anchored under that path
- preserve the old path whenever journals or any other intentionally preserved
  managed artifacts remain

The revised acceptance criteria and tests should include the negative cases
that exercise accidental-deletion risk, not just happy-path cleanup:

- old path empty except journals
- old path empty except stale insights
- old path still has a child content directory
- old path still has manual content
- old path still has a registered unrelated source or managed attachment
  directory that must not be deleted

### 3. The regen contract for path moves and renames is not explicit enough, and the proof bar is too weak

The plan says moved paths and affected parents should be enqueued for regen,
but it does not finish the more important semantic claim: what *kind* of regen
outcome is expected for a pure path move or same-parent rename when content is
unchanged.

Current repo behavior already distinguishes structure-only versus content
changes:

- `src/brain_sync/regen/evaluation.py` classifies rename-only cases via
  unchanged content hash plus changed structure hash
- current folder-move handling in `src/brain_sync/sync/lifecycle.py` enqueues
  the moved path and affected parents, relying on normal evaluation afterward

That matters because approval should not let an implementation silently choose
between:

- enqueue plus structure-only settlement with no content rewrite, or
- forced content regen / summary rewrite / journal append on every path move

For same-parent rename in particular, the expected behavior should be stated
plainly. If content is unchanged, the plan should say whether the approved
behavior is:

- queue the moved path and relevant parent path(s)
- preserve journals in place under the moved subtree
- settle as structure-only metadata change when hashes support that
- avoid summary churn and avoid journal creation solely because of a rename

Required revision:

- state the expected regen outcome for pure path moves and same-parent renames
  when semantic content is unchanged
- state whether parent paths are expected to settle as structure-only as well,
  or whether any parent rewrite is expected
- strengthen acceptance criteria and tests to prove that behavior explicitly

The revised proof should include:

- a same-parent rename scenario through the chosen public surface
- proof that `.brain-sync/journal/` moves with `move-path`
- proof that rename-only path moves do not create content-driven churn when the
  content hash is unchanged
- CLI and MCP proof for the chosen command/result terminology, using `path`
  terms in the command surface and payloads rather than leaving that to docs
  prose alone
- explicit proof of the old-path cleanup status contract for single-source move

## Non-blocking Suggestions

- Keep the strong separation between `path` as the command-surface term and
  `area` as the semantic explanation term. That part of the plan is good; it
  just needs the transport/result proof strengthened.
- If `remove-path` is deferred, add one sentence that the deferred command is
  not needed to make `move-path` or same-parent rename safe in phase 1, so the
  implementation boundary stays visibly narrow.
- If the planner chooses "no `rename-path` in this phase," say so plainly in
  the objective and acceptance criteria rather than only as a non-goal.

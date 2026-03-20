# plan_source-lifecycle-hardening_5 Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-03-20
**Reviewed document:** `docs/plans/plan_source-lifecycle-hardening_5_2026-03-20.md`
**Reviewed against:**
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
- `README.md`
- `docs/plans/plan_source-lifecycle-hardening_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_2_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_3_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_4_review_1_2026-03-20.md`
- `docs/plans/plan_source-state-boundary_2_approved_2026-03-19T19-05-47.md`
- `docs/plans/plan_source-fetch-hardening_2_approved_2026-03-18T11-00-51.md`
- current code reality in:
  - `src/brain_sync/sync/daemon.py`
  - `src/brain_sync/sync/pipeline.py`
  - `src/brain_sync/application/sources.py`
  - `src/brain_sync/application/source_state.py`
  - `src/brain_sync/application/sync_events.py`
  - `src/brain_sync/application/child_discovery.py`
  - `src/brain_sync/application/reconcile.py`
  - `src/brain_sync/application/doctor.py`
  - `src/brain_sync/interfaces/cli/handlers.py`
  - `src/brain_sync/interfaces/mcp/server.py`
  - `src/brain_sync/brain/manifest.py`
  - `src/brain_sync/brain/repository.py`
  - `src/brain_sync/runtime/repository.py`
  - `src/brain_sync/sources/base.py`
  - `src/brain_sync/sources/confluence/attachments.py`
  - `tests/unit/test_architecture_boundaries.py`

**Purpose:** Review revision 5 with a challenge-first standard, with special
focus on finalization-eligibility exactness, cross-machine `missing`
determinism after portable `missing_since_utc` removal, the exact CLI/MCP
finalization contract, the per-source-only finalization scope, concreteness of
documented terminal result states, breadth of the reserved `BrainRepository`
lifecycle-mutation boundary against current code reality, correct scoping of
that reservation relative to `sync/pipeline.py`, doctor diagnostics, and
`sources/confluence/attachments.py`, the zero `sync -> application` target,
runtime-table ordering, documentation-governance compliance, anti-monolith
`sync/` structure, and fortress-level testing.

---

## Verdict

Changes required.

Revision 5 resolves almost all of the earlier blockers. The local
finalization-eligibility rule is now exact enough, the cross-machine `missing`
contract is materially deterministic, the dedicated `finalize-missing` /
`brain_sync_finalize_missing` surfaces are much sharper, the registration
ordering ambiguity is fixed, and the test fortress is close to approval grade.

I am still withholding approval because one authority-surface loophole remains
open in the architecture-enforcement section, and one user-facing contract edge
is still loose enough that implementation would have to invent behavior.

This review artifact does **not** approve the plan and does **not** authorize
implementation. Create a new plan revision rather than editing
`plan_source-lifecycle-hardening_5_2026-03-20.md` in place.

---

## Critical Issues

### C1. The reserved `BrainRepository` lifecycle-mutation set still does not fully close the source-movement authority surface against current code reality

Revision 5 is materially stronger than revision 4 on architecture enforcement.
It now reserves a much broader method set to `sync/lifecycle.py` and
`sync/finalization.py`:

- `docs/plans/plan_source-lifecycle-hardening_5_2026-03-20.md:636-664`
- `docs/plans/plan_source-lifecycle-hardening_5_2026-03-20.md:686-689`
- `docs/plans/plan_source-lifecycle-hardening_5_2026-03-20.md:894-897`

That closes the obvious current seams in `application/sources.py` and
`application/doctor.py` for:

- `save_source_manifest()`
- `update_source_sync_settings()`
- `mark_source_missing()`
- `clear_source_missing()`
- `mark_source_stale()`
- `set_source_area_path()`
- `sync_manifest_to_found_path()`
- `delete_source_registration()`
- `remove_source_owned_files()`
- `remove_source_managed_artifacts()`

But one current production lifecycle mutation path still falls outside the
reserved set:

- `src/brain_sync/application/sync_events.py:88-128`
- `src/brain_sync/brain/repository.py:548-577`

`BrainRepository.apply_folder_move_to_manifests()` is not a neutral helper. It
rewrites `knowledge_path` across manifests and can set `knowledge_state =
stale` on moved sources. That is exactly the kind of portable source-lifecycle
mutation the plan says should flow through one authoritative lifecycle surface
for movement as well as missing/finalization:

- `docs/plans/plan_source-lifecycle-hardening_5_2026-03-20.md:16-19`
- `docs/plans/plan_source-lifecycle-hardening_5_2026-03-20.md:696-700`

Because `apply_folder_move_to_manifests()` is omitted from the reserved-method
contract, the proposed AST call-site tests could all pass while a separate
production module such as `sync/watcher_events.py` continues to mutate portable
source lifecycle truth directly during folder-move handling. That is a real
loophole, not a wording nit.

Required revision:

- either add `BrainRepository.apply_folder_move_to_manifests()` to the
  reserved lifecycle-mutation set and the planned AST enforcement
- or state one equally exact watcher-owned carveout for this multi-source move
  primitive, including why it does not violate the plan's "one authoritative
  lifecycle surface" claim
- and add acceptance / unit-boundary coverage that closes this specific
  loophole rather than only the currently named per-source methods

---

## Significant Issues

### S1. The terminal result-state contract is now strong on state names, but still not fully exact for CLI user contract and non-success payload minimums

Revision 5 fixes the biggest finalization-surface gaps:

- per-source only, no bulk mode
- exact CLI target shape
- exact MCP argument shape
- fixed terminal state set

Relevant plan text:

- `docs/plans/plan_source-lifecycle-hardening_5_2026-03-20.md:473-550`
- `docs/plans/plan_source-lifecycle-hardening_5_2026-03-20.md:875-881`
- `docs/plans/plan_source-lifecycle-hardening_5_2026-03-20.md:936-955`

That is close. The remaining problem is that the plan only defines minimum
result payload fields for:

- `pending_confirmation`
- `finalized`

It does not yet define minimum payload/detail expectations for:

- `lease_conflict`
- `not_missing`
- `not_found`

and it still does not say what the CLI contract does with those terminal
states in exit-status terms.

That matters because the MCP surface is structured-return oriented, while the
CLI layer is process/exit oriented today:

- `src/brain_sync/interfaces/mcp/server.py:142-156`
- `src/brain_sync/interfaces/mcp/server.py:606-655`
- `src/brain_sync/interfaces/cli/handlers.py:490-531`
- `src/brain_sync/interfaces/cli/handlers.py:699-762`

Without a tighter statement, two implementations could both "share the same
terminal result states" while still diverging on whether, for example,
`not_found` or `lease_conflict` is surfaced as a success exit, a non-zero exit,
or a warning-only outcome. That is still user-facing contract guesswork.

Required revision:

- define the minimum MCP result fields for `lease_conflict`, `not_missing`,
  and `not_found`, not just their state labels
- define the CLI contract for terminal states at least at the level of:
  - whether the state label must be surfaced to the caller
  - whether each terminal state is success-like or non-zero in exit semantics
- keep that contract aligned with the acceptance and system/MCP test tiers

---

## What Works

1. The local eligibility rule for explicit finalization is now exact enough.
   The machine-local replacement for portable `missing_since_utc` no longer
   leaves the reducer up to implementer guesswork.
2. The cross-machine `missing` contract is materially deterministic now:
   portable `missing` is inherited, while local destructive eligibility must be
   rebuilt from fresh local observation history.
3. The dedicated `brain-sync finalize-missing` /
   `brain_sync_finalize_missing` surfaces are now appropriately per-source for
   the lease model, and the old doctor-owned destructive surfaces are
   explicitly removed or migration-rejected.
4. The widened reserved `BrainRepository` method set is substantially better
   than prior revisions and correctly closes the current seams in
   `application/sources.py`, `application/doctor.py`, `sync/pipeline.py`, and
   `sources/confluence/attachments.py`.
5. The zero production `sync -> application` target, the registration ordering,
   the documentation update set, and the testing matrix are all close to
   approval-grade in this revision.

---

## Required Plan Changes

Before approval, revise the plan so it:

1. Closes the remaining source-movement authority loophole by explicitly
   handling `BrainRepository.apply_folder_move_to_manifests()` in the
   reserved-method contract or by defining an equally exact closed carveout for
   it.
2. Finishes the user-facing finalization contract by defining minimum
   non-success result details and CLI exit-semantics behavior for the fixed
   terminal states.

---

## Conclusion

Revision 5 is very close, but it is not quite sealed yet. The remaining work is
no longer about lifecycle direction; it is about closing the last enforceable
authority gap in source movement and finishing the last bit of user-facing
finalization contract exactness so implementation does not have to improvise.

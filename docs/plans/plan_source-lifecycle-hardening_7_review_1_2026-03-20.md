# plan_source-lifecycle-hardening_7 Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-03-20
**Reviewed document:** `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md`
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
- `docs/plans/plan_source-lifecycle-hardening_5_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_6_review_1_2026-03-20.md`
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

**Purpose:** Review revision 7 with a challenge-first standard, with special
focus on whether the remaining lifecycle-authority surface is fully closed
against current code reality, whether the local finalization contract is now
exact enough, whether the runtime split is mandatory enough, whether the
official finalization surfaces are concrete enough, whether `sync/` avoids
becoming a new monolith, and whether the test matrix is truly approval-grade.

---

## Verdict

Changes required.

Revision 7 resolves the prior blockers around:

- exact explicit-finalization targeting
- local eligibility and cross-machine `missing` semantics
- CLI/MCP terminal result states and exit semantics
- removal of the old doctor destructive surfaces
- the `sync_polling` versus `source_lifecycle_runtime` split
- reserving `materialize_markdown()` and `apply_folder_move_to_manifests()`
- the zero production `sync -> application` target

I am still withholding approval because one movement-related authority seam is
still under-specified against current code reality, and one user-facing
administrative-listing contract is still not carried through the approval bar
and test matrix tightly enough.

This review artifact does **not** approve the plan and does **not** authorize
implementation. Create a new plan revision rather than editing
`plan_source-lifecycle-hardening_7_2026-03-20.md` in place.

---

## Critical Issues

### C1. The plan still does not close the explicit source-move authority surface tightly enough, so movement can remain a parallel lifecycle owner outside the new sync orchestrator

Revision 7 now correctly closes the two previously open lifecycle writers:

- `BrainRepository.materialize_markdown()` is reserved and must route through
  `sync/lifecycle.py`
- `BrainRepository.apply_folder_move_to_manifests()` is reserved and must route
  through `sync/lifecycle.py`

Relevant plan text:

- `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:653-658`
- `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:689-724`
- `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:989-994`

The remaining problem is the user-driven explicit move path that exists in
current code reality:

- `src/brain_sync/application/sources.py:366-415`
- `src/brain_sync/brain/repository.py:516-546`
- `src/brain_sync/interfaces/cli/handlers.py:439-457`
- `src/brain_sync/interfaces/mcp/server.py:333-354`

That path still performs source-owned file movement through:

- `BrainRepository.move_knowledge_tree()`
- `BrainRepository.move_source_attachment_dir()`

and then performs portable lifecycle updates via:

- `BrainRepository.sync_manifest_to_found_path()`
- `BrainRepository.set_source_area_path()`

Revision 7 says source **movement** is in scope and should flow through one
authoritative lifecycle surface:

- `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:16-19`
- `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:281-286`
- `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:636-639`

But the plan still leaves three gaps:

1. the transition-table minimums cover `local move observed`, but not the
   explicit `move source` command that already exists as a CLI/MCP/admin
   surface:
   - `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:758-770`
2. the reserved-method enforcement names manifest-rewrite methods, but not the
   file-move primitives that current explicit move flow relies on:
   - `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:689-704`
3. the acceptance/system/MCP criteria do not require the existing move command
   surfaces to be re-owned by the sync lifecycle layer rather than remaining a
   parallel application-owned movement path

Because of that, an implementation could still satisfy the named reservations
while leaving explicit move partially owned by `application/sources.py`, with
`sync/lifecycle.py` owning only some of the manifest transitions. That would
fall short of the plan's own "one authoritative lifecycle surface" claim for
movement.

Required revision:

- define explicit `move source` as a first-class lifecycle command, not only as
  an implied consequence of watcher-observed local moves
- add an explicit move row to the required transition table
- state exactly which module owns the registered-source move flow
- either reserve `move_knowledge_tree()` and `move_source_attachment_dir()` for
  that owner, or define an equally exact closed rule for who may call them in
  registered-source move flows
- add matching acceptance and test obligations so CLI/MCP move surfaces cannot
  remain a parallel lifecycle authority path

---

## Significant Issues

### S1. The administrative listing contract says CLI and MCP must expose lifecycle state explicitly, but the approval bar still does not require the CLI surface to do so

Revision 7 now makes the listing split conceptually correct:

- active sync projection excludes `knowledge_state = missing`
- administrative registry view includes all registered sources
- CLI and MCP listing/admin surfaces should include lifecycle state explicitly

Relevant plan text:

- `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:607-622`

The remaining problem is that the approval bar still weakens that contract:

- acceptance only requires that missing sources remain visible in
  administrative listings:
  - `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:954-956`
- MCP tests require lifecycle state in `brain_sync_list`:
  - `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:1014-1020`
- system tests require only that CLI `list` returns missing registered
  sources, not that it surfaces lifecycle state explicitly:
  - `docs/plans/plan_source-lifecycle-hardening_7_2026-03-20.md:1028-1035`

Current code reality shows why that matters:

- `SourceInfo` does not currently carry `knowledge_state`:
  - `src/brain_sync/application/sources.py:63-72`
- CLI `handle_list()` does not display lifecycle state:
  - `src/brain_sync/interfaces/cli/handlers.py:406-437`
- MCP `brain_sync_list()` serializes the same source info model:
  - `src/brain_sync/interfaces/mcp/server.py:142-156`

So the plan's narrative contract is "CLI and MCP listing/admin surfaces include
lifecycle state explicitly," but the durable approval criteria only make that
exact for MCP. The CLI side is still loose enough that implementation could
land a partially compliant administrative view and still claim to satisfy the
approved plan.

Required revision:

- promote "administrative listing surfaces expose lifecycle state explicitly"
  into the acceptance criteria, not only the narrative contract
- make the CLI listing contract exact enough to review and test
- add system-level coverage that verifies CLI list output includes lifecycle
  state for missing registered sources, not just their presence

---

## What Works

1. The local eligibility rule for explicit finalization is now exact enough for
   approval-grade implementation planning.
2. The cross-machine `missing` contract is now materially deterministic after
   removing portable `missing_since_utc`.
3. The official `brain-sync finalize-missing` /
   `brain_sync_finalize_missing` surfaces are now concrete enough on targeting,
   terminal states, MCP minimum fields, and CLI exit semantics.
4. Reserving `materialize_markdown()` and
   `apply_folder_move_to_manifests()` closes the earlier materialization and
   watcher-move loopholes cleanly.
5. The `sync_polling` versus `source_lifecycle_runtime` split is now mandatory
   enough in the runtime contract.
6. The required documentation update set is compliant with repository
   documentation-governance rules.
7. The plan still avoids turning `sync/` into a new undifferentiated monolith,
   and the testing matrix is close to fortress-level.

---

## Required Plan Changes

Before approval, revise the plan so it:

1. Closes the explicit source-move authority seam by making user-driven
   `move source` flow first-class in the lifecycle contract, ownership map,
   transition table, and enforcement/test obligations.
2. Carries the "administrative listing surfaces expose lifecycle state
   explicitly" rule into the acceptance criteria and CLI system-test bar, not
   only the MCP side.

---

## Conclusion

Revision 7 is close, but not quite sealed. The remaining work is no longer
about missing/finalization direction; it is about making sure source movement
cannot stay partially outside the new lifecycle owner, and making sure the
administrative listing contract is enforced as concretely for CLI as it is for
MCP.

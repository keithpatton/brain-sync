# plan_source-lifecycle-hardening_6 Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-03-20
**Reviewed document:** `docs/plans/plan_source-lifecycle-hardening_6_2026-03-20.md`
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

**Purpose:** Review revision 6 with a challenge-first standard, with special
focus on whether the remaining lifecycle authority surface is truly closed
against current code reality, whether the polling-versus-lifecycle runtime
split is now exact enough, and whether the plan is ready for approval under the
repository planning workflow.

---

## Verdict

Changes required.

Revision 6 is very close. It resolves the earlier blockers around explicit
finalization targeting, MCP minimum fields, CLI exit semantics, removal of the
old doctor destructive surface, `apply_folder_move_to_manifests()`, the zero
`sync -> application` target, and the required documentation set.

I am still withholding approval because one lifecycle-authority loophole
remains open in the plan's enforcement model, and one runtime-contract line is
still loose enough to weaken the plan's own polling-versus-lifecycle split.

This review artifact does **not** approve the plan and does **not** authorize
implementation. Create a new plan revision rather than editing
`plan_source-lifecycle-hardening_6_2026-03-20.md` in place.

---

## Critical Issues

### C1. The reserved `BrainRepository` mutation boundary still leaves `materialize_markdown()` as an unreserved lifecycle writer, so the authority surface is not fully closed against current code reality

Revision 6 does a strong job reserving the current direct lifecycle mutation
methods to `sync/lifecycle.py` and `sync/finalization.py`:

- `docs/plans/plan_source-lifecycle-hardening_6_2026-03-20.md:684-715`
- `docs/plans/plan_source-lifecycle-hardening_6_2026-03-20.md:953-957`

It also correctly narrows `sync/pipeline.py` to "fetch and assemble source
content" and says it should have no independent lifecycle mutation authority:

- `docs/plans/plan_source-lifecycle-hardening_6_2026-03-20.md:651-653`
- `docs/plans/plan_source-lifecycle-hardening_6_2026-03-20.md:699-702`

The remaining problem is that current code reality still has one important
portable lifecycle writer outside that reserved-method set:

- `src/brain_sync/brain/repository.py:373-428`
- `src/brain_sync/brain/manifest.py:302-321`

`BrainRepository.materialize_markdown()` does not merely write a markdown file.
It also updates the manifest's `knowledge_path`, sets
`knowledge_state = "materialized"`, clears `missing_since_utc`, and writes the
last-successful fields. That is a real lifecycle transition, not a neutral file
helper.

Today that seam is exercised directly from the pipeline path:

- `src/brain_sync/sync/pipeline.py:261-280`
- `src/brain_sync/sync/daemon.py:183-199`

Because `materialize_markdown()` is not part of the reserved-method contract,
the proposed AST call-site tests could all pass while a future implementation
still leaves direct materialization-driven lifecycle mutation in `sync/pipeline.py`
or keeps `sync/daemon.py` calling the pipeline directly. That would preserve a
meaningful lifecycle bypass even after the rest of the reservation work lands.

Required revision:

- either add `BrainRepository.materialize_markdown()` to the reserved
  lifecycle-authority boundary
- or define an equally exact complementary rule that registered-source
  materialization may only be invoked through `sync/lifecycle.py`, even if
  `sync/pipeline.py` remains the fetch/assembly worker
- and add matching architecture-test obligations so the implementation cannot
  keep `sync/pipeline.py` or `sync/daemon.py` as an alternate lifecycle writer
  while still satisfying the narrower reserved-method allowlist

---

## Significant Issues

### S1. The runtime contract still says missing sources "may" leave `sync_polling`, which is too loose for a plan that also says `sync_polling` is active-polling-only

Revision 6 is otherwise much sharper on the runtime split:

- `docs/plans/plan_source-lifecycle-hardening_6_2026-03-20.md:370-399`
- `docs/plans/plan_source-lifecycle-hardening_6_2026-03-20.md:605-620`
- `docs/plans/plan_source-lifecycle-hardening_6_2026-03-20.md:784-789`

The issue is the wording at:

- `docs/plans/plan_source-lifecycle-hardening_6_2026-03-20.md:394-399`

The plan says `sync_polling` remains active-polling-only, but then says
missing sources "may leave" `sync_polling`. That is weaker than the rest of
the revision:

- administrative views must still show missing sources
- active sync projection must exclude missing sources
- first-stage missing ordering later says to remove the source from
  `sync_polling`

Leaving the earlier runtime contract at "may leave" creates an avoidable
ambiguity about whether missing sources can retain stale polling rows as
inactive history. That would blur the exact split the plan is otherwise trying
to establish between:

- `sync_polling` as active polling state
- `source_lifecycle_runtime` as missing/finalization coordination

Current code reality already conflates those concerns enough:

- `src/brain_sync/application/source_state.py:34-53`
- `src/brain_sync/runtime/repository.py:106-114`

So this is precisely the kind of wording gap that should not survive into an
approved lifecycle-hardening plan.

Required revision:

- tighten the runtime contract so missing sources must leave `sync_polling`
  once first-stage missing is recorded
- keep `source_lifecycle_runtime` as the only runtime home for missing-source
  coordination after that point
- add a test obligation that proves the runtime split itself, not only the
  higher-level administrative listing behavior

---

## What Works

1. The local eligibility rule for explicit finalization is now exact enough.
2. The cross-machine `missing` contract is materially deterministic after
   removing portable `missing_since_utc`.
3. The `brain-sync finalize-missing` / `brain_sync_finalize_missing` contract
   is now concrete enough on target shape, terminal states, MCP minimum fields,
   and CLI exit semantics.
4. The widened reserved method set now correctly closes the previously open
   movement loophole around `apply_folder_move_to_manifests()`.
5. The documentation update set is now compliant with repository governance and
   correctly names the authoritative brain/runtime entry points and the
   user-facing README.
6. The plan still avoids turning `sync/` into a new undifferentiated monolith;
   the target module map is concrete and reviewable.
7. The testing matrix is close to fortress-level and already covers the right
   unit, integration, MCP, system, compatibility, and E2E layers.

---

## Required Plan Changes

Before approval, revise the plan so it:

1. Closes the remaining lifecycle-authority loophole around
   `BrainRepository.materialize_markdown()` by either reserving it or adding an
   equally exact enforcement rule for who may invoke registered-source
   materialization.
2. Tightens the runtime split so missing sources must leave `sync_polling`,
   with matching test obligations that keep `sync_polling` versus
   `source_lifecycle_runtime` unambiguous.

---

## Conclusion

Revision 6 is one tightening pass away from approval. The remaining work is no
longer about lifecycle direction; it is about making sure the final authority
boundary is actually closed in the same places current code mutates lifecycle
state, and keeping the runtime split as exact in the contract as it is in the
intended design.

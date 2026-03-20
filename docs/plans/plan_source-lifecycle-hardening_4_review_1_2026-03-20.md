# plan_source-lifecycle-hardening_4 Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-03-20
**Reviewed document:** `docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md`
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

**Purpose:** Review revision 4 with a challenge-first standard, with special
focus on whether the local finalization-eligibility rule is now exact without a
new undefined runtime-staleness concept, whether the cross-machine `missing`
contract is deterministic after removing portable `missing_since_utc`, whether
explicit-finalization sequencing and failure semantics now agree exactly,
whether the reserved `BrainRepository` lifecycle-mutation contract is concrete
enough for the current architecture-test harness, whether the named reservation
is scoped correctly relative to `sync/pipeline.py`, doctor diagnostics, and
`sources/confluence/attachments.py`, whether the zero `sync -> application`
target is exact, whether the documentation update set now satisfies repository
governance, whether the MCP finalization surface is tightly enough defined,
whether the plan still avoids a new `sync/` monolith, and whether the testing
matrix is fortress-level across unit, integration, MCP, system, compatibility,
and E2E.

---

## Verdict

Changes required.

Revision 4 resolves most of the blockers from revision 3. It removes the
undefined runtime-staleness idea, makes the explicit-finalization ordering and
failure model agree, sharpens the zero `sync -> application` target, expands
the required documentation set to include the authoritative brain/runtime
entry points and the user-facing README, and materially strengthens the test
fortress.

I am still withholding approval because two contract edges and one sequencing
edge remain loose enough that implementation would still have to invent
behavior:

- the new official finalization surface is named, but not yet defined tightly
  enough as a user-facing CLI/MCP contract
- the reserved `BrainRepository` lifecycle-mutation-method allowlist is still
  too narrow to enforce the plan's own "one authoritative lifecycle surface"
  goal against current code reality
- the registration ordering rules still blur which runtime table is written for
  ordinary source registration, even though the plan otherwise distinguishes
  `sync_polling` from `source_lifecycle_runtime`

This review artifact does **not** approve the plan and does **not** authorize
implementation. Create a new plan revision rather than editing
`plan_source-lifecycle-hardening_4_2026-03-20.md` in place.

---

## Critical Issues

### C1. The official `finalize-missing` / `brain_sync_finalize_missing` surface is still under-specified as a product contract

Revision 4 now does the important part of naming the dedicated destructive
surfaces and removing the old doctor-owned destructive modes:

- `docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md:456-496`
- `docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md:861-875`

That is materially better than revision 3. But the plan still never freezes the
most important user-facing behavior of the replacement surface:

- whether `brain-sync finalize-missing` targets one source or all missing
  sources
- whether `brain_sync_finalize_missing` takes a `canonical_id`, a source URL, a
  path filter, or a bulk flag
- whether bulk finalization is allowed at all under a per-`canonical_id` lease
  model
- what result shape a non-finalizing preflight returns when local confirmation
  is still being accumulated
- whether CLI and MCP expose the same targeting semantics and failure reasons

That ambiguity matters because current code reality exposes a global
"finalize all missing sources" behavior through doctor-owned surfaces:

- `src/brain_sync/application/doctor.py:671-697`
- `src/brain_sync/interfaces/cli/handlers.py:699-717`
- `src/brain_sync/interfaces/mcp/server.py:606-624`

Revision 4 correctly says those doctor surfaces go away, but it still leaves the
replacement action's scope and invocation model open. That is especially risky
now that the plan also adopts source-level leases and local per-source
eligibility in `source_lifecycle_runtime`
(`docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md:399-454`,
`691-726`). A per-source serialization model and a not-yet-defined bulk
finalization surface are not the kind of gap we should leave for the
implementer to settle.

Required revision:

- define the exact CLI contract for `brain-sync finalize-missing`
- define the exact MCP contract for `brain_sync_finalize_missing`
- state explicitly whether the surface is per-source, batch, or both
- if batch behavior exists, define how it composes with source-level leases,
  partial eligibility, and mixed results
- add acceptance and test obligations for the exact CLI/MCP argument and result
  contract, not just the existence of the named surfaces

### C2. The reserved `BrainRepository` lifecycle-mutation allowlist is still too narrow to enforce the plan's own authority boundary

Revision 4 is much stronger on architecture enforcement than earlier drafts. It
now names:

- zero production `sync -> application` imports
- `sync/lifecycle.py` and `sync/finalization.py` as the reserved lifecycle
  orchestrators
- an AST call-site enforcement strategy for reserved `BrainRepository` methods

Relevant plan text:

- `docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md:515-601`
- `docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md:603-625`
- `docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md:819-845`

The remaining problem is scope. The reserved-method list only covers:

- `mark_source_missing`
- `clear_source_missing`
- `mark_source_stale`
- `set_source_area_path`
- `sync_manifest_to_found_path`
- `delete_source_registration`

That still leaves several current source-lifecycle mutation seams outside the
enforceable allowlist:

- registration writes via `BrainRepository.save_source_manifest()` in
  `src/brain_sync/application/sources.py:215-227`
- source-setting updates via `BrainRepository.update_source_sync_settings()` in
  `src/brain_sync/application/sources.py:477-487`
- destructive source-owned file cleanup via
  `BrainRepository.remove_source_owned_files()` and
  `BrainRepository.remove_source_managed_artifacts()` in
  `src/brain_sync/application/sources.py:163-180`
- direct manifest rewrite via `BrainRepository.save_source_manifest()` in
  `src/brain_sync/application/doctor.py:615-620`

Those repository methods are real production mutation seams today:

- `src/brain_sync/brain/repository.py:193-255`
- `src/brain_sync/brain/repository.py:808-839`

So with the current revision, an implementation could move only the named
missing/move/finalize mutations into `sync/lifecycle.py` / `sync/finalization.py`
while leaving registration, update, direct manifest rewrites, or destructive
cleanup helpers distributed across `application/`, and the proposed
architecture tests would still pass.

That is not tight enough for the plan's own stated objective that source
creation, update, movement, missing handling, rediscovery, explicit
finalization, and admin flow through one authoritative lifecycle surface
(`docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md:16-29`,
`267-285`).

The plan does a good job scoping the named reservation relative to
`sync/pipeline.py`, doctor diagnostics, and
`sources/confluence/attachments.py`, but that exactness only closes the
surface for the six named methods. It does not yet close the broader lifecycle
authority surface that current code actually uses.

Required revision:

- either expand the reserved `BrainRepository` lifecycle-mutation method set to
  cover all source-lifecycle mutation helpers that matter for registration,
  update, explicit remove, and finalization
- or define an equally exact complementary rule that constrains
  `save_source_manifest()`, `update_source_sync_settings()`,
  `remove_source_owned_files()`, and `remove_source_managed_artifacts()` to the
  approved orchestrator path
- state explicitly whether doctor may retain any direct source-manifest rewrite
  path outside official lifecycle APIs, and if so, why that is not considered a
  source-lifecycle mutation

---

## Significant Issues

### S1. The registration ordering rule still blurs `sync_polling` versus `source_lifecycle_runtime`

Revision 4 is appropriately sharp earlier in the runtime section:

- `source_lifecycle_runtime` exists only for missing/finalization/lease
  coordination
- rows are not required for every registered source
- `sync_polling` remains the active-polling-only table

Relevant plan text:

- `docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md:366-397`

But the registration ordering section then says:

- `docs/plans/plan_source-lifecycle-hardening_4_2026-03-20.md:660-664`

specifically:

1. write the portable manifest first
2. create runtime coordination rows second
3. only then expose the source to active polling

That wording is too loose now that the plan has intentionally split runtime
surfaces. For an ordinary new source in `awaiting`, step 2 could be read as:

- create a `sync_polling` row
- create a `source_lifecycle_runtime` row
- create both

Only the first reading appears consistent with the row-scope rules above, but
the plan does not say that directly. This is exactly the kind of small
ambiguity that later produces unnecessary schema spread or inconsistent test
expectations.

Required revision:

- name the exact runtime table(s) touched during ordinary registration
- keep registration ordering consistent with the earlier rule that
  `source_lifecycle_runtime` rows are not required for every registered source

---

## What Works

1. The local explicit-finalization eligibility rule is now much sharper and no
   longer introduces a new undefined runtime-staleness concept.
2. The cross-machine `missing` contract is materially better: portable
   `missing` remains inherited, while finalization eligibility is rebuilt
   locally from fresh observation paths.
3. The explicit-finalization ordering and failure model now agree: manifest
   deletion is last, and anything after that point is clearly marked
   non-authoritative.
4. The zero production `sync -> application` target is now exact enough for the
   boundary-test harness to encode.
5. The documentation update set is now substantially more compliant with
   repository governance because it explicitly covers `docs/brain/README.md`,
   `docs/runtime/README.md`, and the user-facing `README.md`.
6. The plan's anti-monolith work on `sync/` is much stronger than prior
   revisions; the target module map is now concrete and reviewable.
7. The test fortress is now close to approval-grade and spans the right
   behavioral layers; the remaining weakness is mostly downstream of the still
   under-specified finalization and mutation-authority contracts above.

---

## Required Plan Changes

Before approval, revise the plan so it:

1. Defines the exact user-facing CLI and MCP contract for the new
   finalization surface, including target granularity and result semantics.
2. Tightens the `BrainRepository` lifecycle-mutation authority rule so the
   architecture tests can actually enforce the plan's full lifecycle-ownership
   claim rather than only six named methods.
3. Makes the registration ordering rules name the exact runtime table(s)
   written for ordinary source registration.

---

## Conclusion

Revision 4 is very close. The remaining blockers are not about overall
direction anymore; they are about the last few places where the plan still
names a mechanism without freezing the exact contract around it. Tightening the
finalization surface and the enforceable mutation boundary should be enough to
get this ready for approval.

# plan_source-lifecycle-hardening_2 Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-03-20
**Reviewed document:** `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md`
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
- `docs/plans/plan_source-lifecycle-hardening_review_1_2026-03-20.md`
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

**Purpose:** Review revision 2 with a challenge-first standard, with special
focus on versioning and migration explicitness, cross-machine `missing`
determinism after removing portable `missing_since_utc`, runtime lifecycle
coordination sharpness, explicit-only destructive finalization, administrative
listing semantics, anti-monolith package boundaries, restart safety,
idempotency, preservation of the sharp `stale` rule, and the strength of the
test fortress.

---

## Verdict

Changes required.

Revision 2 fixes the largest gaps from the root plan. The Brain Format `1.2` /
runtime `v27` / app `0.7.0` row is now explicit, the required spec updates are
much more concrete, the `stale` rule is carried forward sharply, and the test
fortress is materially stronger.

I am still withholding approval because two contract edges and one enforcement
edge remain under-specified enough that implementers would still have to invent
policy:

- what exactly makes a source "locally eligible" for explicit finalization
  after `missing_since_utc` leaves the portable plane
- whether current destructive doctor entrypoints are removed or remain as a
  second named destructive surface beside `finalize-missing`
- what exact boundary-test shape proves the current `sync -> application`
  pinhole is actually closed rather than merely moved or renamed

This review artifact does **not** approve the plan and does **not** authorize
implementation. Create a new plan revision rather than editing
`plan_source-lifecycle-hardening_2_2026-03-20.md` in place.

---

## Critical Issues

### C1. Local finalization eligibility is still undefined, so the cross-machine `missing` contract is not yet deterministic enough after removing portable `missing_since_utc`

The revision now correctly moves versioning and migration to an explicit
`0.7.0 / Brain Format 1.2 / runtime v27` row and introduces a dedicated
`source_lifecycle_runtime` table. But the plan still does not define the rule
that turns local runtime observations into "locally eligible for explicit
finalization."

Relevant plan text:

- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:289-292`
- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:345-356`
- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:367-385`
- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:406-409`
- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:587-594`
- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:748-763`

The runtime table fields are named (`local_missing_first_observed_utc`,
`local_missing_last_confirmed_utc`, `missing_confirmation_count`, lease
fields), but the plan never states the reducer rule that interprets them.
Right now an implementer still has to guess all of the following:

- whether one local observation is enough or whether two passes are required
- whether eligibility is count-based, elapsed-time-based, or both
- whether explicit-finalization preflight may create the first local runtime
  row and still finalize in the same command, or must stop after recording that
  first observation
- whether startup reconcile and explicit reconcile write identical local
  confirmation state or have different authority
- whether registration creates `source_lifecycle_runtime` rows for every source
  or only once a source enters missing/finalization coordination

That ambiguity matters because current repo behavior is still a strict
two-stage missing model:

- `docs/RULES.md:563-580`
- `src/brain_sync/application/sources.py:559-655`
- `src/brain_sync/sync/daemon.py:101-105`
- `src/brain_sync/sync/daemon.py:160-164`

Revision 2 says different runtimes may disagree on when a source becomes
locally eligible, which is fine as a product decision, but it still needs one
exact local eligibility rule so implementation, docs, and tests are not forced
to discover that rule later.

Required revision:

- define the exact eligibility reducer for `source_lifecycle_runtime`
- state whether explicit finalization may ever both create first local missing
  coordination and finalize in the same invocation
- state whether the old "second pass" meaning survives as a local confirmation
  rule, or is intentionally replaced by a different rule
- make the row-lifecycle scope explicit: all registered sources versus only
  missing/finalization-coordinated sources
- add acceptance and test obligations that prove the eligibility rule, not just
  the existence of the table

---

## Significant Issues

### S1. The plan still does not say one exact thing about the existing destructive doctor entrypoints, so explicit-only finalization is not fully closed over current code reality

The revision now names the intended destructive entrypoints:

- CLI: `brain-sync finalize-missing`
- MCP: `brain_sync_finalize_missing`

and correctly removes destructive authority from startup reconcile and explicit
`reconcile` in the plan text:

- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:391-401`

But the plan still stops short of saying what happens to the currently shipped
doctor destructive paths:

- `src/brain_sync/application/doctor.py:671-697`
- `src/brain_sync/interfaces/cli/handlers.py:699-717`
- `src/brain_sync/interfaces/mcp/server.py:606-624`

That matters because the current CLI and MCP surfaces both expose a named
doctor-mode destructive action today (`deregister_missing`). Revision 2 says
doctor is non-destructive by default and must not bypass lifecycle APIs, but
those statements do not yet force one exact product outcome for the existing
destructive doctor surface.

Without a tighter statement, the implementation could preserve:

- `brain-sync doctor --deregister-missing`
- `brain_sync_doctor(mode="deregister_missing")`

and still claim compliance by routing them through lifecycle APIs. That would
leave destructive finalization with multiple named user-facing entrypoints,
undercutting the revision's "dedicated explicit lifecycle entrypoints" rule.

Required revision:

- state whether doctor destructive modes are removed entirely, rejected with a
  migration hint, or retained only as thin aliases of the dedicated
  `finalize-missing` entrypoints
- if aliases remain, state whether they are temporary compatibility shims and
  where that compatibility decision is documented
- add system and MCP acceptance criteria proving the old doctor destructive
  entrypoints do not survive as an independent product surface

### S2. The proposed boundary-test updates are not yet exact enough to prove the current `sync -> application` pinhole is intentionally closed

The target module map is much improved, and the plan correctly calls out the
need to update:

- `docs/architecture/ARCHITECTURE.md`
- `docs/RULES.md`
- `tests/unit/test_architecture_boundaries.py`

Relevant plan text:

- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:481-498`
- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:702-705`
- `docs/plans/plan_source-lifecycle-hardening_2_2026-03-20.md:717-718`

Current enforcement is exact-file based:

- `tests/unit/test_architecture_boundaries.py:119-129`
- `tests/unit/test_architecture_boundaries.py:473-491`

That is good, but the new plan wording is still broad enough that an
implementer could satisfy it by introducing a new documented exception list
elsewhere in `sync/` rather than truly closing the seam. The same problem
exists for "no direct source-manifest lifecycle mutation outside
`brain.repository` and the approved lifecycle orchestrator path": the plan does
not yet say what exact static or testable rule will enforce that authority
boundary.

Importantly, an import-only off-graph test cannot by itself prove the
write-authority rule. Current code reality still has many lifecycle-sensitive
surfaces spread across `application/` and `sync/`:

- `src/brain_sync/sync/daemon.py:12-19`
- `src/brain_sync/application/sources.py:509-525`
- `src/brain_sync/application/sources.py:559-655`
- `src/brain_sync/application/source_state.py:34-53`

Required revision:

- state the exact post-change expectation for `sync -> application` imports:
  either zero such off-graph imports, or an enumerated residual exception set
- state the exact module path that is the approved lifecycle orchestrator
  authority, so tests can name it concretely
- specify how the "no direct source-manifest lifecycle mutation" rule will be
  enforced beyond generic import checks

---

## What Works

1. The versioning and migration story is now explicit and consistent with the
   repository rules: Brain Format `1.2`, runtime `v27`, app `0.7.0`, guided
   portable migration, and in-place runtime migration.
2. The required spec updates are now concrete enough to keep `docs/brain/`,
   `docs/runtime/`, `docs/RULES.md`, `docs/GLOSSARY.md`,
   `docs/VERSIONING.md`, `docs/COMPATIBILITY.md`, and
   `docs/architecture/ARCHITECTURE.md` from drifting apart.
3. The administrative listing split between active polling projection and
   administrative registry view is a sound product decision and aligns with the
   current code gap in `application/source_state.py` and `application/sources.py`.
4. The `stale` rule remains sharp enough in this revision; it is explicitly
   preserved in both the acceptance criteria and the compatibility test tier.
5. The test fortress is materially stronger than the previous revision and now
   covers unit, integration, MCP, system, compatibility, and E2E tiers.

---

## Required Plan Changes

Before approval, revise the plan so it:

1. Defines the exact local eligibility rule for explicit finalization after
   portable `missing_since_utc` removal, including row-lifecycle scope for
   `source_lifecycle_runtime`.
2. States one exact product outcome for current destructive doctor entrypoints:
   remove them, reject them, or retain them only as compatibility aliases of
   the dedicated finalization entrypoints.
3. Tightens the boundary-test section so it names the exact post-change
   `sync -> application` expectation and the exact enforceable rule for
   lifecycle write authority.

---

## Conclusion

Revision 2 is much closer. The remaining blockers are no longer about overall
direction; they are about the final few contract definitions that keep
cross-machine finalization, user-facing destructive surfaces, and architecture
enforcement from becoming implementation-time guesswork.

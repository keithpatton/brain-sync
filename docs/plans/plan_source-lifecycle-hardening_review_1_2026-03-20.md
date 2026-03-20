# plan_source-lifecycle-hardening Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-03-20
**Reviewed document:** `docs/plans/PLAN_source-lifecycle-hardening.md`
**Reviewed against:**
- `docs/plans/README.md`
- `AGENTS.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
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
  - `src/brain_sync/brain/manifest.py`
  - `src/brain_sync/brain/repository.py`
  - `src/brain_sync/runtime/repository.py`
  - `src/brain_sync/sources/base.py`
  - `src/brain_sync/sources/confluence/attachments.py`
  - `tests/unit/test_architecture_boundaries.py`

**Purpose:** Review the source-lifecycle-hardening root plan with a
challenge-first standard, with special focus on lifecycle-contract sharpness
before package movement, removal of portable `missing_since_utc`, explicit-only
destructive finalization, compact `stale` semantics, doctor authority,
anti-monolith package ownership, concurrency/failure concreteness, and the
strength of the proposed test fortress.

---

## Verdict

Changes required.

The plan has the right direction and correctly identifies the source lifecycle
surface as the next major hardening seam. It is not ready for approval yet,
because several contract decisions that already affect versioning, cross-machine
authority, destructive cleanup, and package-boundary enforcement are still too
open in the root artifact.

This review artifact does **not** approve the plan and does **not** authorize
implementation. The planner should create a revised plan artifact rather than
editing `PLAN_source-lifecycle-hardening.md` in place.

---

## Critical Issues

### C1. Removing portable `missing_since_utc` is proposed without an explicit Brain Format / runtime-schema / migration decision, which conflicts with the current approved compatibility row

`docs/plans/PLAN_source-lifecycle-hardening.md:73-79` makes removal of portable
`missing_since_utc` a confirmed product decision. But the current authoritative
docs still define Brain Format `1.1` as containing that field:

- `docs/brain/SCHEMAS.md:37-47`
- `docs/GLOSSARY.md:808-811`
- `docs/RULES.md:730-731`
- `docs/VERSIONING.md:28-35`
- `docs/COMPATIBILITY.md:13-27`

Under `docs/VERSIONING.md:50-57`, changing a manifest field or changing what is
portable versus runtime state is a Brain Format decision, not an implementation
detail. Likewise, adding runtime coordination for missing/finalization would be
a runtime DB schema decision. The plan currently says only that docs should be
updated as needed (`docs/plans/PLAN_source-lifecycle-hardening.md:167-170`) and
that the revision should inspect whether new runtime fields or tables are needed
(`docs/plans/PLAN_source-lifecycle-hardening.md:268-270`). That is too loose for
an already-approved `0.6.0 / Brain Format 1.1 / runtime v26` row.

Required revision:
- make one explicit versioning decision for this work:
  - whether removing `missing_since_utc` creates Brain Format `1.2`
  - whether runtime coordination changes create runtime schema `v27`
  - what app-version compatibility row is being targeted
- state the migration mode for both planes rather than leaving it implicit
- update the root plan acceptance criteria so versioning and compatibility work
  is mandatory when the portable field is removed

### C2. The plan does not yet specify how `knowledge_state = missing` remains durable and cross-machine-correct once missing timing moves to runtime

The plan intentionally keeps portable `knowledge_state = missing`
(`docs/plans/PLAN_source-lifecycle-hardening.md:81-87`) while moving missing
timing and grace-window coordination to runtime
(`docs/plans/PLAN_source-lifecycle-hardening.md:262-270`,
`docs/plans/PLAN_source-lifecycle-hardening.md:348-350`). That direction is
reasonable, but the contract is not yet sharp enough for the current repo
guarantees.

Today the compatibility row requires cross-machine continuation from portable
manifest truth (`docs/COMPATIBILITY.md:35-41`, `docs/COMPATIBILITY.md:67-75`),
and the current implementation immediately deletes runtime polling rows when a
source is marked missing (`src/brain_sync/application/sources.py:509-525`).
Missing sources also disappear from the normal runtime source projection
(`src/brain_sync/application/source_state.py:40-53`). Finalizing reconcile then
acts from the manifest-driven missing state
(`src/brain_sync/application/sources.py:596-624`,
`src/brain_sync/sync/daemon.py:101-105`).

Once the missing timer leaves the manifest, the root plan must say more than
"inspect whether current runtime schema needs a new table or fields." It still
needs one explicit authority model for:

- where first-observed missing time lives when the source no longer has a
  `sync_polling` row
- whether finalization eligibility is per-runtime only or must survive to a
  second machine
- how another machine interprets a portable `missing` source when it has no
  local missing-observation history
- whether explicit finalization is allowed without a locally observed grace
  window or requires a fresh local re-observation step first

Required revision:
- define the exact runtime record keyed for missing/finalization coordination
- define the cross-machine rule for a source already in portable `missing`
- state whether explicit finalization is driven by portable state plus fresh
  local revalidation, or by some runtime-carried eligibility record, and why
- add acceptance/test obligations that prove the missing lifecycle remains
  deterministic after the portable timestamp is removed

---

## Significant Issues

### S1. Explicit-only destructive finalization is not yet tied to concrete entrypoints, so current finalizing reconcile behavior is left unresolved

The plan confirms that destructive finalization should start explicit-only
(`docs/plans/PLAN_source-lifecycle-hardening.md:89-104`) and later requires
revalidation-safe finalization (`docs/plans/PLAN_source-lifecycle-hardening.md:286-295`).
But it does not yet say which workflows remain authorized to perform that
explicit finalization, or what happens to current finalizing reconcile paths.

Current rules and code make this concrete today:

- `docs/RULES.md:576-580` reserves second-stage cleanup for startup reconcile,
  explicit reconcile commands, or explicit doctor cleanup
- `src/brain_sync/sync/daemon.py:101-105` runs finalizing reconcile at startup
- `src/brain_sync/application/sources.py:559-624` finalizes missing sources by
  default when `reconcile_sources()` runs with `finalize_missing=True`
- `src/brain_sync/application/doctor.py:671-697` exposes an explicit doctor
  destructive path today

If finalization becomes explicit-only, the plan needs to say one exact thing
about each of those surfaces: keep, remove, or narrow. Otherwise the revision
will still be forced to invent product behavior for:

- startup daemon reconcile
- explicit `reconcile` commands
- doctor cleanup commands
- any future CLI/MCP "finalize missing source" action

Required revision:
- name the official explicit finalization entrypoints
- state whether startup reconcile loses destructive authority entirely
- state whether `reconcile` remains a finalizer or becomes non-destructive
- define doctor's allowed destructive surface after the change, not just
  "non-destructive by default"

### S2. The proposed `sync` ownership move is still too broad to prevent a new monolith or to preserve the current architectural seams intentionally

The plan correctly wants to remove the current `sync -> application` upward
pinhole (`docs/plans/PLAN_source-lifecycle-hardening.md:160-163`,
`docs/plans/PLAN_source-lifecycle-hardening.md:339-342`). But the target shape
for the new `sync` ownership model remains too conceptual
(`docs/plans/PLAN_source-lifecycle-hardening.md:207-225`).

That is risky because the repo has concrete architecture and test constraints
today:

- `docs/architecture/ARCHITECTURE.md:162-170` explicitly assigns watcher policy
  and child-discovery policy to `application/`
- `tests/unit/test_architecture_boundaries.py:82-93` keeps `sync` off-graph
  dependencies narrow
- `tests/unit/test_architecture_boundaries.py:119-129` documents the current
  `sync/daemon.py` exception surface exactly

If the next revision is going to move lifecycle policy into `sync/`, it should
also define what stays in `application/` so "thin transport-neutral use-case
facades" remains enforceable instead of aspirational. Right now the root plan
does not say where these responsibilities land after the move:

- child discovery request orchestration
- watcher-to-regen invalidation glue
- transport-neutral source admin facades
- operational-event logging boundaries
- query-index invalidation side effects

Required revision:
- provide a concrete target module map, not just a conceptual list
- name what remains in `application/` after lifecycle movement
- state which new or changed boundary tests will close the seam and prevent
  `sync` from becoming a new general-purpose orchestration package

### S3. `stale` semantics and the proposed test matrix are not yet sharp enough to preserve the existing no-fast-path guarantee

The plan intentionally keeps portable `stale` compact
(`docs/plans/PLAN_source-lifecycle-hardening.md:106-112`) and says stale
sources are not trustable until successful full rematerialization
(`docs/plans/PLAN_source-lifecycle-hardening.md:238-245`). That is directionally
correct, but the root artifact does not yet carry forward the current concrete
compatibility rule that matters most in code: `stale` must force full
rematerialization even when the stored remote fingerprint still matches.

That rule is explicit in:

- `docs/COMPATIBILITY.md:71-75`
- `docs/plans/plan_source-state-boundary_2_approved_2026-03-19T19-05-47.md`
  under the cross-machine proof obligations

It also matters directly to the current pipeline fast path:

- `src/brain_sync/sync/pipeline.py:130-152` only short-circuits when
  `knowledge_state == "materialized"`

The root plan's acceptance criteria and test matrix do not preserve that rule
explicitly. The matrix is also not yet fortress-level enough for the stated
scope because it omits:

- compatibility-focused coverage for the portable/runtime contract change
- an explicit `mcp` tier, even though the scope names MCP drivers
- architecture-boundary tests needed to close the package move intentionally

Required revision:
- state explicitly that `stale` still forbids unchanged-source fast paths until
  a successful full rematerialization
- add compatibility-test obligations for the missing/stale/finalization
  contract, not only broad integration/e2e expectations
- include boundary-test and `mcp`-tier expectations in the test fortress so
  the new lifecycle seam is protected at the same layer where the repo enforces
  other architecture contracts

---

## What Works

1. The plan correctly identifies lifecycle hardening as a contract problem
   before it is a package-movement problem.
2. The explicit separation of commands, observations, policy, and orchestration
   is a good foundation for the next revision.
3. The bias toward explicit-only destructive finalization is prudent for a
   layer that still has competing writers and cross-machine concerns.
4. The plan correctly resists adding a portable stale-cause taxonomy unless the
   product can prove a durable need.

---

## Required Plan Changes

Before approval, revise the plan so it:

1. Makes the versioning and migration consequences of removing portable
   `missing_since_utc` explicit.
2. Defines the exact runtime and cross-machine contract for portable
   `knowledge_state = missing` after timing moves out of the manifest.
3. Names the official explicit destructive-finalization entrypoints and states
   how startup reconcile, explicit reconcile, and doctor cleanup change.
4. Tightens the `sync` ownership target with a concrete module map and
   matching boundary-test expectations.
5. Carries forward the sharp `stale` rule and strengthens the test fortress
   with compatibility, `mcp`, and architecture-boundary coverage.

---

## Conclusion

The root plan is close in direction but not yet sharp enough on the exact
contract edges the user called out. The next revision should freeze those
decisions before the package move begins, so the implementation is following a
clear lifecycle model rather than discovering one while rearranging modules.

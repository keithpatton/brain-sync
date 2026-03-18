# Review

Reviewed artifact: `docs/plans/plan_runtime-release-alignment_5_2026-03-18.md`
Reviewed on: `2026-03-18`
Reviewer: `codex-gpt-5`

## Findings

### 1. Phase 0 does not yet inventory every disputed helper and consuming workflow for `operational_events`

`docs/plans/plan_runtime-release-alignment_5_2026-03-18.md:95-100` undercounts
the `operational_events` surface in the helper inventory, and
`docs/plans/plan_runtime-release-alignment_5_2026-03-18.md:108-109` does the
same in the consuming-workflow inventory. In code,
`src/brain_sync/runtime/repository.py:1513-1523`
(`runtime.repository.invalidate_area_index()`) both dirties paths / advances
tokens **and** writes `query.index.invalidated` to `operational_events`.
Likewise `src/brain_sync/application/query_index.py:21-32`
(`application.query_index.load_area_index()`) both reads the invalidation token
**and** writes `query.index.rebuilt` to `operational_events`. That means the
MCP cached-index refresh flow and the browse / placement / query refresh flow
consume `operational_events` as well as `invalidation_tokens`, but the plan
currently inventories only the token side.

Required fix:
- update the Phase 0 helper inventory so `runtime.repository.invalidate_area_index()`,
  `application.query_index.invalidate_area_index()`, and
  `application.query_index.load_area_index()` record their
  `operational_events` side effects explicitly
- update the Phase 0 consuming-workflow inventory so every `load_area_index()`
  caller is shown as using `operational_events` as well as
  `invalidation_tokens`
- recheck the retained `operational_events` workflow inventory for any other
  similarly collapsed or under-described consumers before resubmission

### 2. Phase 3 still leaves the `operational_events` keep decision partially deferred

`docs/plans/plan_runtime-release-alignment_5_2026-03-18.md:217` says
`operational_events` is `keep now`, but
`docs/plans/plan_runtime-release-alignment_5_2026-03-18.md:293-294` says that
retention remains provisional until Phase 5 confirms that no production
correctness path reads it as authority. That is still a deferred disposition on
the only disputed surface being kept. The user asked for an exact,
non-deferred keep/revert/defer outcome per candidate; this wording keeps the
door open for a later reclassification after implementation has already been
authorized.

Required fix:
- make the Phase 3 disposition final for `operational_events`
- either change the decision to `defer` / `revert now`, or keep it and state
  that the no-authority proof is already part of the approval bar for this
  revision, with later phases limited to validation of the approved decision
  rather than reopening it
- remove wording that leaves the retained-surface verdict provisional after
  approval

### 3. The AreaIndex replacement path is still left to implementation-time guesswork

`docs/plans/plan_runtime-release-alignment_5_2026-03-18.md:243-248` says
`AreaIndex` freshness must return to "a portable-state or in-process
correctness path." That is not one concrete design. Those are materially
different options with different behavior for long-lived MCP/browser/placement
caches, especially under the baseline that the same portable brain may change
elsewhere while this machine is idle. As written, the implementer still has to
choose the replacement authority mechanism during Phase 4.

Required fix:
- specify the exact post-narrowing freshness authority for `AreaIndex`
- state whether cached-index reuse must consult portable state on load, whether
  in-process invalidation is only an optimization layered on top of that
  portable check, and how external portable changes are detected for long-lived
  processes
- make the chosen replacement path specific enough that two different
  implementers would not produce materially different correctness behavior

## Open Questions / Assumptions

- I assumed Phase 0 inventory completeness means naming all disputed-surface
  side effects in helpers and workflows, not only their primary table reads.
- I assumed the requested Phase 3 concreteness bars any wording that would let
  a retained disputed surface be reopened as an architecture decision during
  implementation.

## Verdict

Changes required.

Create a new plan revision that closes the incomplete `operational_events`
inventory, makes the retained-surface decision final, and specifies one exact
`AreaIndex` freshness authority path. This review artifact does not approve the
plan and does not authorize implementation.

# Review

Reviewed artifact: `docs/plans/PLAN_runtime-release-alignment.md`
Reviewed on: `2026-03-18`
Reviewer: `codex-gpt-5`

## Findings

### 1. The plan still delegates the decisive keep/revert call to implementation

`docs/plans/PLAN_runtime-release-alignment.md:341-401` makes Phase 3 the point
where the disputed `v25` runtime surfaces are actually split into `keep now`,
`revert now`, and `defer`, then immediately proceeds to Phase 4 implementation.
That is too much discretion to hand to an implementer under one approval pass.
The contentious release decision is precisely whether `dirty_knowledge_paths`,
`path_observations`, `invalidation_tokens`, and `operational_events` stay in
scope. This plan needs a hard re-review gate after Phases 0-3 produce the
actual narrowed disposition. Require a new plan revision or equivalent
decision artifact that records the concrete keep/revert/defer outcome before
Phase 4 implementation may begin.

### 2. The authority model is vulnerable to circular justification from the same commit under review

`docs/plans/PLAN_runtime-release-alignment.md:41-52` and
`docs/plans/PLAN_runtime-release-alignment.md:71-85` treat current
`docs/runtime/SCHEMAS.md` and `docs/architecture/ARCHITECTURE.md` as primary
constraints. But commit `6d7eb76` also expanded those documents to describe the
new tables as current runtime state. Then
`docs/plans/PLAN_runtime-release-alignment.md:106-115` cites those
classifications as directional support. That is too circular for an adversarial
release-alignment review. The plan must explicitly separate:

- stable higher-order invariants that predate or survive this dispute
- table-specific justifications introduced by `6d7eb76`, which should be
  treated as claims to re-prove, not as evidence for retention

Without that distinction, the review can accidentally bless the expansion
because the expansion already edited the docs.

### 3. The rollback and compatibility posture for unreleased `0.6.0` is not concrete enough

`docs/plans/PLAN_runtime-release-alignment.md:222-230` forbids another runtime
schema bump, and `docs/plans/PLAN_runtime-release-alignment.md:359-364`
requires schema consequences to be documented for reverted surfaces. That still
leaves the critical execution question unresolved: if release narrowing removes
or disables these `v25` surfaces, what is the exact policy for already-created
runtime DBs on developer or tester machines? The plan does not say whether the
expected path is:

- keep schema `25` but leave reverted tables inert
- drop tables in place
- require rebuild/reset for unreleased local DBs
- or something else

Because `docs/VERSIONING.md` and `docs/runtime/SCHEMAS.md` currently frame
in-place migration as the default for supported upgrades, this omission is
material. The plan needs an explicit pre-release rollback policy and release
acceptance criteria for narrowed `v25` state.

### 4. The proof burden for retaining runtime caches is still too aggregate

`docs/plans/PLAN_runtime-release-alignment.md:321-339`,
`docs/plans/PLAN_runtime-release-alignment.md:409-420`, and
`docs/plans/PLAN_runtime-release-alignment.md:468-481` ask for stale-state
analysis and generic advisory-cache tests. That is directionally correct but
still too weak for the specific risk here. The disputed tables participate in
different consuming workflows with different failure modes:

- startup reconcile candidate narrowing
- rename or move propagation
- query-index invalidation and reload
- watcher-driven enqueue behavior

The plan should require per-retained-table, per-consuming-workflow negative
evidence showing that stale rows, missing rows, and divergent rows on another
machine cannot suppress work that portable state requires. A single generic
"cache yields to filesystem truth" test is not enough to retain
`dirty_knowledge_paths`, `path_observations`, or `invalidation_tokens`.

## Open Questions / Assumptions

- Is the intent that Phase 0-3 outputs produce a new narrowed plan revision
  before any implementation work, or was the planner expecting this root plan
  to authorize the whole decision-and-implementation sequence?
- For unreleased `0.6.0`, may developer and tester runtime DBs be explicitly
  rebuilt as part of rollback, or must the narrowed branch continue to support
  in-place evolution from the current `v25` local state?
- Should the table-specific schema and architecture text added in `6d7eb76` be
  treated as provisional until this review closes, or does the planner intend
  to keep those docs in force while narrowing only code?

## Verdict

Changes required.

The candidate keep/revert buckets are directionally conservative, and the
multi-machine/home-work concern is present in the plan, but the plan is still
not approval-ready. Tighten the decision gates, explicitly de-circularize the
authority inputs, and define the exact pre-release rollback posture for `v25`
before asking for approval.

This review artifact does not approve the plan and does not authorize
implementation.

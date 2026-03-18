# Review

Reviewed artifact: `docs/plans/plan_runtime-release-alignment_2_2026-03-18.md`
Reviewed on: `2026-03-18`
Reviewer: `codex-gpt-5`

## Findings

### 1. The post-Phase-3 gate still allows a non-workflow artifact to carry the narrowing decision

`docs/plans/plan_runtime-release-alignment_2_2026-03-18.md:383-392` says
Phases 0-3 may produce "a new narrowed plan revision, or equivalent planner
artifact". That weakens the very gate this revision is trying to harden.
`docs/plans/README.md` defines the authoritative lifecycle artifacts and warns
against inventing extra workflow steps. "Equivalent planner artifact" leaves
room for an ad hoc note or supporting input to stand in for the narrowed
decision record. The plan should require a new plan revision using the repo
naming rules before the next review/approval pass, not an unspecified
equivalent.

### 2. The stable-vs-provisional split still leaves the current `v25` compatibility story looking authoritative

`docs/plans/plan_runtime-release-alignment_2_2026-03-18.md:52-69` treats
`docs/VERSIONING.md` and `docs/COMPATIBILITY.md` as stable authority inputs,
while `docs/plans/plan_runtime-release-alignment_2_2026-03-18.md:222-248`
allows the narrowed unreleased branch to reset or rebuild current local `v25`
DBs and potentially stop accepting pre-narrowing local DB shapes. That is not
yet a clean split. The current compatibility/version docs still encode the
disputed `0.6.0` + `v25` support row and the normal in-place migration
expectation. Unless this plan explicitly says which parts of those docs remain
authoritative during narrowing and which release-row claims are provisional,
reviewers and implementers still have circular support for retaining the
current `v25` continuity story.

### 3. Phase 2 still leaves a loophole for correctness-critical runtime tables to survive

`docs/plans/plan_runtime-release-alignment_2_2026-03-18.md:323-342` allows a
disputed table to be classified as "correctness-critical", but
`docs/plans/plan_runtime-release-alignment_2_2026-03-18.md:105-115` and
`docs/plans/plan_runtime-release-alignment_2_2026-03-18.md:256-259` say the
runtime DB must remain pluggable, non-authoritative, and advisory. The plan
never states the mandatory consequence if `dirty_knowledge_paths`,
`path_observations`, or `invalidation_tokens` turn out to be
correctness-critical in startup reconcile, watcher enqueue, rename/move
propagation, or query-index invalidation paths. That cannot remain an analysis
label only. The plan should state that any disputed machine-local table found
to be correctness-critical fails retention in this narrowing effort and must be
reverted, deferred, or escalated into a separately approved architecture change.

### 4. The rollback policy still leaves the concrete runtime-shape outcome to later judgment

`docs/plans/plan_runtime-release-alignment_2_2026-03-18.md:229-247` makes
reset/rebuild available and forbids a new schema bump, but it still does not
force the narrowed disposition to choose the exact runtime-shape consequence.
There are materially different outcomes here: preserve the current `v25` table
set and make disputed tables inert, treat pre-narrowing local `v25` DBs as
unsupported and rebuild from scratch on explicit detection, or something else.
Those choices affect startup detection, docs, and test obligations. The plan
should require Phase 3 to record the exact runtime-shape strategy rather than a
generic rebuild/reset allowance.

## Open Questions / Assumptions

- I am assuming the intent is to produce a normal next revision artifact such as
  `plan_runtime-release-alignment_3_<date>.md`, not an ad hoc supporting note.
- I am assuming the current `0.6.0` / `v25` compatibility row may still be
  revised before release because the row is not yet shipped to end users.
- I am assuming "correctness-critical" was meant as an audit outcome to force
  narrowing, not as a permissible retained category for disputed runtime
  surfaces.

## Verdict

Changes required.

The revision is materially tighter than the root plan, and the per-workflow
negative-proof matrix is much stronger, but the gate is still not approval
ready. Tighten the artifact requirements after Phase 3, finish separating
provisional release-row claims from stable invariants, and remove the remaining
loopholes around correctness-critical retention and rollback shape.

This review artifact does not approve the plan and does not authorize
implementation.

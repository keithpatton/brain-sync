# Review

Reviewed artifact: `docs/plans/plan_runtime-release-alignment_3_2026-03-18.md`
Reviewed on: `2026-03-18`
Reviewer: `codex-gpt-5`

## Findings

### 1. `operational_events` still is not forced through the same concrete narrowing decision path as the other retained candidates

`docs/plans/plan_runtime-release-alignment_3_2026-03-18.md:267-279` says
`operational_events` may be kept only by explicit scope decision, and
`docs/plans/plan_runtime-release-alignment_3_2026-03-18.md:519-522` correctly
includes it in the later negative-proof matrix. But the mandatory narrowing
outputs in Phase 2 and Phase 3 are written only around the "disputed" tables or
"disputed surfaces" at
`docs/plans/plan_runtime-release-alignment_3_2026-03-18.md:395-417` and
`docs/plans/plan_runtime-release-alignment_3_2026-03-18.md:432-449`. That means
the required authority disposition row, the concrete keep/revert/defer table,
and the exact post-Phase-3 narrowed decision do not explicitly have to name
`operational_events` at all.

For a release-stabilization plan, that is still too loose. `operational_events`
is a retained runtime surface candidate and the user explicitly asked for
per-table, per-consuming-workflow proof burden for it. The plan should force
`operational_events` through the same Phase 2/3 recorded decision path as any
other retained table candidate, even if the likely answer is "keep" under a
strict observability-only contract. Otherwise its retention can still happen by
implication rather than by a required narrowed decision artifact.

## Open Questions / Assumptions

- I am assuming the planner intended `operational_events` to be decided in the
  post-Phase-3 narrowing artifact, not merely validated later in Phase 5.
- I am assuming "disputed surfaces" was meant to refer only to the cache-like
  tables, not to all runtime surfaces still requiring an explicit keep/revert
  call.

## Verdict

Changes required.

This revision closes the earlier lifecycle, compatibility, and
correctness-critical loopholes, but it is still not fully approval-ready
because `operational_events` is not yet forced into the mandatory narrowing
decision outputs.

This review artifact does not approve the plan and does not authorize
implementation.

# Plan source-state-boundary 2 Implementation Notes

2026-03-20T18:15:39+13:00
Change: Closure review recorded for `plan_source-state-boundary_2_approved_2026-03-19T19-05-47.md`; repository history indicates the approved boundary reset landed.
Reason: Commit `7a0f2f3` on 2026-03-19 (`Implement source state boundary reset`) matches the implementation notes already captured here and is the strongest direct repository signal for this plan.
Assumed completion date: 2026-03-19T23:00:06+13:00.
Status: Completed (inferred from git history).

2026-03-19T22:58:59+13:00
Change: Stabilization commit point reached after adversarial review hardening. The remaining known issues were intentionally parked as bounded follow-up work rather than continuing to churn this plan implementation.
Reason: The remaining regressions are narrow post-implementation inconsistencies with limited blast radius, not signs of an unstable source-state-boundary model. Follow-up issues to track in Trello:
- `Stale sources should override long poll cadence and rematerialize promptly`
- `List and status surfaces should include missing sources as registered`
Status: Implemented / parked for follow-up.

2026-03-19T22:58:59+13:00
Change: App-version continuity remained on the `0.6.0` support row while Brain Format moved to `1.1` and runtime schema moved to `v26`.
Reason: Explicit implementation-time product direction overrode the earlier plan expectation of moving to the next app-major row. Docs and tests were aligned to that decision.
Status: Implemented.

2026-03-19T23:55:00+13:00
Change: Final review-pass alignment tightened explicit remove and missing-clear semantics without changing the approved lifecycle model. CLI/MCP/user-facing wording now reflects destructive explicit remove, source-owned file cleanup uses the same rediscovery tiers as reconcile, and the public missing-clear helper returns `stale` rather than `materialized`.
Reason: Close review-identified contract drift while keeping the portable/runtime boundary reset scoped to the already-settled product rules.
Status: Implemented.

2026-03-19T23:20:00+13:00
Change: Explicit source removal does not prune now-empty knowledge directories after deleting source-owned files.
Reason: User-directed tightening during implementation. Empty folder cleanup is outside the source-state boundary reset and risks turning source removal into broader directory-structure policy.
Status: Implemented.

2026-03-19T23:05:00+13:00
Change: Watcher-driven reconcile is explicitly non-finalizing. It may mark first-stage `missing`, repair `knowledge_path`, and mark `stale`, but only deterministic finalizing flows perform second-stage missing deregistration.
Reason: Preserve the intended missing grace period during normal live filesystem churn instead of letting unrelated watcher events collapse it.
Status: Implemented.

2026-03-19T23:05:00+13:00
Change: Explicit source removal is destructive to synced source material. `remove_source` now removes source registration, synced markdown, and source-owned attachments together rather than trying to detach kept local copies.
Reason: User-directed implementation tightening during execution. The preserve-content variant introduced unnecessary detach/orphan semantics and made doctor cleanliness harder to reason about. Local filesystem deletion remains the softer path that enters the missing lifecycle first.
Status: Implemented.

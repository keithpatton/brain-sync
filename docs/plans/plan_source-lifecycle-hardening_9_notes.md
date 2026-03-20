# Plan source-lifecycle-hardening 9 Implementation Notes

2026-03-20T17:54:52+13:00
Change: Treat `operational_events` as a machine-local, append-only temporal trail for diagnostics, observability, and testing during source lifecycle hardening. It must remain non-authoritative, non-fatal, and explicitly not a replay source.
Reason: The runtime event table should provide enough rich event information to understand and diagnose bugs, especially where daemon, CLI, MCP, watcher, reconcile, and restart-driven actions overlap in time, without becoming a second source of lifecycle truth.
Status: Clarified.

2026-03-20T17:54:52+13:00
Change: Preserve the existing event spine where semantics still hold, but move authoritative lifecycle emission to the new sync-owned lifecycle/finalization surfaces instead of leaving parallel application-owned emit points as the long-term owner. Existing emitted event types that should be preserved or intentionally superseded during this work are `source.registered`, `source.updated`, `source.moved`, `source.removed`, `source.missing_marked`, `source.child_registered`, `source.child_request.saved`, `source.child_request.cleared`, `reconcile.path_updated`, `reconcile.missing_marked`, `reconcile.deleted`, `reconcile.orphan_cleaned`, `reconcile.path_enqueued`, `watcher.structure_observed`, `watcher.move_observed`, `watcher.move_applied`, `regen.enqueued`, `regen.started`, `regen.completed`, `regen.failed`, `query.index.invalidated`, and `query.index.rebuilt`.
Reason: These events already provide useful historical coverage. The hardening work should retain continuity for debugging and tests while relocating ownership to the new authoritative orchestration seams.
Status: Clarified.

2026-03-20T17:54:52+13:00
Change: For this plan, add an exact lifecycle/finalization event slice at the new authoritative sync-owned boundary rather than relying only on logs. Recommended minimum additional event types are `source.missing_confirmed`, `source.rediscovered`, `source.finalization_pending_confirmation`, `source.finalized`, `source.finalization_lease_conflict`, `source.finalization_not_missing`, and `source.finalization_not_found`. Emit once per authoritative lifecycle result with stable fields: `canonical_id`, `knowledge_path` when known, `outcome` aligned to the terminal/result state, and compact `details_json` only for disambiguating evidence such as confirmation count, lease owner, or revalidation basis.
Reason: The table should act as a temporal point of truth for key domain events in the operational space so overlapping actions can be analyzed after the fact and tests can assert definitive behavior across process boundaries.
Status: Recommended.

2026-03-20T17:54:52+13:00
Change: Do not broaden this implementation into a full repo-wide event-catalog refactor. Centralizing event-name constants and removing scattered string literals should be handled as follow-up work after this approved plan is executed. Within this plan, prefer bounded changes that avoid unnecessary naming churn while keeping new lifecycle/finalization events exact and reviewable.
Reason: The approved work is source lifecycle hardening, not a general observability redesign. Keeping the event-catalog centralization as a follow-up avoids reopening plan scope while still giving the implementation agent enough guidance to preserve and extend the event model responsibly.
Status: Deferred follow-up.

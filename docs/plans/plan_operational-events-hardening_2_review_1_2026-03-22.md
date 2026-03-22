# Review

Plan reviewed: `docs/plans/plan_operational-events-hardening_2_2026-03-22.md`
Reviewer: Codex
Date: 2026-03-22

## Verdict

Changes required.

Create a new plan revision that resolves the finding below. This review
artifact does not approve the plan and does not authorize implementation.

## Findings

### 1. The required-field matrix now contains at least one incorrect payload requirement and one under-justified payload rename

Revision 2 fixed the earlier boundary and enforcement ambiguity, but the new
required-field matrix introduces a material contract problem in the event
payload requirements themselves.

Concrete code reality today:

- `source.child_registered` is emitted with the child source in the row's
  `canonical_id`, while `details` currently carries
  `parent_canonical_id` in
  `src/brain_sync/sync/lifecycle.py`
- `watcher.move_observed` and `watcher.move_applied` currently emit
  `details={"src": ..., "dest": ...}` in
  `src/brain_sync/sync/lifecycle.py`

But the revision's required-field matrix instead requires:

- `source.child_registered` -> `details.child_canonical_id`
- `watcher.move_observed` / `watcher.move_applied` ->
  `details.old_path` / `details.new_path`

That is still approval-blocking for two reasons:

1. `source.child_registered` appears to be wrong, not just different. The row's
   `canonical_id` already identifies the child, so requiring
   `details.child_canonical_id` duplicates existing row identity while dropping
   the actually useful parent linkage the current event carries. That would
   push the implementer into an incorrect payload contract.
2. The watcher move-key rename may be acceptable, but the plan does not justify
   it as an intentional contract change. Revision 2 frames this pass as bounded
   hardening rather than broader payload redesign, so changing stable detail
   keys needs to be explicitly defended or deferred.

Required revision:

- fix the `source.child_registered` field lock so it matches the intended
  correlation contract
- either:
  - keep the current watcher move detail keys and lock those explicitly, or
  - state clearly that this pass intentionally renames those keys, why that
    rename is required for REGEN/readability, and which tests/docs must prove
    the new contract
- recheck the full required-field matrix for similar row-vs-details mistakes so
  the approved plan does not encode a wrong event contract

## Summary

Revision 2 resolves the first review's main blockers around scope, ownership
guarding, daemon wiring, and documentation authority. The remaining issue is
in the required-field matrix itself: at least one required field is wrong for
the current event semantics, and one key rename is not yet justified strongly
enough for a bounded hardening pass.

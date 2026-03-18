# plan_runtime-failure-hardening_2 Review 1 - One Contract Gap Remains

**Reviewer:** Codex GPT-5
**Date:** 2026-03-18
**Reviewed document:** `docs/plans/plan_runtime-failure-hardening_2_2026-03-18.md`
**Reviewed against:**
- `docs/plans/README.md`
- `AGENTS.md`
- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- current runtime, regen, sync, and source code in `src/brain_sync/`
- machine-local evidence in `%USERPROFILE%\.brain-sync\logs\brain-sync.log`

---

## Verdict

Changes required.

This revision fixes most of the blockers from the prior review. The bundle is
now much tighter around current code reality, the evidence anchors are better,
and the scope boundaries are substantially clearer.

One material ambiguity still remains in the `regen_locks` conflict contract.
This review artifact does **not** approve the plan and does **not** authorize
implementation.

---

## Finding

### F1. Contract A currently reads as if `owner_id` is last-writer-wins, which would weaken the existing regen ownership model

The revised plan says that for `regen_locks.knowledge_path`, replay of the same
normalized path is replay-safe and that when concurrent or repeated callers
write different lifecycle fields for the same path, "the later runtime write
wins" for lifecycle-only fields including `owner_id`
([`plan_runtime-failure-hardening_2_2026-03-18.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/plan_runtime-failure-hardening_2_2026-03-18.md):317-321).

That is too broad against current code reality:

- [`save_regen_lock()`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/runtime/repository.py#L1657)
  is a blind upsert.
- [`acquire_regen_ownership()`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/runtime/repository.py#L1725)
  is the actual guarded ownership path and only allows acquisition when the row
  is unowned, already ours, or stale.
- [`save_insight_state()`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/application/insights.py#L70)
  and other callers can still persist lifecycle rows outside that acquisition
  helper.

So the plan currently leaves a dangerous interpretation available to an
implementer: conflicting `owner_id` writes could be treated as replay-safe
simply because they target the same normalized `knowledge_path`.

That would blur an important boundary:

- replay-safe update of lifecycle state for the same logical owner
- versus invalid ownership stomp while another owner still legitimately holds
  the lock

The whole point of moving from the retired `insight_state` evidence to the
current `regen_locks` owner is to preserve present-day semantics, not to widen
them accidentally.

**Required revision:** Tighten Contract A so it explicitly distinguishes:

1. replay-safe updates by the same owner or by non-ownership lifecycle writes
2. ownership transfer through the existing guarded paths (`acquire`,
   `release`, stale reclaim)
3. conflicting live-owner writes as invariant violations or rejected updates,
   not last-writer-wins behavior

The acceptance criteria should also prove that a second live owner cannot
silently overwrite `owner_id` for an actively owned `knowledge_path`.

---

## Conclusion

This is close. After the `regen_locks.owner_id` contract is tightened so it
matches the existing ownership-acquisition model, I would expect the next
revision to be ready for approval review.

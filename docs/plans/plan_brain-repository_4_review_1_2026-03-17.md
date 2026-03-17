# plan_brain-repository_4 Review 1 - Correction Closed, Approval Recommended

**Reviewer:** Codex GPT-5
**Date:** 2026-03-17
**Reviewed document:** `docs/plans/plan_brain-repository_4_2026-03-17.md`
**Prior approved revision:** `docs/plans/plan_brain-repository_2_approved_2026-03-17T11-13-59.md`
**Prior review:** `docs/plans/plan_brain-repository_3_review_1_2026-03-17.md`
**Reviewed against:**
- `docs/plans/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`
- `docs/plans/plan_runtime-observability_3_notes.md`
- `docs/plans/plan_runtime-observability_supporting.md`
- current code in `src/brain_sync/brain_repository.py`
- current code in `src/brain_sync/state.py`
- current code in `src/brain_sync/pipeline.py`
- current code in `src/brain_sync/commands/sources.py`
- current code in `src/brain_sync/attachments.py`
- current code in `src/brain_sync/commands/doctor.py`
- current code in `src/brain_sync/regen.py`

**Purpose:** Review revision 4 of the corrective brain-repository plan, with
specific attention to whether it closes the two blocking gaps from the prior
review: explicit carry-forward of revision 2's still-binding constraints, and
a verifiable write-boundary closure gate strong enough to support later
observability work.

---

## Review-1 Resolution Status

The two blocking issues from the revision-3 review are resolved.

| ID | Prior issue | Resolution in revision 4 | Verified |
|---|---|---|---|
| F1 | Revision 3 did not clearly preserve revision 2's still-valid requirements | Revision 4 adds an explicit carry-forward section and names the key continuing constraints, including journal durability, doctor/attachments scope, structured outcomes, watcher role, and sequencing | Yes |
| F2 | The write-first rule was not yet a strong enough closure gate | Revision 4 adds an explicit inventory requirement, exception-list rule, write-adjacent authority-read scope, dependency-direction cleanup, and stronger acceptance criteria | Yes |

---

## Findings

No blocking findings.

Revision 4 fixes the key approval problem in revision 3: it now behaves like a
true correction layer on top of the approved revision-2 architecture instead
of reading like a narrower replacement plan.

That shows up in the right places:

- the new carry-forward section makes it explicit that revision 2 remains in
  force unless revision 4 deliberately tightens or replaces a requirement
- the plan preserves the important revision-2 invariants that were at risk of
  being weakened by omission, especially journal durability, doctor and
  attachment migration scope, observability-ready structured outcomes, watcher
  edge-observer semantics, and sequencing before observability and the later
  regen refactor
- the write-first rule is now expressed as a genuine closure gate rather than
  a hotspot-only migration intention
- the write-adjacent authority-read clarification closes the loophole where
  semantic ownership could remain split even after raw file writes moved
- the dependency-direction cleanup requirement addresses the real drift visible
  in the current code, where `brain_repository.py` still imports helpers from
  `pipeline.py`

That corrected shape also aligns with the supporting observability audit:

- the plan now requires a full portable-write inventory rather than assuming
  the current hotspot list is complete
- it allows temporary exceptions only if they are explicit and justified
- it keeps observability parked until the write seam is actually trustworthy
  enough to serve as an event boundary

The resulting scope remains narrow enough to be practical. Revision 4 does not
re-open full read centralization, schema redesign, or a broader architectural
rewrite. It stays focused on the two things that matter most right now:

1. restoring the intended portable-vs-runtime persistence seams
2. making the portable write boundary real enough to support the next stage

---

## Advisory Notes

### A1. Keep the temporary exception list visible and small

Revision 4 correctly permits temporary exceptions only as an explicit,
justified list. During implementation, that list should stay short and visible
enough that it acts as migration pressure rather than becoming a durable
second path.

### A2. Preserve the distinction between repository outcomes and workflow orchestration

Revision 4 correctly requires dependency-direction cleanup. The implementation
will be strongest if repository methods return durable semantic outcomes while
workflow modules remain responsible for sequencing, retries, polling, and
interface-specific orchestration.

---

## Verdict

Approval recommended.

Create `plan_brain-repository_4_approved_<datetime>.md` before
implementation. This review artifact does not itself approve the plan.

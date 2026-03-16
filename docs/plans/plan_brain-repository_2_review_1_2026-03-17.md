# plan_brain-repository_2 Review 1 - Review Gaps Closed, Approval Recommended

**Reviewer:** Codex GPT-5
**Date:** 2026-03-17
**Reviewed document:** `docs/plans/plan_brain-repository_2_2026-03-17.md`
**Prior review:** `docs/plans/plan_brain-repository_review_1_2026-03-17.md`
**Reviewed against:**
- `docs/plans/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/plans/plan_runtime-observability_3_approved_2026-03-16T15-57-33.md`
- `AGENTS.md`
- current code in `src/brain_sync/watcher.py`
- current code in `src/brain_sync/reconcile.py`
- current code in `src/brain_sync/pipeline.py`
- current code in `src/brain_sync/commands/sources.py`
- current code in `src/brain_sync/commands/doctor.py`
- current code in `src/brain_sync/attachments.py`
- current code in `src/brain_sync/state.py`
- current code in `src/brain_sync/manifest.py`
- current code in `src/brain_sync/sidecar.py`
- current code in `src/brain_sync/regen.py`

**Purpose:** Review revision 2 of the brain-repository plan after the first
review, with specific attention to whether it now closes the portable-state
scope gap around attachments and doctor, and whether it preserves the journal
durability contract strongly enough before approval.

---

## Review-1 Resolution Status

The two blocking issues from the first review are resolved.

| ID | Prior issue | Resolution in revision 2 | Verified |
|---|---|---|---|
| F1 | `attachments.py` and `commands/doctor.py` were outside the explicit migration surface | Revision 2 adds both modules to the authoritative seam list, scope, workstreams, expected caller responsibilities, risks, tests, and acceptance criteria | Yes |
| F2 | Journal durability and append-only rules were not encoded strongly enough | Revision 2 adds a fixed design decision for journal preservation, makes journal APIs append-oriented, and adds cleanup-focused test and acceptance obligations | Yes |

---

## Findings

No blocking findings.

Revision 2 makes the important change revision 1 needed: it turns both review
concerns into explicit plan requirements rather than leaving them implicit.

That shows up in the right places:

- `attachments.py` and `commands/doctor.py` are now part of the named current
  authority surface and no longer treated as out-of-band implementation detail
- the scope now includes attachment lifecycle behavior and doctor-facing repair
  migration
- the repository responsibilities now include attachment durability and
  doctor-facing repair helpers
- the workstreams now distinguish source/attachment migration, doctor/repair
  migration, and area-state/journal cleanup semantics
- the acceptance criteria now verify both repository-owned attachment
  lifecycle behavior and journal preservation during cleanup

That revised shape matches the current code seams much better:

- `src/brain_sync/attachments.py` is on the portable managed-file write path
- `src/brain_sync/commands/doctor.py` is the repair and drift-recovery path
- `src/brain_sync/watcher.py`, `src/brain_sync/reconcile.py`,
  `src/brain_sync/pipeline.py`, and `src/brain_sync/regen.py` remain the main
  scattered authority paths the repository layer is supposed to absorb

The journal clarification is especially important and now lands correctly. The
plan no longer risks turning repository-owned cleanup into a generalized
"delete managed files" abstraction that would violate `docs/RULES.md`.

---

## Advisory Notes

### A1. Keep doctor-facing repository operations aligned with mainline semantics, not as a thin wrapper layer

This is not blocking, but it is worth preserving during implementation.

Revision 2 correctly moves doctor into scope. The implementation will be
stronger if doctor consumes the same repository operations and semantic result
types as normal convergence paths wherever possible, rather than introducing a
parallel "doctor-only" repository API that re-encodes similar rules with a
different shape.

### A2. Approval artifact should remain separate from this review

This review recommends approval, but it is **not** approval.

Per `docs/plans/README.md`, the approved basis for implementation is created
only when the corresponding `_approved_<datetime>` artifact exists.

---

## Verdict

Approval recommended.

Create `plan_brain-repository_2_approved_<datetime>.md` before
implementation. This review artifact does not itself approve the plan.

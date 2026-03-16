# plan_windows-long-paths_2 Review 1 - Scope Closed, Approval Recommended

**Reviewer:** Codex GPT-5
**Date:** 2026-03-16
**Reviewed document:** `docs/plans/plan_windows-long-paths_2_2026-03-16.md`
**Prior review:** `docs/plans/plan_windows-long-paths_review_1_2026-03-16.md`
**Reviewed against:**
- `docs/plans/README.md`
- `docs/brain-format/README.md`
- `docs/brain-format/RULES.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- current code in `src/brain_sync/fileops.py`
- current code in `src/brain_sync/fs_utils.py`
- current code in `src/brain_sync/pipeline.py`
- current code in `src/brain_sync/reconcile.py`
- current code in `src/brain_sync/__main__.py`
- current code in `src/brain_sync/regen.py`
- current code in `src/brain_sync/commands/doctor.py`
- current code in `src/brain_sync/commands/sources.py`

**Purpose:** Review revision 2 of the Windows long-path correctness plan after
the first review, with specific attention to whether it now closes the watcher
/ reconciliation scope gap and the outward-path portability gap before any
approval artifact is created.

---

## Review-1 Resolution Status

The key issues from the first review are resolved.

| ID | Prior issue | Resolution in revision 2 | Verified |
|---|---|---|---|
| C1 | Watcher/reconciliation treatment left open | Added explicit objective, scope, fixed design decision, workstreams, and verification for `fs_utils`, reconcile, and watcher-adjacent paths | Yes |
| C2 | Outward path contract not fixed | Added explicit internal-only `\\?\` rule plus portable-path requirements for returned values, manifests, and diagnostics | Yes |

---

## Findings

No blocking findings.

Revision 2 does the important thing revision 1 did not: it turns the two prior
boundary concerns into settled plan requirements instead of leaving them as
review-time questions.

That shows up in the right places:

- the objective now requires doctor, startup reconcile, and live watcher
  handling to share one filesystem view on Windows
- the scope now explicitly includes `fs_utils.py`, `reconcile.py`, and
  watcher-adjacent `__main__.py` paths
- the fixed design decisions now state both that filesystem-truth readers must
  share one Windows-safe view and that `\\?\` forms are internal only
- the workstreams and verification gates now check both runtime correctness and
  outward portability

That revised shape matches the current architecture and code seams much better
than the first plan:

- `fs_utils.py` is part of the content-discovery truth model
- `reconcile.py` depends on that truth model during startup recovery
- `__main__.py` depends on `classify_folder_change()` for live watcher
  decisions
- `commands/sources.py` and `commands/doctor.py` are both on the path where
  rediscovered values can become persisted manifest state

The revision also keeps the portable Brain Format contract intact by making the
internal/external path boundary explicit rather than implied.

---

## Advisory Notes

### A1. Keep outward-path normalization at the helper boundary, not scattered across callers

This is not a blocking issue, but it is worth preserving during
implementation.

Revision 2 correctly requires returned values to come back in normal caller-safe
form. The implementation will be easier to reason about if that conversion is
centralized in the shared Windows-safe helper layer rather than reimplemented
independently in `doctor.py`, `commands/sources.py`, `pipeline.py`, and other
callers.

That reduces the chance of one code path returning a prefixed absolute `Path`
while another returns a root-relative normal form.

### A2. Approval artifact should remain separate from this review

This review recommends approval, but it is **not** approval.

Per `docs/plans/README.md`, the next step is to create a separate approval
artifact named on the approved-plan pattern before implementation begins.

---

## What The Revision Gets Right

1. It explicitly includes the runtime correctness paths that participate in the
   repository's filesystem-truth model.
2. It protects the Brain Format contract by making `materialized_path`
   portability an implementation invariant rather than a hoped-for outcome.
3. It ties scope, design decisions, workstreams, and verification together
   cleanly instead of leaving important behavior to implementer inference.
4. It stays appropriately narrow: no format change, no manifest schema change,
   no broad filesystem abstraction rewrite.

---

## Verdict

Approval recommended.

Create `plan_windows-long-paths_2_approved_<datetime>.md` before
implementation. This review artifact does not itself approve the plan.

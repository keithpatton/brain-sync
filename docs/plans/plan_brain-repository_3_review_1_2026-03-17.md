# plan_brain-repository_3 Review 1 - Correction Direction Is Right, But Approval Should Wait For Two Closure Fixes

**Reviewer:** Codex GPT-5
**Date:** 2026-03-17
**Reviewed document:** `docs/plans/plan_brain-repository_3_2026-03-17.md`
**Prior approved revision:** `docs/plans/plan_brain-repository_2_approved_2026-03-17T11-13-59.md`
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

**Purpose:** Review revision 3 as a corrective plan after implementation drift,
with specific attention to whether it fairly diagnoses what went wrong without
misstating revision 2, whether the corrected portable-vs-runtime layering is
right, whether write-first enforcement and observability sequencing are scoped
correctly, and whether the revision is concrete enough to approve as the new
latest implementation basis.

---

## Findings

### F1. Revision 3 is not yet explicit enough about which revision-2 constraints remain in force

This is the main architectural risk in approving revision 3 as the new latest
plan artifact.

The framing of revision 3 is fair: it correctly says revision 2 was
directionally sound and that the failure was execution drift, not planner
misdirection. The corrected layering is also directionally right:

- `brain_repository.py` as the portable-brain persistence boundary
- `state.py` as the runtime-plane persistence boundary
- `fileops.py`, `manifest.py`, and `sidecar.py` beneath those seams rather
  than acting as the seams themselves
- observability sequenced after trustworthy write boundaries exist

The problem is that revision 3 is much narrower than revision 2, while the
workflow treats the latest approved revision as the implementation basis. As
written, revision 3 does not clearly say that revision 2's still-valid
requirements continue to apply unless explicitly superseded.

That matters because revision 2 carried several concrete constraints that are
still important to the correction, including:

- journal durability and append-only preservation as a fixed design decision
- explicit doctor and attachment migration obligations
- structured semantic outcomes for later observability
- watcher-as-edge-observer wording that prevents semantic authority drift
- broader acceptance gates around cleanup, repair, and repo-owned semantics

Revision 3 still points in the same direction, but it no longer preserves
those items with the same force. If approved as-is, an implementer could
reasonably read the omissions as intentional narrowing rather than "all prior
non-conflicting requirements still stand."

Required correction:

- add an explicit carry-forward statement that revision 2 remains in force
  except where revision 3 deliberately tightens or replaces it, or
- restate the revision-2 invariants that must remain binding in the corrected
  plan

Without that, the corrective revision risks weakening the very architecture it
is trying to restore.

### F2. The write-first rule is correct, but the plan does not yet make it verifiable enough to trust before observability resumes

The scope choice is right: write mediation is the highest-leverage immediate
gate, and full read centralization can wait.

The remaining issue is that revision 3 states the write-first invariant more
strongly than its workstreams and acceptance criteria currently enforce it.

Revision 3 says:

- all normal runtime portable-brain writes should go through
  `brain_repository.py`
- runtime observability should pause until those write seams are trustworthy

But the enforcement and verification shape is still too soft:

- the workstreams no longer include revision 2's explicit authority inventory
  as a required implementation step
- acceptance criterion 5 only requires the **known** write hotspots to be
  migrated or documented as temporary exceptions
- Workstream 2 guards only direct primitive-module imports, even though the
  current write bypasses also occur through direct `Path`, `shutil`, and
  helper-level writes in higher modules such as `pipeline.py`,
  `commands/sources.py`, `attachments.py`, `commands/doctor.py`, and
  `regen.py`

The supporting observability audit is helpful here: it already identifies the
main remaining portable mutation seams. But the plan should turn that audit
into a real closure gate rather than leaving it as background context.

Required correction:

- add an explicit portable-write inventory / exception-list step as part of
  execution
- require the implementation to close or document **all** remaining normal
  runtime portable-write paths, not only the currently known hotspots
- strengthen the guardrail language so it does not rely only on primitive
  imports when the real boundary risk is any direct portable mutation outside
  the repository seam

Without that stronger closure rule, observability could be resumed on top of a
boundary that is still porous in practice.

---

## What Revision 3 Gets Right

Revision 3 does correctly capture the core failure mode without unfairly
blaming revision 2.

The current code supports that reading:

- `src/brain_sync/state.py` still contains portable mutation helpers such as
  `save_portable_insight_state()`, `delete_insight_state()`, and
  `clear_children_flag()`, which shows the runtime-plane seam is not yet clean
- `src/brain_sync/pipeline.py`, `src/brain_sync/commands/sources.py`,
  `src/brain_sync/attachments.py`, `src/brain_sync/commands/doctor.py`, and
  `src/brain_sync/regen.py` still contain direct portable-write behavior
- `src/brain_sync/brain_repository.py` already shows some upward workflow
  entanglement by importing pipeline helpers, which is exactly the kind of
  repository-shape drift revision 3 is trying to correct

So the correction thesis is sound:

- the problem was implementation drift away from the approved seam
- the target two-plane layering is correct
- write-first enforcement is the right immediate scope
- observability should wait until the write seams are actually trustworthy

---

## Advisory Notes

### A1. Make dependency-direction cleanup explicit for the repository correction

`brain_repository.py` currently imports helper behavior from `pipeline.py`.
That is strong evidence that the repository seam is still shaped partly around
workflow code rather than purely around durable brain semantics.

The corrected plan would be safer if it explicitly required moving those
cross-layer helpers into a neutral lower layer or into the repository itself
so the dependency direction becomes unambiguous.

### A2. Write-first does not mean write-only when the read determines semantic authority

Deferring broad read centralization is reasonable.

However, write-adjacent reads that determine the meaning of a durable
transition still need to move with the corrected seam. Source resolution,
missing/reappeared classification, and area-state load decisions are examples.

Otherwise the system can end up with "repository-owned file writes" but still
split semantic authority, which would weaken the later observability boundary.

---

## Verdict

Revision 3 diagnoses the drift correctly and points at the right corrected
layering and sequencing, but I do **not** recommend approval yet.

Create a further revision that:

1. explicitly carries forward the still-valid revision-2 constraints, and
2. turns the write-first rule into a verifiable closure gate rather than a
   hotspot-only migration target

This review artifact does not approve the plan.

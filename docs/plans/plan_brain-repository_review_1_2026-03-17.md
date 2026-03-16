# plan_brain-repository Review 1 - Boundary Direction Is Right, But Two Contract Gaps Remain

**Reviewer:** Codex GPT-5
**Date:** 2026-03-17
**Reviewed document:** `docs/plans/PLAN_brain-repository.md`
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

**Purpose:** Review the initial brain-repository plan with specific attention to
whether it captures the real current authority surface in code and whether it
preserves the portable-brain contract strongly enough before any approval
artifact is created.

---

## What Is Already Correct

The plan is aimed at a real architectural problem, and the central diagnosis
matches the current code.

The reviewed plan correctly identifies that:

- `watcher.py` still performs semantic folder-move handling directly across
  runtime and manifest state
- `reconcile.py`, `commands/sources.py`, and `pipeline.py` each own part of
  source identity and path-healing behavior
- `regen.py` still mixes classification, durable writes, and cleanup
- `state.py` still exposes transitional seams that reflect the prior DB-heavy
  authority model

That is consistent with the current implementation, so the plan direction is
good. The remaining issues are about closure of scope and contract detail, not
about whether the repository boundary is needed.

---

## Findings

### F1. The plan claims a central boundary for managed filesystem mutations, but it does not explicitly cover two current bypasses: `attachments.py` and `commands/doctor.py`

This is the main blocking issue.

The plan objective and scope are broad:

- it says portable-brain reads and writes should flow through one dedicated
  intermediary layer
- it includes managed filesystem operations in scope
- it says current callers should migrate to the repository boundary instead of
  coordinating manifests, sidecars, and managed paths directly

But the listed implementation seams and migration workstreams stop short of two
important current portable-state mutators:

- `src/brain_sync/attachments.py` writes and migrates managed attachment
  directories under `knowledge/**/.brain-sync/attachments/`
- `src/brain_sync/commands/doctor.py` directly reads and repairs manifests,
  managed identity frontmatter, sidecars, attachment directories, and runtime
  rebuild state

Those are not edge curiosities. They are part of the current authority surface:

- `attachments.py` is on the durable write path for portable managed files
- `doctor.py` is the repair/convergence path when the portable brain is in
  drift or partial corruption

If those seams are left outside the explicit migration map, the repository
layer can land while still leaving important portable-state interpretation and
mutation logic outside the boundary it claims to centralize.

Revision 2 should therefore do one of these explicitly:

1. Add `attachments.py` and `commands/doctor.py` to the authoritative code
   seam list and to the relevant migration/testing workstreams.
2. Or narrow the plan so it clearly excludes them for now and explains why
   leaving those bypasses does not violate the "single internal boundary"
   objective yet.

The current mixed form is too broad to approve safely.

### F2. The cleanup design does not yet encode the journal durability and append-only contract strongly enough

The second blocking issue is the treatment of journals.

The plan puts summaries, sidecars, journals, and cleanup behavior behind one
repository owner, and it says cleanup semantics should be made explicit for
deleted areas, empty areas, and stale managed artifacts. But it never carries
forward the current normative journal rules from `docs/RULES.md`.

Those rules are stronger than the plan currently states:

- when an area ceases to exist, the system cleans up insights and insight state
  but preserves journals
- journals are append-only
- journals survive automated cleanup, including orphan cleanup
- journals are durable and not regenerable

Without that contract being repeated here as a fixed design decision and an
acceptance/test obligation, the repository boundary could accidentally turn
"managed cleanup" into "cleanup of everything under `.brain-sync/`" for an
area. That would be a product-contract regression, not just an implementation
detail.

Revision 2 should make all of the following explicit:

- journals are not cleanup candidates in normal repository convergence flows
- repository journal APIs are append-only rather than generic rewrite/delete
  helpers
- deleted-area and empty-area cleanup tests must verify journal preservation

Until that is spelled out, the cleanup portion of the plan is underspecified.

---

## Recommended Revision Shape

Revision 2 should keep the current direction, but close these two gaps before
approval:

1. Either fully include `attachments.py` and `commands/doctor.py` in the
   repository-boundary migration, or explicitly narrow the claim that this plan
   centralizes all current portable-state mutation paths.
2. Add a fixed design decision and matching acceptance/test language that
   preserves the existing journal durability and append-only contract during
   repository-owned cleanup.

---

## Verdict

Approval not recommended for revision 1.

Create a revised plan artifact before any approval artifact is created. This
review artifact does not itself approve the plan.

# plan_portable-state-write-discipline Review 1 - Definition And Scope Need One More Pass

**Reviewer:** Codex GPT-5
**Date:** 2026-03-17
**Reviewed document:** `docs/plans/PLAN_portable-state-write-discipline.md`
**Reviewed against:**
- `docs/plans/README.md`
- `docs/brain-format/README.md`
- `docs/brain-format/GLOSSARY.md`
- `docs/brain-format/RULES.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`
- current code in `src/brain_sync/state.py`
- current code in `src/brain_sync/sidecar.py`
- current code in `src/brain_sync/regen.py`
- current code in `src/brain_sync/commands/doctor.py`
- current code in `src/brain_sync/manifest.py`
- current code in `src/brain_sync/fileops.py`

**Purpose:** Review the initial portable-state write-discipline plan with
specific attention to whether it clearly defines portable brain state,
distinguishes real portable changes from no-op churn, and scopes the runtime
write surfaces tightly enough for safe implementation.

---

## What Is Already Correct

The central diagnosis is sound and matches the current code.

The reviewed plan correctly identifies that:

- `save_insight_state()` currently couples portable sidecar persistence with
  runtime `regen_locks` updates
- `doctor --rebuild-db` currently replays through that shared path
- several regen flows double-write portable sidecar state through both
  `save_insight_state()` and `write_regen_meta()`

That diagnosis is consistent with the current implementation in:

- `src/brain_sync/state.py`
- `src/brain_sync/commands/doctor.py`
- `src/brain_sync/regen.py`

So the plan is aimed at a real problem. The remaining issues are about
definition precision and scope discipline, not about whether the bug exists.

---

## Findings

### F1. The plan uses "portable brain state" and "real portable state change" as if already defined, but it does not actually define them

This is the main blocking issue.

The plan's objective says "Portable brain state must only be altered when a
real portable state change has occurred", but the plan never turns either term
into a settled definition. It repeatedly uses "git-visible" and "portable
bytes unchanged" language, but those are symptoms and proxies, not the
normative contract.

That matters because the authoritative docs already define the higher-level
boundary:

- `docs/brain-format/GLOSSARY.md` defines brain state as the persistent,
  portable-on-disk state inside the brain root and excludes runtime state
- `docs/brain-format/RULES.md` states that the brain root is portable and that
  runtime state lives outside it
- `docs/architecture/ARCHITECTURE.md` states that portable state lives in the
  brain root while runtime state lives under the user config directory

But the reviewed plan does not yet state the implementation-level consequence
of that boundary clearly enough.

Revision 2 should add a settled terminology section that makes all of the
following explicit:

- portable brain state means durable filesystem state within the brain root
- runtime state means machine-local state outside the brain root
- a real portable change is a durable filesystem change to a portable entry,
  such as add, delete, rename, case-only rename where representable, or byte
  content change
- a no-op portable rewrite is not a real portable change merely because a code
  path opened and rewrote a file
- git-visible diffs are an operator-facing signal, not the source of truth
- transport artifacts such as line-ending normalization from external git
  operations are outside the intended invariant

Without that definition work, the implementation can easily drift into "keep
git clean" heuristics instead of enforcing the actual portable-state contract.

### F2. The plan claims a repository-wide invariant, but the workstreams only inventory the insight-state seam

The plan says it is establishing a repository-wide invariant, and it names
`manifest.py` and "manifests, and similar durable artifacts" as part of the
problem space. But the actual workstreams and implementation strategy only
inventory:

- `state.save_insight_state()`
- `sidecar.write_regen_meta()`
- regen outcome paths
- `doctor --rebuild-db`

That is too narrow for the objective as written.

The authoritative docs define portable brain state much more broadly than
insight-state sidecars alone. Within the brain root, portable state also
includes:

- root manifests under `.brain-sync/sources/`
- materialized synced documents under `knowledge/`
- summaries, journals, and attachments under per-area `.brain-sync/`

Current code also has multiple portable write seams outside the sidecar path,
including `manifest.py`, source materialization flows, attachment writes, and
summary/journal writes.

Revision 2 should therefore do one of two things explicitly:

1. Narrow the plan title, objective, scope, and verification so this is
   clearly an "insight-state and regen/doctor portable no-op write discipline"
   plan.
2. Or keep the repository-wide objective, but add a first-class portable write
   surface inventory across all portable mutators in the brain root, then mark
   which surfaces this implementation changes now versus which are deferred.

Either approach is acceptable. The current mixed form is not.

### F3. The open questions section still leaves review-critical decisions unresolved

The plan says these questions should be resolved during review before
implementation begins, but revision 1 still leaves them open.

At this point the review record is strong enough to close them in the next
revision:

- the fix should be both API-separation and content-sensitive-write work, not
  one or the other
- there is no justified runtime-only scenario in this seam where rewriting
  unchanged portable sidecar bytes is desirable
- the definition of portable brain state belongs at least in the Brain Format
  glossary/rules layer, while the runtime ownership split and code-seam
  explanation belong in architecture

Leaving those as open questions keeps the approval gate ambiguous when they are
actually core design decisions.

---

## Recommended Revision Shape

Revision 2 should keep the existing diagnosis and work on top of it, but make
these changes before approval:

1. Add an explicit terminology/invariant section that defines portable brain
   state, real portable change, no-op portable rewrite, and the role of git
   diffs as an observable proxy rather than the authority.
2. Decide whether this is a sidecar/regen/doctor plan or a truly
   repository-wide portable-write-discipline plan, then align title, scope,
   workstreams, and verification to that choice.
3. Convert the current open questions into settled decisions and list the
   expected doc homes up front instead of leaving them tentative.

---

## Verdict

Approval not recommended for revision 1.

Create a revised plan artifact before any approval artifact is created. This
review artifact does not itself approve the plan.

# plan_architecture-hardening Review 1 - Revision Needed Before Approval

**Reviewer:** Codex GPT-5
**Date:** 2026-03-17
**Reviewed document:** `docs/plans/PLAN_architecture-hardening.md`
**Reviewed against:**
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/architecture/reviews/TEMPLATE.md`
- `docs/architecture/reviews/2026-03-17-baseline.md`

**Purpose:** Review the canonical architecture-hardening plan for approval
readiness, with specific attention to whether it resolves the baseline
architecture findings into implementable decisions rather than leaving key
boundary choices to the implementation phase.

---

## Findings

### F1. The plan still leaves the child-discovery contract decision open at the exact point where the baseline review said guesswork must stop

The plan correctly identifies child-discovery intent as a top blocker, but it
does not actually finish the design decision. In the fixed decisions section,
`fetch_children` and `child_path` are said to need either:

- a runtime-only owner, or
- removal of the feature

The next sentence then says the plan assumes the runtime-only choice only if it
can be made unambiguous without a Brain Format change.

That is still implementation-time branching on a core contract question. The
baseline architecture review called this issue out precisely because the system
already models this concept in contradictory ways across `application`,
`brain`, `runtime`, and `sync`. A hardening plan needs to choose the steady
state now, or define an explicit gate that forces a short follow-up revision
before workstream 1 begins. As written, an implementer still has to decide
whether the feature survives, what owns it, and what user-visible behavior is
preserved.

This is a blocking gap because `docs/plans/README.md` says approval should be
withheld when key design decisions are deferred to implementer guesswork.

Plan evidence:

- `docs/plans/PLAN_architecture-hardening.md:107`
- `docs/plans/PLAN_architecture-hardening.md:115`

Baseline evidence:

- `docs/architecture/reviews/2026-03-17-baseline.md` critical finding 1

Required revision:

The next plan revision should make one of these explicit:

- child-discovery intent is removed from the product surface in this plan, with
  the affected commands and tests named, or
- child-discovery intent survives as runtime-only behavior, with one named
  owner, explicit non-durable semantics, and caller migration rules

---

### F2. The runtime-ownership workstream does not define the steady-state owner for cross-plane projection logic

Workstream 3 says `runtime/repository.py` should be split into focused owners,
but its acceptance criteria stop at "separable by module" and "easier to audit
and test." That is not enough for this specific problem.

The baseline review did not just say the file is too large. It said the module
mixes runtime ownership with source-state projection, portable sidecar
projection, and compatibility stubs. The architecture docs also say portable
brain semantics belong to `brain/` and runtime semantics belong to `runtime/`.

The plan never states what must happen to the projection logic that currently
bridges those planes. Without that, implementation could satisfy the plan by
splitting one monolith into several runtime-owned modules while preserving the
same cross-plane ambiguity that triggered the review finding in the first
place.

This is another approval blocker because the plan has not yet named the target
ownership model for one of the highest-blast-radius seams in the repository.

Plan evidence:

- `docs/plans/PLAN_architecture-hardening.md:194`
- `docs/plans/PLAN_architecture-hardening.md:205`
- `docs/plans/PLAN_architecture-hardening.md:217`

Baseline and architecture evidence:

- `docs/architecture/reviews/2026-03-17-baseline.md` critical finding 3
- `docs/architecture/ARCHITECTURE.md` section `2.5. State Authority Model`
- `docs/RULES.md` section `Persistence Plane Ownership`

Required revision:

The next revision should state the approved steady state for manifest/sidecar
projection explicitly. For example:

- projection leaves `runtime/` and moves to an `application/` or `brain/`
  owned read/service layer, or
- a narrow runtime-owned projection surface is intentionally retained, with its
  exact inputs, outputs, and allowed cross-plane dependencies defined

---

### F3. The plan identifies root scoping as a problem but does not choose whether the hardening outcome is explicitly single-brain or genuinely root-isolated

The problem statement names root scoping and runtime isolation as a current
risk, and workstream 5 says root-scoping assumptions should be made explicit.
Its acceptance criterion then says root-agnostic APIs should either drop unused
root arguments or become genuinely root-aware.

That is still two materially different architectures:

- one where the system intentionally remains single-brain in runtime storage
  and APIs are simplified to say so, or
- one where runtime state and telemetry become meaningfully root-isolated

Both are defensible, but they drive different code movement, test coverage, and
observability semantics. Because the plan is supposed to prepare later
observability and scale work, leaving this decision open is not a small
implementation detail.

This needs to be resolved before approval so later workstreams do not optimize
for incompatible end states.

Plan evidence:

- `docs/plans/PLAN_architecture-hardening.md:68`
- `docs/plans/PLAN_architecture-hardening.md:244`
- `docs/plans/PLAN_architecture-hardening.md:266`

Baseline evidence:

- `docs/architecture/reviews/2026-03-17-baseline.md` critical finding 5

Required revision:

The next plan revision should explicitly choose one of these paths:

- declare this hardening stage single-brain by design, remove misleading root
  parameters, and defer true root isolation to a later approved plan, or
- require root-scoped runtime/telemetry ownership now and name the modules and
  tests that must prove that isolation

---

## Advisory Notes

### A1. The overall structure is strong once the blocking decisions are pinned down

The objective, sequencing, review-rerun exit criteria, and the emphasis on test
ratchets are all good. The plan is also grounded in the architecture review in
the right way and is pointed at the real high-blast-radius seams.

### A2. Clean up the small status typo in the next revision

`docs/plans/PLAN_architecture-hardening.md:11` ends with `trail.f`.

---

## Verdict

Changes required.

Create a revised plan artifact that resolves the three blocking design choices
above before creating an approval artifact. This review artifact does not
approve the plan and does not authorize implementation.

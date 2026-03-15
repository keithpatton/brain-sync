# plan_docs-upgrade Review 1 — Governance Direction Good, Scope Needs Revision

**Reviewer:** Codex GPT-5
**Date:** 2026-03-15
**Reviewed documents:**
- `docs/plans/PLAN_docs-upgrade.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`
- `CLAUDE.md`
- `docs/brain-format/{RULES,SCHEMAS,VERSIONING,COMPATIBILITY,GLOSSARY,TEMPLATES}.md`
- Current repository state after the v23 implementation and full green test suite

**Purpose:** Review the documentation-governance plan after the v23 code
refactor so the next docs pass aligns with the actual Brain Format 1.0 /
runtime v23 baseline and gives agents accurate guidance.

---

## Verdict

The plan is **directionally correct** and should move forward, but it is
**not ready for approval as written**.

The main problem is not the governance idea. The hierarchy is sensible:
brain-format as specification, architecture as explanation, AGENTS as
repository practice, and README as user-facing guidance. The issue is that
the plan was drafted before the v23 implementation landed, so it
substantially underestimates how stale the core docs now are.

In particular:

- `ARCHITECTURE.md` needs a real v23 content rewrite, not a one-line pointer
  edit.
- `README.md` needs an explicit rewrite in scope, not just governance around
  it.
- The plan should say more clearly how Diataxis boundaries are enforced once
  the new doc set exists.

---

## Critical Issues

### C1. `ARCHITECTURE.md` rewrite is under-scoped

`PLAN_docs-upgrade.md` says the architecture doc needs only a minimal edit:
change the CLAUDE pointer and add a link to `docs/brain-format/`, with "no
other content changes."

That is no longer viable. The current architecture doc still describes
pre-v23 behavior in multiple places, including:

- top-level `insights/` ownership and mirroring
- sidecars at `insights/**/.regen-meta.json`
- manifests with `manifest_version`, `fetch_children`, and `child_path`
- the root-local `.sync-state.sqlite`
- `.brain-sync/version.json`
- `documents`, `relationships`, and `daemon_status` as part of the active
  runtime model
- global context involving `schemas/` and `insights/_core/`

These are not cosmetic drift. They are material contract errors. If the docs
plan is executed as written, `ARCHITECTURE.md` will remain an authoritative
explanation document that contradicts the now-implemented product.

**Recommendation:** Expand the plan so `docs/architecture/ARCHITECTURE.md`
gets a targeted v23 rewrite pass, at minimum for:

- system structure/storage model
- state authority
- managed-file identity
- attachment layout
- watcher/reconcile behavior
- MCP/query global context notes

### C2. `README.md` rewrite is missing from execution scope

The plan correctly says README should be the user guide, but it does not put a
README content rewrite in scope. The current README still documents the old
layout and commands, including:

- top-level `insights/` and `schemas/`
- root `.sync-state.sqlite`
- old state authority text
- old MCP/query assumptions
- the legacy `brain-sync migrate` command

This means the plan would improve governance while still leaving the primary
user-facing document materially wrong for new users.

There is also a Diataxis issue: the current README mixes user guide, reference,
architecture, and explanation. That is exactly the kind of ambiguity the plan
is trying to prevent.

**Recommendation:** Add README rewrite work explicitly to the plan, with a
clear target:

- keep README user-facing
- remove architecture-heavy internals
- move durable contract details to `docs/brain-format/`
- move deeper "why/how it works" material to `docs/architecture/`

---

## Significant Issues

### S1. The plan should define the post-restructure Diataxis boundaries more explicitly

The authority hierarchy is strong, but the content-mode boundaries are still a
little implicit. After the restructure, contributors should not need to guess
whether a topic belongs in README, architecture, or brain-format docs.

The cleanest mapping is:

- `docs/brain-format/` = reference/specification
- `docs/architecture/` = explanation
- `AGENTS.md` = operational repository rules and contributor practice
- `README.md` = user-facing tutorial/how-to entrypoint

The current plan gestures at this, but an explicit "what must not appear in
each layer" section would make it much easier for agents to maintain purity.

**Recommendation:** Add a short anti-mixing section to the plan, especially:

- README must not carry durable storage-spec detail
- architecture must not be used as the source of truth for on-disk schema
- AGENTS must not absorb architecture explanation
- brain-format docs must not become procedural contributor docs

### S2. The plan should acknowledge that `AGENTS.md` is the center of agent alignment, not the whole solution

Creating `AGENTS.md` is the right move and should happen. But the review of the
current repo shows that the agent-alignment problem is really two problems:

1. a missing neutral root instruction file (`AGENTS.md`)
2. stale core documents that agents will still read and trust

Without saying this explicitly, a future implementation could over-focus on the
`CLAUDE.md` -> `AGENTS.md` swap and under-invest in the architecture/README
corrections that matter just as much for agent behavior.

**Recommendation:** Add a short statement to the plan that the goal is both:

- neutral agent entrypoint alignment
- correction of stale high-authority docs that shape agent decisions

### S3. The plan should recommend sequencing the docs work after a code checkpoint

The repo is now at a strong implementation checkpoint: the v23 refactor is in
place and the full suite is green. That is an ideal point for a separate commit
before documentation restructuring starts.

This is not required for correctness, but it will make the docs work safer and
much easier to review. Otherwise a future branch risks mixing a large product
refactor with a docs governance rewrite in one review unit.

**Recommendation:** Add a note that execution should begin from a committed
v23 checkpoint, then perform the docs pass as a separate follow-up change.

---

## Moderate Issues

### M1. `docs/brain-format/README.md` should be framed as an index, not a second specification layer

The plan already proposes `docs/brain-format/README.md`, which is good.
It would help to say explicitly that this file is an index into the six
authoritative spec docs, not a parallel source of truth.

**Recommendation:** State that this README summarizes and links, but does not
normatively redefine any rule from the six spec documents.

### M2. The planning trail is already in place, so the "copy plan to project planning trail" step can be simplified

The plan says to copy itself into `docs/plans/PLAN_docs-upgrade.md`, but the
reviewed file is already there.

**Recommendation:** Remove or rewrite that step so the plan stays focused on
remaining execution work rather than already-completed trail setup.

---

## What the Plan Gets Right

1. Replacing `CLAUDE.md` with a thin pointer and moving durable repository
   rules into `AGENTS.md` is the right direction.
2. The proposed authority order is sensible and matches how contributors and
   agents actually use the docs.
3. Creating inbound links into `docs/brain-format/` is important and overdue.
4. Deduplicating state authority, dependency rules, and source adapter
   guidance out of multiple places is a healthy cleanup.
5. The intent to make governance self-documenting is exactly right for an
   agent-heavy repo.

---

## Recommended Plan Revision

Before approval, revise `PLAN_docs-upgrade.md` so it says:

1. Create `AGENTS.md` and reduce `CLAUDE.md` to a thin pointer.
2. Add `docs/brain-format/README.md` as a non-normative index.
3. Rewrite `docs/architecture/ARCHITECTURE.md` sections that still describe
   pre-v23 storage, identity, and runtime behavior.
4. Rewrite `README.md` to match the current user-facing v23 product shape.
5. State the intended Diataxis boundary for each document layer.
6. Recommend executing the docs work after a committed v23 code checkpoint.

---

## Approval Criteria For The Next Revision

I would approve the next revision if it:

- expands `ARCHITECTURE.md` from a pointer-only change to a scoped content
  alignment pass
- adds explicit README rewrite work
- states the document-boundary rules more concretely
- preserves the good governance and deduplication direction already in the plan

---

## Conclusion

This plan has the right destination, but its execution scope still reflects a
pre-implementation view of the repo.

The repo now has a real v23 baseline. The next docs plan revision should treat
that as a fact and update the core explanatory and user-facing documents
accordingly. Once that scope correction is made, the docs-upgrade work should
be straightforward to approve and execute.

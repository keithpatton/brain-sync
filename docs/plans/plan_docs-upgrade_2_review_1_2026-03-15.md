# plan_docs-upgrade_2 Review 1 — Approved For Execution

**Reviewer:** Codex GPT-5
**Date:** 2026-03-15
**Reviewed documents:**
- `docs/plans/plan_docs-upgrade_2_2026-03-15.md`
- `docs/plans/plan_docs-upgrade_review_1_2026-03-15.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`
- `CLAUDE.md`
- `docs/brain-format/{RULES,SCHEMAS,VERSIONING,COMPATIBILITY,GLOSSARY,TEMPLATES}.md`
- Current repository state after the committed v23 implementation checkpoint

**Purpose:** Validate whether the revised docs-upgrade plan resolves the
scope and governance issues identified in review 1 and is ready to execute as
the next follow-up to the v23 code migration.

---

## Verdict

**Approved for execution.**

This revision resolves the core problems from review 1:

- it explicitly starts from the committed v23 checkpoint
- it treats stale high-authority docs as a first-class problem
- it expands `ARCHITECTURE.md` from a pointer tweak into a scoped v23 rewrite
- it puts `README.md` rewrite work in scope
- it states the intended Diataxis boundaries clearly enough for agents and
  human contributors to follow

The plan is now aligned with the actual state of the repo and gives an
implementation agent enough direction to execute without guessing.

---

## Review-1 Resolution Status

All review-1 issues are resolved.

| Prior issue | Status | Notes |
|---|---|---|
| `ARCHITECTURE.md` rewrite under-scoped | Resolved | Section 4 now defines a real v23 alignment pass with explicit stale sections |
| `README.md` rewrite missing | Resolved | Section 5 adds a user-facing v23 alignment pass |
| Diataxis boundaries too implicit | Resolved | "Document Boundaries (Diataxis)" table is clear and actionable |
| `AGENTS.md` over-emphasized relative to stale docs | Resolved | Context now correctly frames this as both agent alignment and stale-doc correction |
| Docs work should follow a code checkpoint | Resolved | "Prerequisites" section states this directly |
| `docs/brain-format/README.md` needed non-normative framing | Resolved | Section 3 explicitly says it is a non-normative index |
| Planning trail step was stale | Resolved | Removed from the revised execution scope |

---

## What This Revision Gets Right

1. **The scope now matches the repo reality.** The plan correctly recognizes
   that the v23 code refactor is done but the docs still describe pre-v23
   behavior.

2. **The governance model is concrete rather than aspirational.** The
   authority hierarchy plus the "must contain / must not contain" table is the
   right level of precision for an agent-heavy repo.

3. **The architecture rewrite is focused without drifting into redesign.**
   Keeping `ARCHITECTURE.md` as explanation while correcting stale storage,
   identity, and state-model content is exactly the right balance.

4. **The README rewrite has the right user-facing intent.** It treats README
   as tutorial/how-to rather than a dumping ground for internals.

5. **The Diataxis relocation call is sensible.** The plan correctly identifies
   that the current "How it works" material in README is explanation content
   and should either move or be reduced to a short user-facing summary.

6. **The execution order is safe.** Starting from the committed v23 checkpoint
   keeps the docs pass reviewable and avoids mixing product migration work with
   governance cleanup.

---

## Minor Notes

These are not blockers and can be handled during execution.

### M1. README CLI/reference cleanup should include stale command surface details

The plan already captures the main stale README sections, but during
execution the implementer should also sweep the CLI reference and related user
examples for stale command surface details, especially any legacy wording tied
to pre-v23 behavior such as the old migration story or old top-level managed
paths.

This does not require a plan rewrite because it fits naturally inside the
README alignment pass.

### M2. Exact line references are useful now but should not constrain execution

The stale-section tables use current line numbers, which is helpful for review.
During execution, the implementer should treat them as targeting aids rather
than as a requirement to preserve document structure exactly.

Again, this is not blocking.

---

## Execution Confidence

**High confidence.**

The revised plan is specific enough to execute and narrow enough to remain
reviewable. It also leaves the authoritative brain-format spec where it
belongs: above architecture, AGENTS guidance, and README.

That is the right shape for the next change.

---

## Conclusion

This revision is ready.

The next step should be implementation of the docs pass itself:

1. create `AGENTS.md`
2. reduce `CLAUDE.md` to a thin pointer
3. add `docs/brain-format/README.md`
4. align `docs/architecture/ARCHITECTURE.md` to v23
5. align `README.md` to the current user-facing v23 product

Once that lands, the repository will have both a correct v23 runtime baseline
and a documentation hierarchy that helps agents stay aligned with it.

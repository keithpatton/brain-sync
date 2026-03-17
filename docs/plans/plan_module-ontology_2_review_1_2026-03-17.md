# plan_module-ontology_2 Review 1 - Approval Recommended

**Reviewer:** Codex GPT-5
**Date:** 2026-03-17
**Reviewed document:** `docs/plans/plan_module-ontology_2_2026-03-17.md`
**Prior review:** `docs/plans/plan_module-ontology_review_1_2026-03-17.md`
**Reviewed against:**
- `docs/plans/README.md`
- `AGENTS.md`
- `docs/architecture/ARCHITECTURE.md`
- current code in `src/brain_sync/layout.py`
- current code in `src/brain_sync/config.py`
- current code in `src/brain_sync/state.py`
- current code in `src/brain_sync/__main__.py`
- current code in `src/brain_sync/attachments.py`
- current code in `src/brain_sync/commands/placement.py`

**Purpose:** Review revision 2 of the module-ontology plan, with specific
attention to whether it resolves the blocking Review-1 issue around mixed
portable/runtime ownership in the current `layout.py`.

---

## Review-1 Resolution Status

The blocking issue from the prior review is resolved.

| ID | Prior issue | Resolution in revision 2 | Verified |
|---|---|---|---|
| F1 | The plan placed mixed runtime path ownership under `brain`, leaving the persistence-plane split architecturally inconsistent | Revision 2 makes the `layout.py` split explicit in the package map, package definitions, dependency rules, module classification, naming corrections, migration phase ordering, and acceptance criteria | Yes |

---

## Findings

No blocking findings.

Revision 2 closes the approval gap from Review 1 in the right way:

- it explicitly states that portable layout and version helpers belong in
  `brain.layout`
- it explicitly states that machine-local runtime path helpers such as
  `brain_sync_user_dir()`, `runtime_db_path()`, and `daemon_status_path()`
  belong under `runtime`
- it preserves the intended dependency rule that `runtime -> brain` is not the
  steady-state answer for path ownership
- it makes the split an implementation requirement in Phase 1 rather than an
  implied cleanup left for later

That correction matters because the current code really does have mixed
ownership in `layout.py`, and `config.py` already consumes the runtime-path
helpers. The revised plan now gives implementers one clear architectural
direction instead of leaving them to choose between contradictory outcomes.

The rest of the plan remains strong:

- `application/` is still the right replacement for `commands/`
- `regen`, `sync`, and `query` are now described as real subsystem packages
  with directional boundaries
- mixed modules such as `attachments.py` and `commands/placement.py` are still
  handled honestly
- the shim policy and migration phases still minimize long-lived conceptual
  drift

---

## Advisory Notes

### A1. Keep `runtime.paths` narrow

The new split is sound as long as `runtime.paths` remains limited to
machine-local path ownership and does not grow into a second generic layout
bucket.

### A2. Update architecture docs and guardrails early

Because the plan now names the split explicitly, implementation should update
`AGENTS.md` and `docs/architecture/ARCHITECTURE.md` early enough that new code
does not continue importing mixed layout helpers from legacy paths.

---

## Verdict

Approval recommended.

Create `plan_module-ontology_2_approved_<datetime>.md` before implementation.
This review artifact does not itself approve the plan.

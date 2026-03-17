# plan_module-ontology Review 1 - Revision Needed Before Approval

**Reviewer:** Codex GPT-5
**Date:** 2026-03-17
**Reviewed document:** `docs/plans/PLAN_module-ontology.md`
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

**Purpose:** Review the canonical module-ontology plan for architectural
soundness, with specific attention to whether the proposed package map,
dependency rules, and migration phases produce a coherent steady state for the
portable brain plane, the runtime plane, and the major subsystem boundaries.

---

## Findings

### F1. The plan still places runtime path ownership under `brain`, which conflicts with its own persistence-plane split

The plan's main direction is strong: `application/` is a clearer replacement
for `commands/`, `regen` and `sync` are correctly treated as subsystem
packages, and moving brain-root-specific filesystem helpers out of generic
utility space is the right architectural correction.

There is still one blocking contradiction in the steady-state package map:

- the plan says `brain` owns portable brain persistence and that machine-local
  runtime DB and daemon state are out of scope
- the plan says `runtime` owns runtime config and path resolution under the
  user config directory
- the allowed dependency list does not include `runtime -> brain`
- but the plan also classifies the current `layout.py` wholesale as
  `brain.layout`, even though the current module owns both portable layout
  helpers and runtime path helpers such as `brain_sync_user_dir()`,
  `runtime_db_path()`, and `daemon_status_path()`

That matters because the current `config.py` already consumes those runtime
path helpers. In the proposed steady state, implementers would have to do one
of three bad things:

1. keep runtime path semantics under `brain`, weakening the claimed
   brain-vs-runtime separation
2. make `runtime` depend on `brain`, despite the dependency table not naming
   that as an allowed direction
3. silently split `layout.py` during implementation without the plan naming
   that decision

For a plan that is meant to be normative about package ontology and dependency
direction, that is too central a gap to leave implicit.

The revision should resolve this explicitly in one of these ways:

- split today's `layout.py` into a portable `brain` layout module plus a
  runtime-owned path/config module, or
- move cross-plane path/version constants into a clearly neutral shared home
  and update the dependency rules accordingly, or
- explicitly allow and justify `runtime -> brain` for layout-only imports if
  that is the intended steady state

Until that choice is made in the plan itself, the persistence-plane boundary
is not fully coherent.

---

## Advisory Notes

### A1. The rest of the ontology is materially improved

Aside from the layout/path ownership issue, the plan is substantially clearer
than the current tree. The treatment of `commands/`, `regen`, `sync`,
`attachments.py`, `commands/placement.py`, and the top-level resource
directories is honest and directionally sound.

### A2. The migration phases are workable once the layout decision is explicit

The staged migration, shim policy, and test-impact discussion are all strong
enough to support implementation after the layout/runtime split is clarified in
the next revision.

---

## Verdict

Approval not recommended yet.

Create a revised plan artifact that resolves the `layout.py` / runtime-path
ownership contradiction before creating an approval artifact. This review
artifact does not itself approve the plan.

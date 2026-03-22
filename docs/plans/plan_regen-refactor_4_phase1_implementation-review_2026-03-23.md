# Implementation Review

Approved plan: `docs/plans/plan_regen-refactor_4_approved_2026-03-22T17-42-43.md`
Review mode: standard
Reviewed changes: working tree
Reviewer: Codex
Date: 2026-03-23

## Verdict

Pass with follow-ups.

Phase 1 is acceptable for continuation consideration into Phase 2, with no
blocking implementation defects found against the approved Phase 1 scope.
This review does not clear Phase 2 on behalf of the user.

## Findings

- None.

## Acceptance Criteria Coverage

- Met: `evaluate_folder_state()` now returns explicit single-node outcomes for
  missing path, no content, unchanged, structure only, content changed, and
  metadata backfill without invoking the backend
  (`src/brain_sync/regen/engine.py:1416`).
- Met: `regen_single_folder()` consumes the explicit evaluation result and
  threads a typed execution input with backend capabilities into execution
  rather than recomputing the folder classification inline
  (`src/brain_sync/regen/engine.py:1609`, `src/brain_sync/regen/engine.py:1631`,
  `src/brain_sync/regen/engine.py:1634`).
- Met: the bounded capability seam lives under `llm/` and defines prompt
  budget class, max prompt tokens, structured-output expectations, invocation
  mode, system prompt, tools mode, and prompt overhead
  (`src/brain_sync/llm/base.py:29`, `src/brain_sync/llm/base.py:38`,
  `src/brain_sync/llm/base.py:48`, `src/brain_sync/llm/base.py:66`,
  `src/brain_sync/llm/base.py:116`).
- Met: Sonnet 4.6 is explicitly covered as a 1M-context capability target,
  while the contract remains backend-agnostic through `resolve_backend_capabilities()`
  and `SupportsCapabilities` (`src/brain_sync/llm/base.py:83`,
  `src/brain_sync/llm/base.py:108`, `src/brain_sync/llm/base.py:123`).
- Met: cross-package production callers now import REGEN services through the
  package surface instead of reaching into `regen.engine` directly
  (`src/brain_sync/application/regen.py:8`, `src/brain_sync/sync/lifecycle.py:20`,
  `src/brain_sync/sync/reconcile.py:17`).
- Met: Phase 1 stayed in scope. Prompt budgeting remains on the existing
  conservative planner and was not silently moved to capability-driven policy
  (`src/brain_sync/regen/engine.py:164`, `src/brain_sync/regen/engine.py:1211`,
  `src/brain_sync/regen/engine.py:1300`, `src/brain_sync/regen/engine.py:1332`,
  `docs/regen/README.md:293`).
- Met: the known `skipped_backfill` walk-up versus wave mismatch remains
  unchanged and is documented as current behavior rather than silently altered
  in Phase 1 (`src/brain_sync/regen/engine.py:1600`, `docs/regen/README.md:347`).
- Met: the new Phase 1 unit coverage proves the required evaluation outcomes,
  the Sonnet 4.6 capability mapping, and execution use of backend invocation
  settings (`tests/unit/test_regen_phase1.py:66`, `tests/unit/test_regen_phase1.py:120`).

- Unproven: none within Phase 1 scope.

- Missed: none.

## Plan Drift And Unexpected Changes

- No material Phase 1 scope drift was found.
- The implementation did not silently take on Phase 2 budget policy or Phase 3
  propagation convergence.
- Documentation changes stayed in the explanatory homes identified by the plan:
  `docs/regen/README.md` and `docs/architecture/ARCHITECTURE.md`.

## Tests And Validation

- Reproduced the Phase 1 proof command:
  `python -m pytest tests/unit/test_regen_phase1.py -q` -> passed (`9 passed`).
- Reproduced the broader regression slice:
  `python -m pytest tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_reconcile_knowledge_tree.py tests/integration/test_regen_pipeline.py -q` -> passed (`216 passed`).
- Reproduced static validation:
  `ruff check src/brain_sync/llm src/brain_sync/regen src/brain_sync/application/regen.py tests/unit/test_regen_phase1.py` -> passed.
- Reproduced type validation:
  `pyright src/brain_sync/llm src/brain_sync/regen src/brain_sync/application/regen.py tests/unit/test_regen_phase1.py` -> passed.

## Docs And Notes

- `docs/plans/plan_regen-refactor_4_notes.md` contains a durable Phase 1
  checkpoint with changed surfaces, proof commands, findings, product-call
  status, and doc review coverage consistent with the approved plan.
- `docs/regen/README.md` now explains the explicit evaluation boundary, the
  bounded capability seam, and the intentionally unchanged `skipped_backfill`
  mismatch (`docs/regen/README.md:183`, `docs/regen/README.md:293`,
  `docs/regen/README.md:349`).
- `docs/architecture/ARCHITECTURE.md` now records the `llm/` ownership of the
  capability seam and the remaining engine decomposition debt
  (`docs/architecture/ARCHITECTURE.md:294`, `docs/architecture/ARCHITECTURE.md:459`).

## Recommended Next Action

- Seek explicit user clearance before starting Phase 2.
- Keep Phase 2 constrained to consuming the existing capability contract for
  budgeting policy rather than widening the contract or altering propagation
  semantics unless a later checkpoint reopens those choices.

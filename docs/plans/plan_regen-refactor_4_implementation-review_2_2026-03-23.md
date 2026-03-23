# Implementation Review

Approved plan: `docs/plans/plan_regen-refactor_4_approved_2026-03-22T17-42-43.md`
Review mode: standard
Reviewed changes: working tree follow-up after `docs/plans/plan_regen-refactor_4_implementation-review_2026-03-23.md`
Reviewer: Codex
Date: 2026-03-23

## Verdict

Pass.

The implemented REGEN refactor is acceptable as a whole against the approved
plan.

The prior blocking Phase 5 diagnostics-coherence issue and the prior
non-blocking fake-backend chunk-proof issue are both resolved in the current
working tree. The approved Phase 0-6 outcomes now read as one coherent system:
explicit evaluation and bounded capability seams, conservative
capability-aware prompt planning, shared propagation rules, the fixed final
summary/journal contract, observability closure on the approved runtime
surfaces, and an explicit scheduler/backend-readiness seam.

This review artifact does not approve any new work beyond the approved plan.

## Findings

- None. I did not identify a remaining implementation defect that blocks or
  materially weakens acceptance against the approved plan.

## Open Questions Or Assumptions

- Assumption: `path_reports[].chunk_count`, `chunked_file_count`, and
  `chunked_files` are intended to describe the latest terminal run for the
  path, while historical invocation totals remain in `path_reports[].token_cost`.
  The current implementation now behaves consistently with that reading.
- The documented prompt-body token-accounting caveat remains important: the
  baseline harness still measures application-assembled prompt-body telemetry,
  not provider-billed totals. I treated that as an accepted documented contract,
  not a defect.
- I reviewed the current working tree, including the uncommitted Phase 6 files
  and the updated notes/docs surfaces listed in `git status`.

## Acceptance Criteria Coverage

- Met: Phase 0 baseline and proof trail remain durable and reproducible,
  including the fictional corpus, repeatable collector, and explicit
  prompt-body telemetry scope.
- Met: Phase 1 still provides an explicit no-backend evaluation seam and a
  bounded backend-capability contract under `llm/`.
- Met: Phase 2 still consumes that contract, keeps long context selective by
  default, and preserves the approved inclusion priority of scaffold, then
  direct files, then child summaries.
- Met: Phase 3 still converges walk-up, full-tree waves, and queue waves onto
  the shared propagation contract, with the approved `skipped_rename`
  narrowing durably documented.
- Met: Phase 4 still enforces the fixed final summary/journal artifact contract
  for model-backed REGEN outputs.
- Met: Phase 5 now satisfies the approved observability closure on the existing
  runtime surfaces. Latest no-call rows in the compact report clear stale chunk
  metadata, and no new runtime table was introduced.
- Met: Phase 6 still provides an explicit queue scheduler-decision seam and a
  durable backend-readiness seam for context budget, concurrency, startup
  overhead, and structured-output reliability.
- Met: Documentation is aligned with the realized implementation across
  `docs/regen/README.md`, `docs/architecture/ARCHITECTURE.md`,
  `docs/RULES.md`, `docs/runtime/README.md`, `docs/runtime/SCHEMAS.md`, and
  the notes trail.

## Plan Drift And Unexpected Changes

- No material plan drift found in the updated working tree.
- I found no hidden reintroduction of Claude-specific prompt policy outside the
  bounded capability seam.
- Queue scheduling still depends on the explicit decision seam in
  `regen/topology.py`, not hidden `regen_path()` side effects.
- Compatibility and versioning implications still appear unchanged in practice;
  I found no undocumented runtime-schema or supported-config change that would
  require `docs/COMPATIBILITY.md` or `docs/VERSIONING.md` updates.

## Tests And Validation

- `python -m pytest tests/unit/test_regen_phase1.py tests/unit/test_regen_phase2.py tests/unit/test_regen_phase5.py tests/unit/test_regen_phase6.py -q` -> `23 passed`
- `python -m pytest tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/unit/test_daemon.py -q` -> `234 passed`
- `python -m pytest tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_phase2_budgeting.py tests/integration/test_regen_pipeline.py tests/integration/test_llm_fake.py -q` -> `22 passed`
- `python -m pytest tests/e2e/regressions/test_content_hash_redundant_regen.py -q` -> `1 passed`
- `python -m ruff check src/brain_sync/regen src/brain_sync/llm src/brain_sync/sync docs/regen/README.md docs/architecture/ARCHITECTURE.md docs/RULES.md` -> passed
- `python -m pyright src/brain_sync/regen src/brain_sync/llm src/brain_sync/sync` -> `0 errors, 0 warnings, 0 informations`
- Ad hoc churned-path diagnostics repro now confirms the prior Phase 5 blocker
  is fixed: after a chunked run followed by `skipped_unchanged`, the compact
  report now shows `chunk_count = 0`, `chunked_file_count = 0`, and
  `chunked_files = []` alongside the correct latest no-call reason.
- Ad hoc forced-chunk fake-backend repro now confirms the merge prompt embeds
  plain-text chunk summaries rather than leaked XML envelopes in the chunk
  section.

## Docs And Notes

- The updated notes trail now reads truthfully for the previously reviewed
  issues: the Phase 5 latest-run coherence claim is now consistent with current
  behavior, and the Phase 4 chunk-path caveat remains properly bounded.
- Final docs still tell the same story the code implements: observability stays
  on `operational_events` plus `token_events`, long context remains selective,
  and queue scheduling stays explicit and backend-agnostic at the policy seam.

## Change Summary

- The full approved REGEN refactor now hangs together cleanly as one system and
  is acceptably proved by unit, integration, e2e, static checks, and targeted
  reviewer repros.
- The remaining caveats are documented product/telemetry scope boundaries
  rather than implementation defects.

## Recommended Next Action

- Ship the approved Phase 0-6 refactor as implemented.

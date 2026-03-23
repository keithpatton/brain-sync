# Implementation Review

Approved plan: `docs/plans/plan_regen-refactor_4_approved_2026-03-22T17-42-43.md`
Review mode: standard
Reviewed changes: working tree
Reviewer: Codex
Date: 2026-03-23

## Verdict

Changes required.

The implemented REGEN refactor is not yet acceptable as a whole against the
approved plan.

Most of the approved Phase 0-6 outcomes are now realized coherently: the
evaluation/capability seam is explicit, prompt planning is capability-aware and
conservative, propagation is shared across walk-up and wave flows with the
approved `skipped_rename` narrowing, the final summary/journal contract is
explicit, the queue uses an explicit scheduler-decision seam, and the requested
unit/integration/e2e/static proof bundle passes in the current working tree.

The remaining blocking issue is in Phase 5 observability closure: the compact
diagnostic report is still not fully latest-run coherent for churned no-call
paths because stale chunk metadata survives into the latest path row. A second,
non-blocking proof-surface issue remains in the fake-backend chunk path.

This review artifact does not approve any new work beyond the approved plan.

## Findings

- [P1] `build_regen_diagnostic_report()` still carries stale chunk metadata into
  churned no-call path rows, so the Phase 5 report is not fully latest-run
  coherent. When the latest terminal event is a no-call outcome, the code
  clears prompt-planner fields but preserves prior `chunk_count`,
  `chunked_file_count`, and `chunked_files` by falling back to the older report
  values (`src/brain_sync/regen/diagnostics.py:124`,
  `src/brain_sync/regen/diagnostics.py:138`,
  `src/brain_sync/regen/diagnostics.py:140`). I reproduced this with a path
  that chunked once and then ended in `skipped_unchanged`: the compact report
  correctly showed `latest_outcome = "skipped_unchanged"` and
  `run_reason = "content_hash_unchanged"`, but it still reported
  `chunk_count = 1` and `chunked_files = ["report.md"]` from the earlier run.
  That leaves the report mixing latest-run no-call semantics with prior-run
  execution facts, which falls short of the approved Phase 5 closure and also
  makes the Phase 5 notes overclaim latest-run coherence
  (`docs/plans/plan_regen-refactor_4_notes.md:365`).

- [P2] The chunked proof surface is still mis-modeled by `FakeBackend`, because
  chunk calls ignore `is_chunk` and return the final summary/journal XML
  envelope instead of plain-text intermediate summaries. `regen_single_folder()`
  appends raw chunk outputs directly into `chunk_summaries_map`
  (`src/brain_sync/regen/engine.py:1279`,
  `src/brain_sync/regen/engine.py:1285`), and the merge prompt then embeds
  those strings verbatim (`src/brain_sync/regen/prompt_planner.py:661`,
  `src/brain_sync/regen/prompt_planner.py:666`). Meanwhile `FakeBackend`
  advertises the same XML output shape for normal successful calls regardless
  of chunk mode (`src/brain_sync/llm/fake.py:70`,
  `src/brain_sync/llm/fake.py:80`,
  `src/brain_sync/llm/fake.py:132`,
  `src/brain_sync/llm/fake.py:157`). I reproduced this with forced chunking:
  the final merge prompt contained raw `<summary>` tags from chunk calls even
  though final summary persistence still succeeded. This does not show a
  production artifact-contract failure, but it does leave chunked fake-backend
  proof weaker than the surrounding test surface suggests
  (`tests/integration/test_llm_fake.py:18`,
  `tests/integration/test_llm_fake.py:39`).

## Open Questions Or Assumptions

- Assumption: `path_reports[].chunk_count`, `chunked_file_count`, and
  `chunked_files` are intended to describe the latest terminal run for that
  path, not a historical aggregate, because historical chunk totals already
  live in `path_reports[].token_cost`.
- I reviewed the current working tree, including the uncommitted Phase 6 files
  and doc updates listed in `git status`.
- I treated the approved `skipped_rename` narrowing as captured plan intent,
  not drift, because it is durably recorded in the notes trail and reflected in
  the final docs.

## Acceptance Criteria Coverage

- Met: Phase 0 now has a durable fictional corpus, repeatable baseline
  collector, explicit prompt-body token-accounting caveat, and an implementation
  notes trail with per-phase checkpoints.
- Met: Phase 1 established explicit no-backend evaluation and a bounded
  backend-capability contract under `llm/`, and Phase 2 consumes that seam
  rather than inventing prompt-budget heuristics elsewhere.
- Met: Phase 2 moved prompt planning to capability-aware conservative budgets
  with the approved inclusion priority of scaffold, then direct files, then
  child summaries; long context remains a capability, not a blanket default.
- Met: Phase 3 converged single-path walk-up, wave execution, and queue wave
  execution onto a shared propagation rule set, with the user-cleared
  `skipped_rename` narrowing and sync-owned move propagation documented durably.
- Met: Phase 4 implemented the fixed final summary/journal contract for
  model-backed REGEN outputs, including strict parsing, journal-commit failure
  surfacing, and `skipped_similarity` journal retention.
- Met: Phase 5 stayed within the approved observability surfaces. No new runtime
  diagnostics table was introduced, and the runtime/docs surfaces remain
  `operational_events`, `token_events`, and `regen_locks`.
- Met: Phase 6 introduced an explicit queue scheduler-decision seam plus an
  extended backend-readiness seam with `max_concurrency`,
  `structured_output.reliability`, and `startup_overhead_class`.
- Met: Reproduced proof bundle in the current working tree:
  `22` targeted phase tests passed, `234` broader unit tests passed,
  `9` integration tests passed, `1` e2e regression passed, `ruff` passed, and
  `pyright` reported `0` errors.
- Missed: Phase 5 latest-run coherence is still incomplete for churned no-call
  paths because stale chunk metadata survives into the latest compact report
  row.
- Unproven: The chunked fake-backend path still does not prove a plain-text
  intermediate-summary contract separately from the final XML artifact
  contract.

## Plan Drift And Unexpected Changes

- No material scope drift found outside the findings above. The implementation
  did not reintroduce Claude-specific budgeting heuristics outside the bounded
  capability seam, did not add a new runtime diagnostics table, and did not
  hide queue scheduling behind `regen_path()` side effects again.
- The post-Phase-3 seam extraction folded into `regen/evaluation.py` and
  `regen/prompt_planner.py` is consistent with the notes trail and the final
  explanatory docs.
- Compatibility and versioning surfaces appear unchanged in practice; I found
  no undocumented runtime-schema or supported-config change that should have
  forced `docs/COMPATIBILITY.md` or `docs/VERSIONING.md` updates.

## Tests And Validation

- `python -m pytest tests/unit/test_regen_phase1.py tests/unit/test_regen_phase2.py tests/unit/test_regen_phase5.py tests/unit/test_regen_phase6.py -q` -> `22 passed`
- `python -m pytest tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/unit/test_daemon.py -q` -> `234 passed`
- `python -m pytest tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_phase2_budgeting.py tests/integration/test_regen_pipeline.py -q` -> `9 passed`
- `python -m pytest tests/e2e/regressions/test_content_hash_redundant_regen.py -q` -> `1 passed`
- `python -m ruff check src/brain_sync/regen src/brain_sync/llm src/brain_sync/sync docs/regen/README.md docs/architecture/ARCHITECTURE.md docs/RULES.md` -> passed
- `python -m pyright src/brain_sync/regen src/brain_sync/llm src/brain_sync/sync` -> `0 errors, 0 warnings, 0 informations`
- Ad hoc baseline rerun confirmed the intended Phase 3 and Phase 5 fixes that
  do hold today: `continued_to_parent == 0` for the targeted walk-up cases, and
  `product/atlas` / `legacy/metadata` now report the correct latest no-call
  `run_reason` and `evaluation_outcome`.
- Ad hoc churned-path diagnostics reproduction exposed the blocking P1 issue:
  after one chunked run followed by `skipped_unchanged`, the compact report
  still showed `chunk_count = 1`, `chunked_file_count = 1`, and
  `chunked_files = ["report.md"]`.
- Ad hoc forced-chunk fake-backend reproduction exposed the P2 issue: the final
  merge prompt still contained raw `<summary>` tags from chunk calls.

## Docs And Notes

- Final doc alignment is otherwise strong. `docs/regen/README.md`,
  `docs/architecture/ARCHITECTURE.md`, `docs/RULES.md`,
  `docs/runtime/README.md`, and `docs/runtime/SCHEMAS.md` now tell a coherent
  story about the evaluation boundary, bounded capability seam, conservative
  long-context budgeting, shared propagation contract, final artifact contract,
  and fixed observability surfaces.
- I found no doc drift around compatibility/versioning scope. The unchanged
  `docs/COMPATIBILITY.md` and `docs/VERSIONING.md` remain plausible because the
  implementation did not introduce a new runtime table or a new supported
  runtime config contract.
- The implementation notes are mostly durable and accurate now, including the
  Phase 2 prompt-body telemetry caveat and the Phase 4 chunk-proof caveat. The
  remaining mismatch is the Phase 5 claim of latest-run report coherence for
  churned no-call paths, which is too broad given P1
  (`docs/plans/plan_regen-refactor_4_notes.md:365`).

## Change Summary

- The refactor substantially improved REGEN structure and proof posture: the
  realized system now has cleaner seams, stronger docs, and better targeted
  tests than the pre-plan state.
- The remaining work is narrow and stays inside the approved plan: finish the
  Phase 5 diagnostics coherence fix and tighten the chunked fake-backend proof
  surface.

## Recommended Next Action

- Fix the compact diagnostics report so latest no-call rows clear or otherwise
  disambiguate stale chunk metadata.
- Narrow `FakeBackend` chunk behavior or add explicit chunk-path proof so the
  forced-chunk test surface models plain-text intermediates correctly.
- Rerun the proof bundle and repeat implementation review after those fixes.

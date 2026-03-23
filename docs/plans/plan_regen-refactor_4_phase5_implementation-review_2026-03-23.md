# Implementation Review

Approved plan: `docs/plans/plan_regen-refactor_4_approved_2026-03-22T17-42-43.md`
Review mode: standard
Reviewed changes: commit `d2ac67b` (`codex/phase5 regen observability closure`)
Reviewer: Codex
Date: 2026-03-23

## Verdict

Changes required.

Phase 5 is not acceptable for continuation consideration into Phase 6 yet.
This review artifact does not approve continuation.

## Findings

- [P1] The new compact diagnostics report is not latest-run coherent for churned
  no-call paths, so it can misstate why a path ran or skipped. In
  `build_regen_diagnostic_report()`, `run_reason`, `evaluation_outcome`, and
  prompt-planner fields are populated only from `regen.started`
  (`src/brain_sync/regen/diagnostics.py:100`,
  `src/brain_sync/regen/diagnostics.py:109`), while later terminal rows update
  only `latest_outcome`, `latest_reason`, and propagation fields
  (`src/brain_sync/regen/diagnostics.py:113`,
  `src/brain_sync/regen/diagnostics.py:129`). The engine does emit
  `evaluation_outcome` on no-call terminal paths such as `skipped_no_content`,
  `skipped_backfill`, `skipped_unchanged`, and `skipped_rename`
  (`src/brain_sync/regen/engine.py:1047`,
  `src/brain_sync/regen/engine.py:1055`,
  `src/brain_sync/regen/engine.py:1101`,
  `src/brain_sync/regen/engine.py:1109`,
  `src/brain_sync/regen/engine.py:1129`,
  `src/brain_sync/regen/engine.py:1137`,
  `src/brain_sync/regen/engine.py:1174`,
  `src/brain_sync/regen/engine.py:1182`), but the report drops that information
  for the latest no-call run. On an ad hoc rerun of the Phase 0 baseline report
  built by `tests/integration/regen_phase0_baseline.py`
  (`tests/integration/regen_phase0_baseline.py:442`,
  `tests/integration/regen_phase0_baseline.py:469`), `product/atlas` reported
  `latest_outcome = skipped_unchanged` and `latest_reason =
  content_hash_unchanged` while still carrying `run_reason = content_changed`
  and `evaluation_outcome = content_changed` from an earlier model-backed run,
  and `legacy/metadata` reported `latest_outcome = skipped_backfill` with both
  `run_reason` and `evaluation_outcome` left null. That breaks the approved
  requirement that the diagnostics seam explain why a path ran and why it was
  skipped, and it weakens the claim that the baseline report is comparison-ready
  without ad hoc interpretation.

- [P2] Queue terminal failure events collapse two different terminal causes into
  one typed reason, which weakens the Phase 5 failure-diagnosis contract. The
  queue distinguishes `lock_contention_deferred` from `retries_exhausted` in
  `outcome` and in the human-readable runtime error string
  (`src/brain_sync/regen/queue.py:250`,
  `src/brain_sync/regen/queue.py:255`), but the persisted `regen.failed` event
  always records `details.reason = "queue_retries_exhausted"` and
  `details.phase = "queue_retry"` for both branches
  (`src/brain_sync/regen/queue.py:262`,
  `src/brain_sync/regen/queue.py:274`). Under the fixed observability contract
  in `docs/RULES.md`, `operational_events` is supposed to be the durable
  semantic surface for why a path failed
  (`docs/RULES.md:112`,
  `docs/RULES.md:134`). As written, a queue terminal row cannot express the
  lock-contention case through its typed reason, so later diagnosis has to infer
  that distinction indirectly from `outcome` or the free-form error text.

## Acceptance Criteria Coverage

- Met: no new runtime table was added. The reviewed change stays within
  `operational_events`, `token_events`, `regen_locks`, and a read-only
  diagnostics seam over those surfaces
  (`src/brain_sync/regen/diagnostics.py:33`,
  `src/brain_sync/runtime/repository.py:2214`,
  `docs/RULES.md:112`,
  `docs/runtime/README.md:33`).
- Met: `operational_events` now carries typed REGEN semantic details for
  started, completed, and failed flows, and `token_events` remains the
  per-call cost/duration surface
  (`src/brain_sync/runtime/operational_events.py:62`,
  `src/brain_sync/runtime/operational_events.py:96`,
  `src/brain_sync/regen/engine.py:1232`,
  `src/brain_sync/regen/engine.py:1510`,
  `src/brain_sync/regen/engine.py:1377`,
  `docs/runtime/SCHEMAS.md:248`,
  `docs/runtime/SCHEMAS.md:299`).
- Met: the bounded terminal lock-release fix remains narrow. `_save_terminal_regen_lock()`
  still raises on a real conflicting owner and only tolerates the row-already-unowned
  and row-missing cases
  (`src/brain_sync/regen/engine.py:382`,
  `src/brain_sync/regen/engine.py:424`,
  `tests/unit/test_regen_phase5.py:159`,
  `tests/unit/test_regen_phase5.py:210`).
- Met: report-driven evidence claims about `prompt_component_coverage_count`,
  `terminal_reason_coverage_count`, `comparison_ready_keys`, and per-path token
  rollups for `research/annual` are reproducible from the baseline harness
  output rather than only from notes wording
  (`tests/integration/regen_phase0_baseline.py:442`,
  `tests/integration/test_regen_phase0_baseline.py:52`).
- Missed: the compact diagnostics report does not yet provide a coherent
  latest-run explanation for churned no-call paths, so the report seam is still
  weaker than the approved Phase 5 contract requires.

## Plan Drift And Unexpected Changes

- The implementation stayed inside the approved observability split. I found no
  evidence of a new runtime table, no attempt to promote logs to authority, and
  no drift into Phase 6 scheduler/backend-readiness behavior.
- The bounded follow-up fix for terminal ownership release is appropriately
  scoped and did not become a broad ownership workaround.

## Tests And Validation

- Reproduced the claimed proof bundle successfully:
  - `python -m ruff check src/brain_sync/regen src/brain_sync/runtime tests/unit/test_regen_phase5.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/unit/test_token_tracking.py tests/integration/regen_phase0_baseline.py tests/integration/test_regen_phase0_baseline.py` -> passed
  - `python -m pyright src/brain_sync/regen src/brain_sync/runtime tests/unit/test_regen_phase5.py tests/integration/regen_phase0_baseline.py` -> `0 errors, 0 warnings, 0 informations`
  - `python -m pytest tests/unit/test_regen_phase5.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/unit/test_token_tracking.py -q` -> `40 passed`
  - `python -m pytest tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/unit/test_token_tracking.py tests/unit/test_regen_phase5.py tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase2_budgeting.py -q` -> `252 passed`
- The recorded notes currently say `37 passed` and `249 passed`
  (`docs/plans/plan_regen-refactor_4_notes.md:227`,
  `docs/plans/plan_regen-refactor_4_notes.md:228`), but my rerun of those same
  commands produced higher passing counts. All commands passed, so this is
  evidence-trail drift rather than a product regression.
- Ad hoc report validation:
  - `python -c "from tests.integration.regen_phase0_baseline import run_phase0_baseline; ..."` confirmed `prompt_component_coverage_count = 8`, `terminal_reason_coverage_count = 11`, the documented `comparison_ready_keys`, and per-path token rollups for `research/annual`.
  - That same report run also reproduced the P1 inconsistency on churned
    no-call paths described above.

## Docs And Notes

- `docs/RULES.md` is the right normative home for the fixed observability split
  and does not overclaim schema authority
  (`docs/RULES.md:112`,
  `docs/RULES.md:134`).
- `docs/runtime/README.md`, `docs/runtime/SCHEMAS.md`, `docs/regen/README.md`,
  and `docs/architecture/ARCHITECTURE.md` are directionally aligned with the
  intended Phase 5 design
  (`docs/runtime/README.md:33`,
  `docs/runtime/SCHEMAS.md:248`,
  `docs/regen/README.md:511`,
  `docs/architecture/ARCHITECTURE.md:556`).
- Those docs currently overstate the practical usefulness of the compact report
  for latest-run diagnosis because the current implementation still mixes older
  `regen.started` data with newer no-call terminal rows in churned path reports.

## Recommended Next Action

- Fix the report seam so a per-path row stays coherent when the latest terminal
  event is a no-call skip or cleanup path, then rerun the Phase 5 proof bundle
  and regenerate the report-driven evidence.
- Tighten queue failure typing so `lock_contention_deferred` and
  `retries_exhausted` remain distinguishable in the typed `regen.failed`
  details, not only in `outcome` or free-form text.
- Re-review Phase 5 after those issues are resolved. Do not treat this artifact
  as Phase 6 clearance.

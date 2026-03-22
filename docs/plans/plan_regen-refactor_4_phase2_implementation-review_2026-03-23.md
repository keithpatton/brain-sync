# Implementation Review

Approved plan: `docs/plans/plan_regen-refactor_4_approved_2026-03-22T17-42-43.md`
Review mode: standard
Reviewed changes: working tree
Reviewer: Codex
Date: 2026-03-23

## Verdict

Pass with follow-ups.

Phase 2 is acceptable for continuation consideration into Phase 3, with one
evidence-wording caveat recorded below. This review does not clear Phase 3 on
behalf of the user.

## Findings

- [P2] The Phase 2 checkpoint overstates the large-leaf token-burn delta as if
  it were provider-billed input, but the baseline harness still discards
  `system_prompt` and reports `input_tokens=len(prompt)//4`. The implementation
  evidence clearly proves the stronger claim, which is chunk/invocation and
  latency reduction, but the wording in the notes currently makes the `970`
  token delta look more authoritative than the harness supports. Tighten the
  notes so this comparison is described as prompt-body-token telemetry from the
  deterministic evaluation backend, not full billed-provider input
  (`docs/plans/plan_regen-refactor_4_notes.md:127`,
  `tests/integration/regen_phase0_baseline.py:87`,
  `tests/integration/regen_phase0_baseline.py:133`).

## Open Questions Or Assumptions

- I reviewed the current working tree as the completed Phase 2 implementation.
- I treated Sonnet 4.6 as the primary target model for this phase, per the
  approved notes trail and the explicit Phase 2 integration proof.
- I treated the current fixed effective envelopes (`160k` / `320k`) as an
  intentional Phase 2 policy choice, not a hidden Phase 6 backend-readiness
  redesign.

## Acceptance Criteria Coverage

- Met: prompt assembly now consumes the Phase 1 capability seam through
  `_effective_prompt_budget()` and the capability object threaded into
  `_build_prompt()` / `_build_prompt_from_chunks()`, rather than using
  model-string heuristics inside prompt assembly
  (`src/brain_sync/regen/engine.py:1169`,
  `src/brain_sync/regen/engine.py:1419`,
  `src/brain_sync/regen/engine.py:1957`,
  `src/brain_sync/regen/engine.py:2040`).
- Met: long context is treated as a capability with selective headroom, not as
  a blanket `1M` default. Current `extended_1m` models get a `320k` effective
  envelope, standard-capability models get `160k`, and the legacy override hook
  remains available for bounded-budget tests
  (`src/brain_sync/regen/engine.py:164`,
  `src/brain_sync/regen/engine.py:1169`,
  `tests/unit/test_regen_phase2.py:31`,
  `tests/unit/test_regen_phase2.py:48`).
- Met: the approved inclusion order is implemented as fixed scaffold first,
  direct files second, child summaries third. Direct-file packing happens
  before child-summary packing, and omitted child summaries plus deferred files
  are surfaced in prompt diagnostics
  (`src/brain_sync/regen/engine.py:1185`,
  `src/brain_sync/regen/engine.py:1232`,
  `src/brain_sync/regen/engine.py:1467`,
  `src/brain_sync/regen/engine.py:1494`,
  `src/brain_sync/regen/engine.py:1529`,
  `tests/unit/test_regen_phase2.py:69`).
- Met: chunking now happens because the remaining effective direct-file budget
  cannot inline a file, not merely because the file exceeded
  `CHUNK_TARGET_CHARS`. The large-leaf Sonnet 4.6 integration proof now stays
  in one regen call
  (`src/brain_sync/regen/engine.py:1244`,
  `tests/integration/test_regen_phase2_budgeting.py:16`).
- Met: Phase 2 did not silently implement later-phase propagation,
  summary/journal contract, or observability-contract changes. The changed
  seams stay confined to prompt assembly, diagnostics, baseline measurement, and
  explanatory docs. I found no Phase 3 propagation-matrix convergence work, no
  Phase 4 artifact-contract changes, and no Phase 5 telemetry-surface contract
  changes in the reviewed diff.
- Unproven: no blocking unproven acceptance criteria remain within Phase 2
  scope.
- Missed: none in the implementation itself; the only issue is the evidence
  wording caveat in the notes.

## Plan Drift And Unexpected Changes

- No material plan drift was found. The implementation stays within the Phase 2
  prompt-budgeting scope and does not widen the capability contract.
- Existing tests that used to imply "large file means chunking" were updated to
  assert budget-driven chunking instead, which matches the approved Phase 2
  behavioral change rather than weakening the contract
  (`tests/unit/test_regen.py:1774`,
  `tests/unit/test_regen.py:1823`,
  `tests/unit/test_regen.py:1868`).
- `src/brain_sync/regen/engine.py` is still a large seam, but the new planner
  helpers and diagnostics do improve local explainability without splitting the
  module prematurely.

## Tests And Validation

- Reproduced the claimed Phase 2 proof commands successfully:
  - `python -m pytest tests/unit/test_regen_phase2.py tests/integration/test_regen_phase2_budgeting.py -q` -> `4 passed`
  - `ruff check src/brain_sync/regen/engine.py tests/unit/test_regen_phase2.py tests/integration/test_regen_phase2_budgeting.py tests/integration/regen_phase0_baseline.py` -> passed
  - `pyright src/brain_sync/regen/engine.py tests/unit/test_regen_phase2.py tests/integration/test_regen_phase2_budgeting.py tests/integration/regen_phase0_baseline.py` -> passed
  - `python -m pytest tests/unit/test_regen.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase0_baseline.py -q` -> `185 passed`
  - `python -m pytest tests/unit/test_regen_phase2.py tests/integration/test_regen_phase2_budgeting.py tests/unit/test_regen.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase0_baseline.py -q` -> `189 passed`
- Reproduced the current baseline harness:
  - `python -c "import json; from tests.integration.regen_phase0_baseline import run_phase0_baseline; print(json.dumps(run_phase0_baseline(), sort_keys=True))"`
- The current baseline output matches the Phase 2 claims that matter most:
  - `research/annual` now runs in `1` invocation with `0` deferred files
  - `research/annual` prompt diagnostics report `extended_1m` with a `320000`
    effective prompt budget and `157253` estimated prompt tokens
  - the quality anchor checks still pass for `_core`, `product/atlas`,
    `programs/ops`, and `research/annual`
- The small large-leaf token delta is expected under the current harness:
  chunk fan-out collapsed, but the single-pass direct prompt is much larger and
  the deterministic backend only counts prompt-body chars, so the measured
  improvement mostly shows up as invocation-count and latency reduction rather
  than dramatic token reduction.

## Docs And Notes

- `docs/regen/README.md` and `docs/architecture/ARCHITECTURE.md` were updated
  in the right explanatory homes for the Phase 2 behavior change
  (`docs/regen/README.md:266`,
  `docs/regen/README.md:275`,
  `docs/regen/README.md:286`,
  `docs/architecture/ARCHITECTURE.md:303`).
- The notes file contains the required durable Phase 2 checkpoint with changed
  surfaces, proof commands, metrics, doc review coverage, and a non-self-
  approving next-action entry.
- The notes should be clarified so the token delta is not read as a stronger
  provider-cost claim than the Phase 0 harness actually measures.

## Change Summary

- Prompt planning is now capability-aware, conservative by default, and aligned
  to the user-cleared priority of scaffold, then direct files, then child
  summaries.
- The strongest demonstrated Phase 2 improvement is elimination of unnecessary
  chunk-and-merge on the large-leaf Sonnet 4.6 case, with preserved anchor
  quality and much lower invocation fan-out.

## Recommended Next Action

- Phase 2 is acceptable for continuation consideration into Phase 3.
- Do not treat this review artifact as Phase 3 clearance.
- Carry the token-telemetry caveat forward in any Phase 3+ discussion that
  compares cost claims against the Phase 0 baseline harness.

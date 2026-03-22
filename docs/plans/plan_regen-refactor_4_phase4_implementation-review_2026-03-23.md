# Implementation Review

Approved plan: `docs/plans/plan_regen-refactor_4_approved_2026-03-22T17-42-43.md`
Review mode: standard
Reviewed changes: working tree
Reviewer: Codex
Date: 2026-03-23

## Verdict

Pass with follow-ups.

Phase 4 is acceptable for continuation consideration into Phase 5, with one
caveat around chunk-path proof and fake-backend contract alignment. This review
does not clear Phase 5 on behalf of the user.

## Findings

- [P2] The Phase 4 fake-backend alignment claim is too broad because
  chunk-and-merge still consumes plain-text intermediate chunk summaries, but
  `FakeBackend` now returns the final XML envelope for those chunk calls too.
  `regen_single_folder()` appends raw `chunk_result.output.strip()` into the
  merge prompt, and `build_prompt_from_chunks()` embeds those strings directly,
  so forced chunking with `FakeBackend(mode="stable")` feeds raw
  `<summary>...</summary><journal>...</journal>` text back into the merge
  prompt instead of plain chunk summaries
  (`src/brain_sync/regen/engine.py:1169`,
  `src/brain_sync/regen/engine.py:1188`,
  `src/brain_sync/regen/prompt_planner.py:651`,
  `src/brain_sync/regen/prompt_planner.py:666`,
  `src/brain_sync/llm/fake.py:127`,
  `src/brain_sync/llm/fake.py:165`).
  The notes currently say this alignment means integration coverage exercises
  the same artifact shape as production REGEN, but the current proof bundle
  does not actually cover the chunk path under that contract
  (`docs/plans/plan_regen-refactor_4_notes.md:122`,
  `docs/plans/plan_regen-refactor_4_notes.md:130`,
  `tests/integration/test_llm_fake.py:33`,
  `tests/unit/test_regen.py:1930`).
  I confirmed this with an ad hoc forced-chunking run using
  `FakeBackend(mode="stable")`: the final merge prompt contained raw
  `<summary>` tags from chunk calls. Final summary persistence still works, so
  this is a proof/contract-alignment defect rather than a demonstrated final
  artifact corruption, but it leaves the chunked path mis-modeled and
  unproven.

## Open Questions Or Assumptions

- I reviewed the current working tree as the completed Phase 4 implementation.
- I treated the fixed Phase 4 artifact contract as applying to the final
  model-backed REGEN output, not to intermediate chunk-summary calls. The
  approved plan and updated docs describe chunk summaries as merge inputs, not
  as durable summary/journal artifacts
  (`docs/plans/plan_regen-refactor_4_approved_2026-03-22T17-42-43.md`,
  `docs/regen/README.md:318`,
  `docs/regen/README.md:346`).
- I treated the recorded no-rollback nuance for journal-append failure as
  acceptable under the approved contract because the plan required failure
  surfacing, not transactional rollback, and the notes and docs now say that
  clearly enough
  (`docs/plans/plan_regen-refactor_4_notes.md:147`,
  `docs/plans/plan_regen-refactor_4_notes.md:148`,
  `docs/regen/README.md:152`,
  `docs/regen/README.md:362`).
- I treated the distinct operational-event outcomes `failed`,
  `failed_artifact_contract`, and `failed_artifact_commit` as an observability
  taxonomy detail for later Phase 5 tightening rather than a missing Phase 4
  documentation obligation. The code distinction is real today
  (`src/brain_sync/regen/engine.py:1250`,
  `src/brain_sync/regen/engine.py:1278`,
  `src/brain_sync/regen/engine.py:1367`).

## Acceptance Criteria Coverage

- Met: Phase 4 introduced an explicit artifact seam in
  `src/brain_sync/regen/artifacts.py` with `ParsedArtifacts`,
  `ArtifactCommitPlan`, strict XML-envelope parsing, and repository-routed
  journal append handling
  (`src/brain_sync/regen/artifacts.py:28`,
  `src/brain_sync/regen/artifacts.py:36`,
  `src/brain_sync/regen/artifacts.py:46`,
  `src/brain_sync/regen/artifacts.py:62`).
- Met: main execution now consumes that artifact model directly rather than
  relying on tuple parsing alone. `regen_single_folder()` parses into
  `ParsedArtifacts`, then commits an `ArtifactCommitPlan` after similarity
  handling
  (`src/brain_sync/regen/engine.py:1256`,
  `src/brain_sync/regen/engine.py:1258`,
  `src/brain_sync/regen/engine.py:1324`,
  `src/brain_sync/regen/engine.py:1353`).
- Met: plain-text fallback was intentionally removed. Journal-only output,
  malformed XML, and text outside the required envelope now fail at the
  artifact boundary with `failed_artifact_contract`, and the tests prove those
  cases do not create new summary or journal files
  (`src/brain_sync/regen/artifacts.py:48`,
  `src/brain_sync/regen/artifacts.py:56`,
  `src/brain_sync/regen/engine.py:1259`,
  `src/brain_sync/regen/engine.py:1278`,
  `tests/unit/test_regen.py:1686`,
  `tests/unit/test_regen.py:1702`,
  `tests/unit/test_regen.py:1721`,
  `tests/unit/test_regen.py:2163`).
- Met: the fixed summary/journal contract is preserved in successful
  model-backed REGEN. Summary remains required, journal remains optional, and a
  valid journal may still be committed on `skipped_similarity`
  (`src/brain_sync/regen/artifacts.py:54`,
  `src/brain_sync/regen/engine.py:1316`,
  `src/brain_sync/regen/engine.py:1334`,
  `tests/unit/test_regen.py:2233`).
- Met: `skipped_unchanged` remains a no-call success path and does not depend
  on the artifact seam or synthesize journal output
  (`src/brain_sync/regen/engine.py:1074`,
  `tests/integration/test_regen_pipeline.py:43`,
  `tests/integration/test_regen_pipeline.py:58`).
- Met: journal commit failure is surfaced as a run failure instead of being
  silently ignored, and runtime success finalization now happens only after the
  summary write and any journal append both succeed
  (`src/brain_sync/regen/engine.py:317`,
  `src/brain_sync/regen/engine.py:334`,
  `src/brain_sync/regen/engine.py:348`,
  `tests/unit/test_regen.py:2301`).
- Met: no new runtime diagnostics table was introduced. The reviewed diff stays
  within REGEN, fake-backend, tests, and explanatory docs, and Phase 4
  correctly left runtime schema/versioning/compatibility docs unchanged.
- Unproven: chunked-flow proof under the stricter fake-backend envelope remains
  incomplete for the reason in the finding above.
- Missed: no blocking acceptance criterion was missed.

## Plan Drift And Unexpected Changes

- The implementation stayed within the approved Phase 4 scope: explicit
  artifact modeling, strict contract enforcement, journal-failure surfacing,
  fake-backend updates, and explanatory doc alignment.
- I did not find accidental tightening of no-call paths such as
  `skipped_unchanged`, cleanup, or other non-LLM branches. The artifact seam is
  entered only after a successful backend call.
- The only material caveat is that fake-backend XML alignment currently reaches
  intermediate chunk-summary calls as well as final REGEN outputs, which makes
  the proof wording stronger than the current chunk-path evidence supports.

## Tests And Validation

- Reproduced the claimed proof bundle successfully:
  - `python -m ruff check src/brain_sync/regen/artifacts.py src/brain_sync/regen/engine.py src/brain_sync/llm/fake.py tests/unit/test_regen.py tests/integration/test_llm_fake.py tests/integration/test_regen_pipeline.py docs/regen/README.md docs/architecture/ARCHITECTURE.md` -> passed
  - `pyright src/brain_sync/regen/artifacts.py src/brain_sync/regen/engine.py src/brain_sync/llm/fake.py tests/unit/test_regen.py tests/integration/test_llm_fake.py tests/integration/test_regen_pipeline.py` -> passed
  - `python -m pytest tests/unit/test_regen.py -q` -> `182 passed`
  - `python -m pytest tests/integration/test_llm_fake.py tests/integration/test_regen_pipeline.py -q` -> `19 passed`
  - `python -m pytest tests/unit/test_regen.py tests/integration/test_llm_fake.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_phase2_budgeting.py -q` -> `203 passed`
- Additional ad hoc validation uncovered the finding above:
  - forced chunking with `FakeBackend(mode="stable")` produced a successful
    final summary, but the final merge prompt contained raw `<summary>` tags
    from intermediate chunk calls

## Docs And Notes

- `docs/regen/README.md` now explains the final artifact contract accurately:
  fixed XML envelope, no plain-text fallback, similarity-skip journal behavior,
  ordered commit semantics, and surfaced journal-commit failures
  (`docs/regen/README.md:149`,
  `docs/regen/README.md:152`,
  `docs/regen/README.md:351`,
  `docs/regen/README.md:362`,
  `docs/regen/README.md:372`).
- `docs/architecture/ARCHITECTURE.md` mentions the new seam accurately and does
  not overclaim a fully decomposed engine
  (`docs/architecture/ARCHITECTURE.md:103`,
  `docs/architecture/ARCHITECTURE.md:107`,
  `docs/architecture/ARCHITECTURE.md:469`).
- The Phase 4 notes capture the important no-rollback nuance clearly enough for
  later reviewers and maintainers
  (`docs/plans/plan_regen-refactor_4_notes.md:147`,
  `docs/plans/plan_regen-refactor_4_notes.md:148`).
- No Phase 4 artifact rule needs promotion into `docs/RULES.md`. The
  summary/journal contract is REGEN-specific subsystem behavior, not a
  cross-cutting repository-wide invariant or precedence rule.
- The notes should not claim that fake-backend XML alignment already gives
  production-equivalent artifact-shape coverage for chunked flow. That part of
  the evidence is currently narrower than the wording suggests.

## Change Summary

- Phase 4 successfully extracted a clearer artifact seam and hardened the final
  summary/journal contract at the execution boundary.
- The remaining caveat is about proof and test-double alignment for chunked
  flow, not about the main final-artifact contract for normal successful REGEN.

## Recommended Next Action

- Phase 4 is acceptable for continuation consideration into Phase 5.
- Do not treat this review artifact as Phase 5 clearance.
- Before relying on the Phase 4 fake-backend proof for later chunk-path or
  artifact-specific work, either narrow the wording to final-output contract
  coverage or add explicit chunk-path coverage that matches the intended
  intermediate-output behavior.

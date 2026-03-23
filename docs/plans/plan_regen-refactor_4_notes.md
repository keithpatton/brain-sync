# Plan regen-refactor 4 Implementation Notes

2026-03-22T17:54:44+13:00
Phase: Phase 0 - baseline, corpus, and decision baseline
Change: Established a fictional REGEN Phase 0 corpus plus a repeatable baseline collector and integration proof for the approved refactor plan.
Reason: Phase 0 required durable baseline evidence, a quality guard strong enough to catch obvious factual loss, and an explicit documentation impact inventory before structural refactor work begins.
Status: Implemented.

Changed code/doc surfaces:

- `tests/integration/regen_phase0_baseline.py`
- `tests/integration/test_regen_phase0_baseline.py`
- `docs/plans/plan_regen-refactor_4_notes.md`

Tests run and results:

- `ruff check tests/integration/regen_phase0_baseline.py tests/integration/test_regen_phase0_baseline.py` -> passed
- `pyright tests/integration/regen_phase0_baseline.py tests/integration/test_regen_phase0_baseline.py` -> passed
- `python -m pytest tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_pipeline.py -q` -> 8 passed
- `python - <<'PY' ... run_phase0_baseline() ... PY` -> baseline collector completed and emitted stable JSON evidence used below

Baseline-versus-current metrics relevant to the phase:

- Harness coverage before/after: before this phase there was no dedicated REGEN Phase 0 corpus, no repeatable baseline collector, and no phase-specific proof; current state has 6 required fictional corpus shapes, 1 standalone baseline collector, and 1 integration proof file covering the corpus and metrics contract.
- Current token usage per node on the Phase 0 corpus, measured as application-assembled prompt-body telemetry from the deterministic evaluation backend and excluding backend system-prompt content, backend invocation framing, and provider-billed-token adjustments: `research/annual` 118961 total tokens across 5 invocations (4 chunk + 1 merge), `programs/ops` 8371, `_core` 1319, `product/atlas` 1271, `operations` 1251, `legacy` 1251, `operations/rename-demo` 1220.
- Current chunked vs non-chunked run counts: 1 chunked node (`research/annual`), 6 non-chunked nodes (`_core`, `product/atlas`, `programs/ops`, `operations/rename-demo`, `operations`, `legacy`).
- Current prompt size by major component: `_core` total ~1723 tokens with instructions ~1329 and global context ~112; `product/atlas` total ~1659 with instructions ~1329; `programs/ops` total ~11095 with child summaries ~9444 and instructions ~1329; `research/annual` total ~1745 with 1 deferred file and instructions ~1329.
- Current latency per node on the collector run: `research/annual` 68 ms total across 5 invocations; `programs/ops` 14 ms; `operations/rename-demo` 11 ms; `legacy` 5 ms; `operations` 8 ms; `_core` 7 ms; `product/atlas` 9 ms.
- Current skip reason frequency on follow-up runs: `skipped_unchanged` 3, `skipped_rename` 1, `skipped_backfill` 1.
- Current ancestor propagation frequency on targeted walk-up follow-ups: 2 of 3 cases continued to a parent (`rename_walkup`, `backfill_walkup`) while 1 of 3 stopped at the leaf (`small_leaf_unchanged`).

Evidence bundle:

- The collector exercised the approved Phase 0 shape matrix: small leaf (`product/atlas`), large leaf (`research/annual`), wide parent (`programs/ops`), `_core`, rename-only churn (`operations/rename-demo`), and metadata-only/backfill (`legacy/metadata`).
- The quality harness used explicit `ANCHOR:` markers plus an evaluation backend that echoes anchors through chunk and merge prompts; all required anchor checks passed for `_core`, `product/atlas`, `programs/ops`, and `research/annual`.
- The before/after improvement claimed in this phase is measurement durability, not runtime behavior: before Phase 0 there was no dedicated corpus/baseline artifact; after Phase 0 the repository can reproduce the same corpus, metrics, and anchor checks through the new collector and test.

Findings summary:

- The planned phase ordering still looks correct: prompt budgeting and dirty-propagation behavior remain the highest-leverage next targets.
- The large-leaf case confirms current chunk fallback is active and expensive under the fixed budget: `research/annual` alone consumed 118961 prompt-body tokens across 5 calls in the deterministic baseline harness.
- The wide-parent case shows child summaries are already a larger prompt cost than direct files on representative parent nodes: `programs/ops` spent ~9444 prompt tokens on child summaries versus ~57 on direct files.
- The instructions block is a dominant fixed prompt cost on every measured node at ~1329 estimated tokens, including small leaves and `_core`.
- Rename-only and metadata-backfill follow-ups both continued one level upward in walk-up mode and reached an unchanged parent, which is a concrete false-positive ancestor-evaluation driver.

Product calls surfaced:

- `skipped_backfill` still continues upward in walk-up mode even though wave propagation excludes backfill; this mismatch needs an explicit Phase 1 decision instead of implementer guesswork.
- The current fixed prompt envelope did not truncate the wide-parent case here, but the data already shows child summaries can dominate prompt cost; Phase 2 should treat long context as selective headroom rather than blanket default.

Regressions or ambiguous results:

- No regressions were found in the targeted Phase 0 integration slice.
- The current walk-up versus wave asymmetry around `skipped_backfill` remains an intentional ambiguity in the codebase rather than a resolved product rule.

Unresolved product decisions:

- Whether `skipped_backfill` should keep walking upward or converge to the wave propagation contract.
- Whether future prompt-budget expansion should primarily buy more child-summary headroom, more direct-file headroom, or both.

Docs reviewed:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`

Docs changed:

- `docs/plans/plan_regen-refactor_4_notes.md`

Docs reviewed but intentionally unchanged:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`

Recommended next action:

- proceed unchanged

## Plan completion marker — 2026-03-23

Completion status:

- The approved `plan_regen-refactor_4` implementation is complete through Phase 6.
- The whole-plan implementation review follow-up is complete.
- The latest whole-plan review outcome reported no findings and accepted the realized implementation against the approved plan.

Final durable state:

- All approved phases were implemented with checkpointed notes.
- Required implementation review artifacts now exist for the realized work.
- The current notes trail records the final whole-plan follow-up fixes for diagnostics latest-run coherence and fake-backend chunk proof alignment.

Recommended next action:

- plan fully completed

## Final whole-plan review follow-up — 2026-03-23

Purpose:

- Address the blocking whole-plan implementation review finding that Phase 5 diagnostics still leaked stale chunk metadata into latest-run no-call path reports.
- Tighten the fake-backend chunk proof surface so chunk intermediates match the intended plain-text merge-input contract.

Changed code/doc surfaces:

- `src/brain_sync/regen/diagnostics.py`
- `src/brain_sync/llm/fake.py`
- `tests/unit/test_regen_phase5.py`
- `tests/integration/test_llm_fake.py`
- `docs/plans/plan_regen-refactor_4_notes.md`

Tests run and results:

- `python -m pytest tests/unit/test_regen_phase5.py tests/integration/test_llm_fake.py tests/integration/test_regen_phase0_baseline.py -q` -> 21 passed
- `python -m ruff check src/brain_sync/regen/diagnostics.py src/brain_sync/llm/fake.py tests/unit/test_regen_phase5.py tests/integration/test_llm_fake.py tests/integration/test_regen_phase0_baseline.py` -> passed
- `python -m pyright src/brain_sync/regen/diagnostics.py src/brain_sync/llm/fake.py tests/unit/test_regen_phase5.py tests/integration/test_llm_fake.py` -> passed
- `python -m pytest tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_regen_phase5.py tests/unit/test_regen_phase6.py tests/unit/test_runtime_operational_events.py tests/integration/test_llm_fake.py tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_pipeline.py -q` -> 252 passed
- `python -m pyright src/brain_sync/regen src/brain_sync/llm tests/unit/test_regen_phase5.py tests/unit/test_regen_phase6.py tests/integration/test_llm_fake.py` -> passed

Baseline-versus-current metrics relevant to the follow-up:

- Latest-run chunk metadata coherence before/after: before this follow-up a path that chunked on an earlier run and then ended in a no-call latest outcome could still report prior-run `chunk_count`, `chunked_file_count`, and `chunked_files`; current state clears all 3 latest-run chunk fields to `0`, `0`, and `[]` for latest no-call outcomes.
- Fake chunk proof shape before/after: before this follow-up `FakeBackend` returned the final XML envelope even when `is_chunk=True`, so merge prompts could contain raw `<summary>` tags from chunk calls; current state returns plain-text chunk summaries for chunk invocations while preserving XML output for final calls.

Evidence bundle:

- `tests/unit/test_regen_phase5.py` now proves a chunked path followed by a latest `skipped_unchanged` run clears stale latest-run chunk metadata in the diagnostics report.
- `tests/integration/test_llm_fake.py` now proves fake chunk calls return plain-text merge inputs rather than final XML envelopes.
- The broader 252-test regression slice passed after both fixes landed.

Findings summary:

- The whole-plan review blocker around latest-run chunk metadata coherence is resolved.
- The fake-backend chunk-path proof surface now matches the intended contract more honestly: final model-backed outputs stay XML, chunk intermediates stay plain text.

Product calls surfaced:

- No new product call was exposed by this follow-up.

Regressions or ambiguous results:

- No regressions were found in the targeted or broader regression slices.
- Prompt-body token accounting remains intentionally unchanged and still excludes backend-owned system-prompt and invocation framing overhead.

Docs reviewed:

- `docs/plans/plan_regen-refactor_4_notes.md`

Docs changed:

- `docs/plans/plan_regen-refactor_4_notes.md`

Docs reviewed but intentionally unchanged:

- `docs/regen/README.md`
- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`

Recommended next action:

- re-review the whole-plan implementation state

## Phase 6 checkpoint — 2026-03-23

Phase name and completion date:

- Phase 6: scheduler and backend-capability readiness — completed 2026-03-23

Changed code/doc surfaces:

- `src/brain_sync/regen/topology.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/llm/base.py`
- `src/brain_sync/llm/__init__.py`
- `src/brain_sync/llm/claude_cli.py`
- `src/brain_sync/llm/fake.py`
- `tests/unit/test_regen_phase6.py`
- `tests/unit/test_regen_phase1.py`
- `tests/unit/test_regen_queue.py`
- `tests/unit/test_runtime_operational_events.py`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/RULES.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Tests run and results:

- `python -m pytest tests/unit/test_regen_phase6.py tests/unit/test_regen_queue.py tests/unit/test_regen_phase1.py -q` -> 34 passed
- `python -m ruff check src/brain_sync/llm src/brain_sync/regen tests/unit/test_regen_phase6.py tests/unit/test_regen_queue.py tests/unit/test_regen_phase1.py` -> passed
- `python -m pyright src/brain_sync/llm src/brain_sync/regen tests/unit/test_regen_phase6.py tests/unit/test_regen_queue.py tests/unit/test_regen_phase1.py` -> passed
- `python -m pytest tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_regen_phase6.py tests/unit/test_daemon.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase0_baseline.py -q` -> 246 passed
- `python -m ruff check src/brain_sync/llm src/brain_sync/regen src/brain_sync/sync/daemon.py tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_regen_phase6.py tests/unit/test_daemon.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase0_baseline.py docs/regen/README.md docs/architecture/ARCHITECTURE.md docs/RULES.md` -> passed
- `python -m pyright src/brain_sync/llm src/brain_sync/regen src/brain_sync/sync/daemon.py tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_regen_phase6.py tests/unit/test_daemon.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/integration/test_regen_phase0_baseline.py` -> passed

Baseline-versus-current metrics relevant to the phase:

- Queue scheduler explicitness before/after: before this phase the daemon queue had 0 explicit scheduler-decision objects and 1 hidden single-path fast path that delegated ancestor continuation to `regen_path()`; current state has 1 explicit `decide_queue_batch()` surface with 2 named strategies (`single_path_walk_up`, `wave_batch`) and 0 queue calls to `regen_path()`.
- Single-path strategy proof before/after: before this phase the queue could not expose or test the exact walk-up chain it intended to run; current state proves a 1-seed batch such as `initiative/workstream` plans the bounded chain `initiative/workstream -> initiative -> ''`.
- Multi-path strategy proof before/after: before this phase queue wave intent was inferred indirectly from `len(ready) > 1`; current state proves a 2-seed batch such as `area/sub1`, `area/sub2` plans 3 explicit waves `("area/sub1","area/sub2")`, `("area")`, `("")`.
- Backend capability seam before/after: before this phase `BackendCapabilities` exposed prompt-budget class, max prompt tokens, structured-output contract shape, and invocation settings, but had 0 explicit readiness fields for concurrency, startup overhead, or structured-output reliability; current state adds 3 explicit readiness traits: `max_concurrency`, `structured_output.reliability`, and `invocation.startup_overhead_class`.
- Backend readiness examples added in proof: current fake-backend contract reports `max_concurrency = 8` with `startup_overhead_class = low`, while Claude CLI reports `max_concurrency = 1` with `startup_overhead_class = high`; both report `structured_output.reliability = strict`.
- Phase 0 / Phase 2 baseline comparison remains stable: this phase intentionally did not change prompt assembly or prompt-body token accounting, so the existing baseline still reports `research/annual` at `final_invocations = 1` and `chunk_invocations = 0` under the current prompt-body-only measurement scope.

Evidence bundle:

- `tests/unit/test_regen_phase6.py` proves the new scheduler decision seam directly and proves backend-owned readiness traits for fake and Claude backends.
- `tests/unit/test_regen_queue.py` proves queue processing now uses the explicit single-path walk-up path rather than the removed hidden `regen_path()` fast path while preserving wave behavior for multi-path batches.
- `tests/unit/test_runtime_operational_events.py` proves queue event emission remains non-duplicating after the explicit scheduler change.
- `tests/integration/test_regen_pipeline.py` and `tests/integration/test_regen_phase0_baseline.py` prove the queue/scheduler seam change did not regress the current pipeline or the durable baseline harness.

Findings summary:

- Queue scheduling now depends on an explicit ready-batch decision surface instead of hidden engine ancestor traversal.
- The bounded single-path walk-up special case remains in place, but it is now explicit, testable, and only selected when exactly 1 ready seed is present in the queue snapshot.
- Multi-path queue batches still use depth-ordered wave processing, but the wave choice is now made explicitly and explained by the scheduler seam rather than by an inline `len(ready)` branch alone.
- The backend-capability seam is now durable enough for later backend expansion work: REGEN can reason about context budget, max concurrency, startup overhead, and structured-output reliability without reintroducing backend-name heuristics into scheduler policy.
- No actual LLM parallelism was introduced in this phase. `max_concurrency` is readiness metadata for later phases or follow-on work, not a new execution policy.

Final phase report on what scheduler/backend work is now unblocked:

- later queue-policy work can compare “single-path walk-up” versus “use one shared wave model everywhere” by changing the explicit scheduler decision seam rather than by reopening engine propagation logic
- later backend expansion can tune concurrency policy and startup-cost tradeoffs from bounded capability data instead of backend-specific string checks
- later parallelism work can be added behind the current explicit strategy object without reopening the Phase 3 propagation contract or the Phase 4 artifact contract

Product calls surfaced:

- No new Phase 6 blocking product call was exposed.

Regressions or ambiguous results:

- No regressions were found in the targeted or broader queue/daemon/regen regression slices.
- Prompt-body token accounting remains intentionally unchanged in this phase; it still excludes backend-owned system-prompt and invocation framing overhead.
- This phase does not make the daemon queue execute parallel LLM calls; any throughput gain remains deferred intentionally.

Any remaining product calls intentionally deferred from this plan:

- the future deterministic “meaningful change” gate ahead of LLM generation remains deferred to follow-on work
- portable area-move identity for offline reconcile remains deferred to follow-on work

Unresolved product decisions:

- No new unresolved product decision blocks the end of this plan.
- The two deferred follow-on items above remain outside the approved Phase 0-6 scope.

Docs reviewed:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/GLOSSARY.md`
- `docs/RULES.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/sync/README.md`
- `docs/regen/README.md`
- `README.md`

Docs changed:

- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/regen/README.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Docs reviewed but intentionally unchanged:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/GLOSSARY.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `README.md`

Final doc review note summarizing all docs reviewed and updated across implementation:

- Across Phases 0-6, the implementation trail updated `docs/regen/README.md`, `docs/architecture/ARCHITECTURE.md`, `docs/sync/README.md`, `docs/runtime/README.md`, `docs/runtime/SCHEMAS.md`, `docs/RULES.md`, and this notes artifact where the realized behavior changed or the proof trail needed durable capture.
- Across the same implementation trail, `AGENTS.md`, `docs/plans/README.md`, `docs/GLOSSARY.md`, `docs/COMPATIBILITY.md`, `docs/VERSIONING.md`, `docs/brain/README.md`, `docs/brain/SCHEMAS.md`, and `README.md` were reviewed and remain accurate for the current end state.

Recommended next action:

- proceed unchanged

2026-03-23T08:55:08+13:00
Phase: Phase 4 - artifact-aware pipeline hardening
Change: Introduced an explicit REGEN artifact contract for required summary payloads and optional journal payloads, hardened execution to fail invalid structured output at the artifact boundary, delayed runtime success finalization until journal commit succeeds, aligned the fake backend with the fixed contract, and updated the explanatory docs.
Reason: Phase 4 required a fixed summary/journal contract with explicit handling for malformed output, summary-retained similarity success, and journal-write failure without creating a new diagnostics table.
Status: Implemented.

Changed code/doc surfaces:

- `src/brain_sync/regen/artifacts.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/llm/fake.py`
- `tests/unit/test_regen.py`
- `tests/integration/test_llm_fake.py`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Tests run and results:

- `python -m ruff check src/brain_sync/regen/artifacts.py src/brain_sync/regen/engine.py src/brain_sync/llm/fake.py tests/unit/test_regen.py tests/integration/test_llm_fake.py tests/integration/test_regen_pipeline.py docs/regen/README.md docs/architecture/ARCHITECTURE.md` -> passed
- `pyright src/brain_sync/regen/artifacts.py src/brain_sync/regen/engine.py src/brain_sync/llm/fake.py tests/unit/test_regen.py tests/integration/test_llm_fake.py tests/integration/test_regen_pipeline.py` -> passed
- `python -m pytest tests/unit/test_regen.py -q` -> 182 passed
- `python -m pytest tests/integration/test_llm_fake.py tests/integration/test_regen_pipeline.py -q` -> 19 passed
- `python -m pytest tests/unit/test_regen.py tests/integration/test_llm_fake.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_phase2_budgeting.py -q` -> 203 passed

Baseline-versus-current metrics relevant to the phase:

- Invalid plain-output acceptance before/after: before this phase `_parse_structured_output()` accepted 1 no-tag fallback path and treated raw text as summary; current state accepts 0 plain-output fallback paths and requires exactly 1 `<summary>...</summary><journal>...</journal>` envelope.
- Invalid-output classification before/after: before this phase journal-only or malformed XML surfaced indirectly through the tiny-summary guard after parsing to `("", None)`; current state fails those cases at the explicit artifact-contract boundary with `failed_artifact_contract`.
- Fake-backend final-output alignment before/after: before this phase deterministic fake `stable`, `rewrite`, and `large-output` modes emitted plain summary bodies; current state emits the fixed summary/journal XML contract in those modes so final-output integration coverage exercises the same artifact shape as production REGEN. Chunk intermediates remain plain-text merge inputs rather than a separately proven XML artifact path in this phase.
- Success finalization ordering before/after: before this phase successful runtime finalization and owner release happened before journal append; current state finalizes runtime success only after summary persistence and any journal append both succeed.
- Broad regen regression slice: 203 targeted unit/integration tests passed after the change, compared with 0 passing at the midpoint when older plain-output test doubles still violated the new contract; all required fixtures were updated to the fixed envelope.

Evidence bundle:

- `tests/unit/test_regen.py::TestParseStructuredOutput` now proves valid summary/journal parsing, empty-journal handling, and strict rejection of plain output, malformed tags, journal-only output, and text outside the XML envelope.
- `tests/unit/test_regen.py::TestJournalWriting::test_journal_write_failure_surfaces_run_failure` proves a valid summary payload plus a failed journal append surfaces as `RegenFailed` and leaves runtime state marked `failed` rather than silently succeeding.
- `tests/integration/test_llm_fake.py` now proves the stable fake backend emits `<summary>` and `<journal>` sections for final successful outputs, and `tests/integration/test_regen_pipeline.py` still passes end-to-end with the stricter artifact parser. This evidence does not claim separate XML alignment for chunk-call intermediates.

Findings summary:

- REGEN now has an explicit artifact model: `ParsedArtifacts` for validated model output and `ArtifactCommitPlan` for the durable write decision after similarity handling.
- Summary remains the primary required artifact for model-backed REGEN; journal remains optional and only commits when a valid summary payload exists.
- `skipped_similarity` remains a successful run and may still append journal content because the summary payload was valid even though the summary rewrite was discarded.
- `skipped_unchanged` still performs no LLM call and does not synthesize journal output.
- Journal commit failure is now surfaced as a failed run before runtime success is finalized.

Product calls surfaced:

- No new blocking product call was exposed in Phase 4.
- The approved fixed contract was implemented as written: no raw-summary fallback, no journal-only success path, and no new runtime diagnostics table.

Regressions or ambiguous results:

- No regressions were found in the targeted regen unit/integration slice after the contract hardening and fake-backend alignment.
- Journal append failure now fails the run after summary persistence may already have happened; the current implementation does not attempt summary rollback because the approved Phase 4 contract required failure surfacing, not transactional rollback semantics.
- Chunked-flow proof in this phase is limited to preserving the final artifact contract. Forced-chunk fake-backend runs still treat chunk-call outputs as plain-text intermediate summaries in the merge prompt, so Phase 4 should not be read as proving XML artifact handling for chunk intermediates.

Unresolved product decisions:

- None newly surfaced in this phase.

Docs reviewed:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`

Docs changed:

- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Docs reviewed but intentionally unchanged:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `README.md`

Recommended next action:

- proceed unchanged

2026-03-23T16:09:33+13:00
Phase: Phase 5 - observability and cost diagnostics closure
Change: Locked REGEN semantic event fields to typed reason/phase coverage, added a compact diagnostics seam over the existing runtime event surfaces, exposed loadable token-event rows for report aggregation, aligned the Phase 0 baseline harness with the fixed observability contract, and updated the authoritative docs without adding a new runtime table.
Reason: Phase 5 required durable explanation for why REGEN ran, skipped, failed, propagated, chunked, and spent tokens, while staying inside the approved `operational_events` + `token_events` + `regen_locks` contract.
Status: Implemented.

Changed code/doc surfaces:

- `src/brain_sync/regen/diagnostics.py`
- `src/brain_sync/regen/__init__.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/runtime/operational_events.py`
- `src/brain_sync/runtime/repository.py`
- `tests/unit/test_regen_phase5.py`
- `tests/unit/test_regen_queue.py`
- `tests/unit/test_runtime_operational_events.py`
- `tests/unit/test_token_tracking.py`
- `tests/integration/regen_phase0_baseline.py`
- `tests/integration/test_regen_phase0_baseline.py`
- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Tests run and results:

- `python -m ruff check src/brain_sync/regen src/brain_sync/runtime tests/unit/test_regen_phase5.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/unit/test_token_tracking.py tests/integration/regen_phase0_baseline.py tests/integration/test_regen_phase0_baseline.py` -> passed
- `python -m pyright src/brain_sync/regen src/brain_sync/runtime tests/unit/test_regen_phase5.py tests/integration/regen_phase0_baseline.py` -> 0 errors
- `python -m pytest tests/unit/test_regen_phase5.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/unit/test_token_tracking.py -q` -> 40 passed
- `python -m pytest tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_runtime_operational_events.py tests/unit/test_runtime_operational_event_callers.py tests/unit/test_token_tracking.py tests/unit/test_regen_phase5.py tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase2_budgeting.py -q` -> 252 passed

Baseline-versus-current metrics relevant to the phase:

- Locked REGEN semantic coverage before/after: before this phase the catalog did not require typed semantic details for all REGEN started/completed/failed events and the runtime docs did not describe a fixed REGEN observability split; current state field-locks `regen.started` on `details.reason` plus `details.evaluation_outcome`, `regen.completed` on `details.reason` plus `details.propagates_up`, and `regen.failed` on `details.error` plus `details.reason` plus `details.phase`.
- Prompt-planner visibility before/after: before this phase the baseline harness had no durable runtime-surface proof for prompt-budget class, component token breakdown, deferred files, or omitted child summaries; current Phase 0 corpus report records `prompt_component_coverage_count = 8` and the started-event details now carry those prompt-planning facts for each model-backed REGEN run.
- Terminal reason coverage before/after: before this phase the baseline harness did not prove that terminal REGEN rows explained why paths skipped, failed, or propagated; current Phase 0 corpus report records `terminal_reason_coverage_count = 11` with per-path `latest_reason`, `propagates_up`, and propagation details aggregated from `operational_events`.
- Latest-run report coherence before/after: before the review follow-up, churned no-call paths could retain stale `run_reason` / `evaluation_outcome` from an older `regen.started` row or leave them null on backfill-only runs; current report uses the latest terminal no-call context, so `product/atlas` now reports `run_reason = "content_hash_unchanged"` with `evaluation_outcome = "unchanged"` and `legacy/metadata` reports `run_reason = "metadata_backfill_only"` with `evaluation_outcome = "metadata_backfill"`.
- Comparison-readiness before/after: before this phase the baseline harness relied on bespoke metric extraction without a compact report seam over the runtime diagnostics; current state emits a `diagnostic_report` with `comparison_ready_keys = ["outcome_counts", "path_reports[].component_tokens", "path_reports[].token_cost", "path_reports[].propagates_up", "high_churn_paths"]`.
- Cost aggregation before/after: before this phase token telemetry was durable only at the raw row level; current report rolls those existing `token_events` rows into per-path totals including `invocations`, `chunk_invocations`, `final_invocations`, token totals, and duration totals. On the current corpus, `research/annual` reports `final_invocations = 1`, `chunk_invocations = 0`, and `final_total_tokens = 117991` under the existing application-prompt-body measurement scope.
- Contract-boundary proof: current `diagnostic_report.observability_contract` is fixed to `semantic_events_surface = "operational_events"`, `cost_surface = "token_events"`, `coordination_surface = "regen_locks"`, and `logs_authoritative = false`, confirming the phase stayed within the approved observability surfaces and added 0 new runtime tables.
- Queue failure typing before/after: before the review follow-up, queue terminal failure events used `details.reason = "queue_retries_exhausted"` even when `outcome = "lock_contention_deferred"`; current state preserves the cause distinction with `details.reason = "queue_lock_contention_deferred"` for lock-contention exhaustion and `details.reason = "queue_retries_exhausted"` for generic retry exhaustion.

Evidence bundle:

- `tests/unit/test_regen_phase5.py` proves typed REGEN started/completed/failed event details, including semantic reasons, propagation outcomes, prompt-component capture, chunk-versus-final cost aggregation in the compact report, and the bounded terminal-lock follow-up for already-unowned or missing rows.
- `tests/unit/test_runtime_operational_events.py` proves the field-locked runtime event catalog now requires the new REGEN semantic details, and `tests/unit/test_token_tracking.py` proves the new `load_token_events(...)` filters used by diagnostics/reporting.
- `tests/integration/test_regen_phase0_baseline.py` now proves the Phase 0 baseline harness exports a `diagnostic_report` with the fixed observability contract, terminal reason coverage, comparison-ready keys, and latest-run coherent no-call path reasons over the current corpus.
- `tests/unit/test_regen_queue.py::test_lock_contention_exhaustion_records_classified_failure` now proves queue terminal failure details preserve the correct typed reason for lock-contention exhaustion.
- The broader REGEN/runtime regression slice still passed unchanged at `252` tests, which shows the observability work did not require a new runtime persistence surface or change the existing REGEN control flow.

Findings summary:

- Phase 5 closed the approved observability gap without adding a new runtime table.
- `operational_events` is now the typed semantic trail for why a path ran, skipped, failed, or propagated, including prompt-planner facts for model-backed runs.
- `token_events` remains per-call telemetry, but the new diagnostics seam now makes chunk cost, final-call cost, and high-churn paths easy to inspect without bespoke ad hoc queries.
- The compact report now stays latest-run coherent for no-call churned paths instead of inheriting stale `regen.started` reasons from earlier model-backed runs.
- Queue terminal failure events now preserve the distinction between lock-contention exhaustion and generic retry exhaustion in their typed `details.reason` field.
- `regen_locks` remains coordination-only runtime state and is now documented more explicitly as not being a historical analytics surface.
- The baseline harness can now compare REGEN decisions and costs through a compact report built from the approved durable surfaces rather than through chat-only interpretation.

Product calls surfaced:

- No new product call was exposed in Phase 5.
- The implementation stayed within the fixed observability contract from the approved plan: no new runtime diagnostics table, no attempt to make logs authoritative, and no migration of semantic explanations into `regen_locks`.

Regressions or ambiguous results:

- No regressions were found in the focused Phase 5 tests or the broader REGEN/runtime regression slice.
- `token_events` still represents invocation-level telemetry only, so prompt-component sizes and propagation reasons remain split across `operational_events` details and the compact aggregated report rather than living in one raw runtime row.
- The Phase 0 baseline continues to measure application-assembled prompt-body tokens rather than provider-billed totals; the new report makes that easier to compare, but it does not change that existing measurement scope.

Unresolved product decisions:

- None newly surfaced in this phase.

Docs reviewed:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/sync/README.md`
- `docs/regen/README.md`
- `README.md`

Docs changed:

- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/regen/README.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Docs reviewed but intentionally unchanged:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/GLOSSARY.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/sync/README.md`
- `README.md`

Recommended next action:

- proceed unchanged

2026-03-23T09:35:00+13:00
Implementation note: Post-Phase-3 REGEN seam extraction before Phase 4
Change: Extracted deterministic folder evaluation into `regen/evaluation.py` and prompt assembly/chunk planning into `regen/prompt_planner.py`, while keeping `regen/engine.py` as the compatibility-preserving orchestration surface.
Reason: The approved implementation work left `regen/engine.py` too large to carry comfortably into later artifact and observability phases; this bounded refactor creates clearer seams for later execution/persistence extraction and for a future deterministic generation gate.
Status: Implemented.

Changed code/doc surfaces:

- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/evaluation.py`
- `src/brain_sync/regen/prompt_planner.py`
- `src/brain_sync/regen/__init__.py`
- `docs/architecture/ARCHITECTURE.md`
- `docs/regen/README.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Tests run and results:

- `python -m ruff check src/brain_sync/regen/engine.py src/brain_sync/regen/evaluation.py src/brain_sync/regen/prompt_planner.py --fix` -> passed after import/format cleanup
- `pyright src/brain_sync/regen/engine.py src/brain_sync/regen/evaluation.py src/brain_sync/regen/prompt_planner.py` -> passed
- `python -m pytest tests/unit/test_regen.py tests/unit/test_regen_phase1.py tests/unit/test_regen_phase2.py -q` -> 193 passed
- `python -m pytest tests/unit/test_regen_queue.py -q` -> 21 passed
- `python -m pytest tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase2_budgeting.py -q` -> 9 passed

Baseline-versus-current metrics relevant to the note:

- `src/brain_sync/regen/engine.py` moved from roughly 2390 lines before the refactor to 1290 lines after the extraction.
- New focused seams added: 1 deterministic evaluation module (`regen/evaluation.py`) and 1 prompt-planning module (`regen/prompt_planner.py`).
- Compatibility preservation remained explicit: existing tests that patch `brain_sync.regen.engine.MAX_PROMPT_TOKENS`, `brain_sync.regen.engine.invoke_claude`, `brain_sync.regen.engine._preprocess_content`, and `brain_sync.regen.engine._split_markdown_chunks` still passed unchanged.

Findings summary:

- The extraction materially reduced `regen/engine.py` size and made evaluation and prompt-planning ownership explicit without changing phase behavior.
- `regen_single_folder()` remains the orchestration seam and still carries execution, output parsing, and persistence responsibilities.
- The current split creates a clean future seam for a deterministic "should generation run?" policy gate between evaluation and backend execution.

Product calls surfaced:

- No new product decisions were introduced by this bounded structural refactor.

Regressions or ambiguous results:

- No regressions were found in the targeted regen unit, queue, or integration slices.
- `regen/engine.py` is still larger than ideal, so the seam extraction should be treated as partial completion rather than the end of regen modularization.

Unresolved product decisions:

- None added by this refactor note.

Docs reviewed:

- `AGENTS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/regen/README.md`
- `docs/plans/README.md`

Docs changed:

- `docs/architecture/ARCHITECTURE.md`
- `docs/regen/README.md`
- `src/brain_sync/regen/__init__.py`
- `docs/plans/plan_regen-refactor_4_notes.md`

Docs reviewed but intentionally unchanged:

- `AGENTS.md`
- `docs/plans/README.md`

2026-03-23T07:53:54.0198904+13:00
Phase: Phase 3 - dirty detection and propagation precision
Change: Converged single-path, wave, and queue propagation on one shared contract for actual parent inputs, removed false-positive walk-up from local-only structure churn and metadata backfill, and moved parent-visible folder-rename propagation to the sync-owned move enqueue path.
Reason: Phase 3 required REGEN propagation to follow actual parent dependencies rather than legacy continuation shortcuts.
Status: Implemented with one approved exception to the coarse plan matrix.

Changed code/doc surfaces:

- `src/brain_sync/regen/topology.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/sync/lifecycle.py`
- `tests/unit/test_regen.py`
- `tests/unit/test_sync_events.py`
- `tests/integration/regen_phase0_baseline.py`
- `tests/integration/test_regen_phase0_baseline.py`
- `docs/regen/README.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Tests run and results:

- `python -m pytest tests/unit/test_regen.py -q` -> 181 passed
- `python -m pytest tests/unit/test_sync_events.py tests/unit/test_watcher_moves.py -q` -> 13 passed
- `python -m pytest tests/integration/test_regen_phase0_baseline.py tests/integration/test_regen_pipeline.py -q` -> 8 passed
- `python -m pytest tests/unit/test_regen_queue.py tests/unit/test_regen.py tests/unit/test_sync_events.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase0_baseline.py -q` -> 216 passed
- `ruff check src/brain_sync/regen/topology.py src/brain_sync/regen/engine.py src/brain_sync/regen/queue.py src/brain_sync/sync/lifecycle.py tests/unit/test_regen.py tests/unit/test_sync_events.py tests/integration/regen_phase0_baseline.py tests/integration/test_regen_phase0_baseline.py` -> passed
- `pyright src/brain_sync/regen/topology.py src/brain_sync/regen/engine.py src/brain_sync/regen/queue.py src/brain_sync/sync/lifecycle.py tests/unit/test_regen.py tests/unit/test_sync_events.py tests/integration/regen_phase0_baseline.py tests/integration/test_regen_phase0_baseline.py` -> passed

Baseline-versus-current metrics relevant to the phase:

- Targeted Phase 0 walk-up ancestor continuation rate improved from `2/3` cases before Phase 3 (`rename_walkup`, `backfill_walkup`) to `0/3` cases after Phase 3 (`small_leaf_unchanged`, `rename_walkup`, `backfill_walkup` all now stop at the leaf).
- `rename_walkup` before/after: `ancestor_event_count` moved from `1` to `0`; ordered paths moved from `["operations/rename-demo", "operations"]` to `["operations/rename-demo"]`.
- `backfill_walkup` before/after: `ancestor_event_count` moved from `1` to `0`; ordered paths moved from `["legacy/metadata", "legacy"]` to `["legacy/metadata"]`.
- Shared propagation set before/after: before Phase 3, single-path walk-up continued on `skipped_rename` and `skipped_backfill` even though wave processing already excluded `skipped_backfill`; after Phase 3, single-path walk-up, full-tree wave execution, and queue wave execution all share the same upward set: `regenerated`, `skipped_no_content`, and `cleaned_up`.
- Parent-visible folder move enqueue before/after: before Phase 3, same-parent folder rename enqueued only the moved area and cross-branch folder move enqueued the moved area plus only the old parent; after Phase 3, same-parent rename enqueues the moved area plus the shared parent, root-level rename enqueues the moved area plus root, and cross-branch move enqueues the moved area plus both old and new parents.
- Quality guard remained stable: the Phase 0 anchor harness stayed `all_passed = true` before and after this phase.

Evidence bundle:

- `tests/integration/test_regen_phase0_baseline.py` plus the current baseline collector output prove the false-positive ancestor-walk-up drop from `2/3` to `0/3` without anchor loss.
- `tests/unit/test_regen.py::test_backfill_ancestor_not_regenerated_on_second_visit` and `tests/unit/test_regen.py::test_local_structure_only_rename_does_not_walk_up_to_parent` prove local-only structure churn and metadata backfill now stop at the leaf.
- `tests/unit/test_sync_events.py::test_apply_folder_move_enqueues_shared_parent_on_same_parent_rename`, `tests/unit/test_sync_events.py::test_apply_folder_move_enqueues_root_on_root_level_rename`, and `tests/unit/test_sync_events.py::test_apply_folder_move_enqueues_old_parent_on_cross_branch_move` prove parent-visible structure changes are now carried by explicit sync move enqueue paths.

Findings summary:

- Single-path walk-up, full-tree wave execution, and queue wave execution now share one authoritative propagation rule set.
- `skipped_backfill` no longer continues upward in walk-up mode, removing the Phase 0 asymmetry with wave execution.
- Local-only `skipped_rename` no longer implies parent invalidation; REGEN updates local managed hashes and stops at the current node.
- Parent-visible folder renames and moves are now explicit sync-lifecycle responsibilities rather than implicit REGEN walk-up side effects.
- The false-positive ancestor evaluation cases captured in the Phase 0 corpus were removed without degrading the anchor-quality harness.

Product calls surfaced:

- Resolved by user clearance on 2026-03-23: local-only structure changes inside a folder do not propagate upward; parent-visible child-structure changes propagate via explicit move/reconcile paths.
- Approved exception list for the plan matrix: the coarse `skipped_rename -> propagate` row is narrowed in implementation because `skipped_rename` remains a local structure-only REGEN action; parent-visible folder rename and move propagation is handled by sync-owned move enqueue paths instead of generic REGEN walk-up.

Regressions or ambiguous results:

- No regressions were found in the targeted unit, queue, watcher-move, or integration slices that exercise the changed propagation paths.
- The Phase 0 corpus does not yet include an explicit folder-move scenario, so the proof for parent-visible rename propagation comes from dedicated sync move tests rather than from the baseline corpus itself.

Unresolved product decisions:

- None within Phase 3 after the user-cleared propagation rule and approved exception above.

Docs reviewed:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/sync/README.md`
- `docs/regen/README.md`
- `README.md`

Docs changed:

- `docs/architecture/ARCHITECTURE.md`
- `docs/sync/README.md`
- `docs/regen/README.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Docs reviewed but intentionally unchanged:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `README.md`

Recommended next action:

- proceed unchanged

2026-03-23T07:21:03+13:00
Phase: Phase 2 - prompt assembly and budgeting refactor
Change: Reworked REGEN prompt assembly to consume the Phase 1 backend-capability contract, use conservative model-aware effective budgets, prioritize stable scaffold then direct files then child summaries, and defer chunking until remaining direct-file budget truly requires it.
Reason: Phase 2 required prompt planning to stop treating long context as either unavailable or blanket-default, while materially reducing unnecessary chunk-and-merge work under the approved inclusion priorities.
Status: Implemented.

Changed code/doc surfaces:

- `src/brain_sync/regen/engine.py`
- `tests/unit/test_regen_phase2.py`
- `tests/integration/test_regen_phase2_budgeting.py`
- `tests/unit/test_regen.py`
- `tests/integration/regen_phase0_baseline.py`
- `tests/integration/test_regen_phase0_baseline.py`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Tests run and results:

- `python -m pytest tests/unit/test_regen_phase2.py tests/integration/test_regen_phase2_budgeting.py -q` -> 4 passed
- `ruff check src/brain_sync/regen/engine.py tests/unit/test_regen_phase2.py tests/integration/test_regen_phase2_budgeting.py tests/integration/regen_phase0_baseline.py` -> passed
- `pyright src/brain_sync/regen/engine.py tests/unit/test_regen_phase2.py tests/integration/test_regen_phase2_budgeting.py tests/integration/regen_phase0_baseline.py` -> passed
- `python -m pytest tests/unit/test_regen.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase0_baseline.py -q` -> 185 passed
- `ruff check src/brain_sync/regen/engine.py tests/unit/test_regen.py tests/unit/test_regen_phase2.py tests/integration/test_regen_phase2_budgeting.py tests/integration/test_regen_phase0_baseline.py tests/integration/regen_phase0_baseline.py` -> passed
- `python -m pytest tests/unit/test_regen_phase2.py tests/integration/test_regen_phase2_budgeting.py tests/unit/test_regen.py tests/integration/test_regen_pipeline.py tests/integration/test_regen_phase0_baseline.py -q` -> 189 passed
- `python -c "import json; from tests.integration.regen_phase0_baseline import run_phase0_baseline; print(json.dumps(run_phase0_baseline(), sort_keys=True))"` -> completed and emitted the current Phase 2 baseline evidence bundle used below

Baseline-versus-current metrics relevant to the phase:

- Planner contract before/after: before this phase prompt assembly used 1 fixed planner budget (`120000`) plus earlier char-threshold-driven chunk fallback; current state uses capability-aware effective planner budgets with 1 explicit legacy override hook, `160000` for standard-capability models, and `320000` for current `extended_1m` models while still treating long context as selective headroom rather than "use 1M".
- Inclusion priority before/after: before this phase direct files and child summaries were packed under one coarse budget with earlier file deferral; current state preserves the approved priority order of stable scaffold first, direct files second, child summaries third.
- Large-leaf chunking delta on the fictional corpus: `research/annual` moved from 5 LLM invocations (4 chunk + 1 merge) to 1 invocation, and from 1 deferred file to 0 deferred files.
- Large-leaf prompt-shape delta on the fictional corpus: `research/annual` prompt tokens moved from ~1745 estimated tokens with chunk summaries in the merge prompt to ~157253 estimated tokens with the direct file inlined under the `extended_1m` budget.
- Large-leaf prompt-body-token delta on the fictional corpus: `research/annual` moved from 118961 total prompt-body tokens to 117991 total prompt-body tokens in the deterministic baseline harness, a reduction of 970 tokens (about 0.8%) despite eliminating 4 extra chunk calls. This comparison excludes backend system-prompt content, backend invocation framing, and provider-billed-token adjustments.
- Large-leaf latency delta on the fictional corpus: `research/annual` collector latency moved from 68 ms total to 3 ms total in the deterministic baseline backend run because the path no longer performs chunk-and-merge fan-out.
- Chunked versus non-chunked corpus delta: the Phase 0 corpus moved from 1 chunked node / 6 non-chunked nodes to 0 chunked nodes / 7 non-chunked nodes.
- Wide-parent prompt cost remains child-summary dominated after the refactor: `programs/ops` currently spends ~9432 estimated tokens on child summaries versus ~43 on direct files, which matches the approved budget priority while preserving all child summaries in this representative case.

Evidence bundle:

- `tests/unit/test_regen_phase2.py` proves three key planner contracts directly: extended-context models can inline a large file without chunking, the legacy `MAX_PROMPT_TOKENS` override still forces deferral in bounded-budget tests, and omitted child summaries are surfaced in planner diagnostics.
- `tests/integration/test_regen_phase2_budgeting.py` proves the end-to-end large-leaf path on `claude-sonnet-4-6` now completes in a single regen call with no chunk fallback.
- The Phase 0 baseline harness now consumes real prompt-planner diagnostics rather than a hand-maintained estimator, and the current baseline confirms anchor-quality checks still pass for `_core`, `product/atlas`, `programs/ops`, and `research/annual`.
- The baseline harness now states its token-accounting scope explicitly: it measures application-assembled prompt-body tokens only, including packaged instructions, `_core` context, direct-file or chunk-summary body content, child summaries when present, and existing summary when present, while excluding backend system prompt, backend invocation framing, and provider-specific billed-token adjustments.
- The before/after improvement claimed in this phase is concrete and measured: on the representative large-leaf corpus path, REGEN now avoids chunk fan-out entirely while preserving the large-file anchors in the generated summary.

Findings summary:

- Phase 2 successfully moved prompt planning onto the bounded backend-capability seam from Phase 1 instead of keeping model-string budgeting logic local to REGEN execution.
- The approved inclusion priority is now reflected in implementation and docs: stable scaffold, then direct files, then child summaries.
- On current `extended_1m` capability models such as Sonnet 4.6, REGEN now uses materially larger single-pass prompts when that avoids unnecessary chunking, but still stops well short of treating the full context window as default budget.
- The largest measurable gain on the fictional corpus is chunk-rate and invocation-count reduction, not dramatic raw token savings.
- `regen/engine.py` gained clearer prompt-planner helper seams, but it remains a large module; this phase improved modularity inside the file rather than splitting ownership across new modules.

Product calls surfaced:

- No new blocking product decision was exposed in Phase 2; the approved Phase 2 guidance on conservative model-aware budgeting and prompt inclusion priority was implemented as directed.
- The still-open later-phase product call remains the propagation mismatch around `skipped_backfill`, which is intentionally left for Phase 3.

Regressions or ambiguous results:

- No quality regression was found in the Phase 2 proof bundle; all Phase 0 anchor checks still passed after the planner change.
- Raw token reduction on the large-leaf corpus case was modest even though chunking collapsed from 5 calls to 1. That is an intentional and acceptable trade in this phase, but it means the strongest current evidence is lower chunk fan-out and latency rather than major token-elimination on this specific corpus.
- Existing regen tests that had implicitly equated "large file" with "must chunk" had to be updated to assert budget-driven chunking instead. This was expected behavior drift from the approved Phase 2 refactor, not an accidental regression.

Unresolved product decisions:

- Whether `skipped_backfill` should converge fully to the approved wave propagation contract remains unresolved until Phase 3 implementation.
- Whether the generalized baseline harness should eventually be renamed beyond `regen_phase0_baseline.py` remains intentionally deferred; it is useful now, but no naming/product decision is needed before later phases.

Docs reviewed:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`

Docs changed:

- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Docs reviewed but intentionally unchanged:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `README.md`

Recommended next action:

- proceed unchanged

2026-03-22T19:17:18+13:00
Phase: Phase 1 - evaluation boundary and bounded backend-capability contract
Change: Extracted an explicit no-backend evaluation model for one REGEN node, introduced a bounded generic LLM capability contract, narrowed the application-to-regen seam, and aligned the explanatory docs with the new boundary.
Reason: Phase 1 required a durable split between "should this node regen?" and "perform regen", plus a backend-owned capability seam that Phase 2 must consume instead of ad hoc model heuristics.
Status: Implemented.

Changed code/doc surfaces:

- `src/brain_sync/llm/base.py`
- `src/brain_sync/llm/__init__.py`
- `src/brain_sync/llm/claude_cli.py`
- `src/brain_sync/llm/fake.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/__init__.py`
- `src/brain_sync/application/regen.py`
- `tests/unit/test_regen_phase1.py`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Tests run and results:

- `python -m pytest tests/unit/test_regen_phase1.py -q` -> 9 passed
- `ruff check src/brain_sync/llm src/brain_sync/regen src/brain_sync/application/regen.py tests/unit/test_regen_phase1.py` -> passed
- `pyright src/brain_sync/llm src/brain_sync/regen src/brain_sync/application/regen.py tests/unit/test_regen_phase1.py` -> passed
- `python -m pytest tests/unit/test_regen.py tests/unit/test_regen_queue.py tests/unit/test_reconcile_knowledge_tree.py tests/integration/test_regen_pipeline.py -q` -> 216 passed
- `ruff check docs/regen/README.md docs/architecture/ARCHITECTURE.md src/brain_sync/llm src/brain_sync/regen src/brain_sync/application/regen.py tests/unit/test_regen_phase1.py` -> passed

Baseline-versus-current metrics relevant to the phase:

- Explicit evaluation surface before/after: before this phase REGEN decision policy was split across `classify_folder_change()` plus inline branches in `regen_single_folder()` with 3 public `ChangeEvent` states and several implicit cleanup/backfill branches; current state has 1 explicit `evaluate_folder_state()` result carrying 6 named outcomes (`missing_path`, `no_content`, `unchanged`, `structure_only`, `content_changed`, `metadata_backfill`) without invoking the backend.
- Backend capability contract before/after: before this phase there was no bounded capability seam in `llm/`; current state has 1 backend-owned contract surface (`BackendCapabilities`) exposing prompt-budget class, max prompt tokens, structured-output expectations, and invocation settings.
- Model-capability evidence added in the contract: current contract resolves unknown models conservatively at `standard_200k` / `200000` max prompt tokens and treats explicit Sonnet/Opus 4.6 selectors and `[1m]` selectors as `extended_1m` / `1000000` max prompt tokens.
- Cross-package reach-through before/after: `src/brain_sync/application/regen.py` previously imported 1 engine-local helper directly (`invalidate_global_context_cache` from `brain_sync.regen.engine`); current state has 0 direct `application -> regen.engine` imports in production code and uses the package surface instead.
- Phase 0 baseline behavior versus current behavior: no token, chunk-rate, or propagation behavior was intentionally changed in Phase 1; the Phase 0 baseline remains the current runtime baseline, while the measurable improvement in this phase is decision-model explicitness and boundary narrowing rather than runtime cost reduction.

Evidence bundle:

- `tests/unit/test_regen_phase1.py` proves all required evaluation outcomes without invoking the active backend and proves REGEN execution consumes backend-supplied invocation settings.
- Existing regen regression coverage still passed after the seam change: `tests/unit/test_regen.py`, `tests/unit/test_regen_queue.py`, `tests/unit/test_reconcile_knowledge_tree.py`, and `tests/integration/test_regen_pipeline.py` all passed unchanged.
- The before/after improvement claimed in this phase is structural and testable: before Phase 1 the evaluation model was implicit and backend capability assumptions lived as engine-local constants; after Phase 1 both seams are explicit, typed, and covered by dedicated tests.

Findings summary:

- REGEN now has an explicit evaluation boundary that can classify a node into the required Phase 1 outcomes without invoking the backend.
- `regen_single_folder()` now consumes evaluation results rather than recomputing the same cleanup/backfill/rename gating inline.
- The backend-capability seam is now owned by `llm/`, not by REGEN constants, and it is generic rather than REGEN-named at the type level.
- Current capability mapping is model-aware enough for the approved next phase: it reports conservative `200k` ceilings for unknown models and `1M` capability for explicit Sonnet 4.6 / Opus 4.6 selectors and `[1m]` selectors.
- The current walk-up versus wave behavior mismatch around `skipped_backfill` is still present by design in this phase; Phase 1 made it easier to reason about, but did not change propagation behavior.

Product calls surfaced:

- No new blocking product call was exposed inside Phase 1.
- The already known later-phase choice remains open: how aggressively Phase 2 should spend long-context capability on models such as Sonnet 4.6 versus staying conservative by default. The contract now exposes capability ceilings, but Phase 1 does not choose the runtime budget envelope.

Regressions or ambiguous results:

- No regressions were found in the targeted new tests or the broader existing regen/regression slice.
- The walk-up versus wave asymmetry for `skipped_backfill` remains an intentional current-state mismatch; this is not a new ambiguity, but it remains unresolved until the propagation phase lands the approved matrix.

Unresolved product decisions:

- Phase 2 still needs an explicit decision on the default effective budget envelope for long-context-capable models, even though the capability ceiling is now surfaced.
- The suggestion to generalize the Phase 0 baseline harness filename was reviewed, but intentionally left unchanged in this phase to avoid rewriting the just-established checkpoint trail before we decide whether the harness becomes a stable long-lived utility.

Docs reviewed:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `README.md`

Docs changed:

- `docs/regen/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_regen-refactor_4_notes.md`

Docs reviewed but intentionally unchanged:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `README.md`

Recommended next action:

- proceed unchanged

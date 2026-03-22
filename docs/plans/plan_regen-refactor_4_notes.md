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

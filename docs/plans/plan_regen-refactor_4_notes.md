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
- Current token usage per node on the Phase 0 corpus: `research/annual` 118961 total tokens across 5 invocations (4 chunk + 1 merge), `programs/ops` 8371, `_core` 1319, `product/atlas` 1271, `operations` 1251, `legacy` 1251, `operations/rename-demo` 1220.
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
- The large-leaf case confirms current chunk fallback is active and expensive under the fixed budget: `research/annual` alone consumed 118961 tokens across 5 calls.
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

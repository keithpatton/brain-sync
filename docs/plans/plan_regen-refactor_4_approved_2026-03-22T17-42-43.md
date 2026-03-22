# Approval

Approved: 2026-03-22T17:42:43+13:00
Approved by: Codex

Notes:

- phase gates are now durable, non-self-approving, and tied to the approved
notes artifact
- Phase 1 now provides a bounded backend-capability contract before prompt
budgeting work begins
- propagation, summary/journal semantics, observability surfaces, and
documentation/versioning triggers are now concrete enough for phased
implementation without implementer guesswork

---

# plan_regen-refactor_4_2026-03-22: REGEN Hardening And Refactor

## Status

Approved implementation plan. This revision is the authoritative handoff for
phased REGEN hardening and refactor work.

It records phased scope, sequencing, design constraints, durable decision
gates, documentation obligations, and acceptance criteria for implementation
and later implementation review.

## Relationship To Prior Plan And Review

This revision supersedes:

- `docs/plans/PLAN_regen-refactor.md`
- `docs/plans/plan_regen-refactor_2_2026-03-22.md`
- `docs/plans/plan_regen-refactor_3_2026-03-22.md`

This revision responds directly to:

- `docs/plans/plan_regen-refactor_3_review_1_2026-03-22.md`

The blocking issues addressed here are:

- phase gates are now made durable and non-self-approving
- backend-capability policy is moved earlier so Phase 2 has an approved source
of truth
- the target propagation contract is now explicit
- summary/journal and observability contract choices are now pinned down
tightly enough for implementation and doc alignment

## Objective

Raise REGEN to a state where it:

- burns materially fewer unnecessary tokens
- performs materially fewer unnecessary regens
- preserves or improves generated meaning quality
- improves end-to-end regen latency and throughput
- exposes cleaner seams for future artifact specialization and backend
expansion
- becomes easier to reason about, test, observe, and document correctly

This is a product-and-architecture hardening plan, not a code-cleanup-only
plan.

## Authoritative Inputs

Implementation and review must treat these documents as primary constraints:

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

Primary code seams that this plan must keep aligned:

- `src/brain_sync/regen/__init__.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/regen/topology.py`
- `src/brain_sync/regen/lifecycle.py`
- `src/brain_sync/application/regen.py`
- `src/brain_sync/application/sync_events.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/llm/__init__.py`
- `src/brain_sync/llm/base.py`
- `src/brain_sync/llm/claude_cli.py`
- `src/brain_sync/runtime/repository.py`
- `tests/unit/test_regen.py`
- `tests/unit/test_regen_queue.py`
- `tests/unit/test_regen_lifecycle.py`
- `tests/integration/test_regen_pipeline.py`
- `tests/e2e/regressions/test_content_hash_redundant_regen.py`

## Problem Statement

The current REGEN subsystem is directionally strong but still mixes too many
concerns in one place and still leaves too much cost, latency, policy
ambiguity, and documentation drift risk on the table.

The highest-leverage current problems are:

1. prompt assembly and budgeting are deterministic but still coarse, with a
  fixed budget and early chunking rules that leave newer long-context models
   underused
2. dirty detection and parent propagation are good enough to avoid some churn
  but not yet cleanly aligned around actual parent inputs
3. single-path walk-up and multi-path wave execution still encode slightly
  different continuation and propagation semantics
4. `regen.engine` still mixes evaluation, prompt planning, LLM execution,
  persistence, skip logic, and telemetry in one implementation seam
5. observability exists but does not yet explain REGEN decisions well enough
  for confident optimization
6. summary and journal are already artifact-like outputs, but the pipeline does
  not yet make artifact boundaries explicit
7. scheduler and backend work should come later, but the current shape makes
  later optimization harder than it should be
8. explanatory and normative docs could drift as the refactor lands unless doc
  review and alignment are treated as first-class work

## Fixed Planning Direction

These are the proposed design directions for implementation planning. Review
should challenge them explicitly if needed, but the plan assumes them unless a
review artifact says otherwise.

### 1. Quality Is A Hard Gate

Token and latency wins do not count as success if meaning quality regresses.

### 2. REGEN Policy Should Be Backend-Agnostic

The current default model is Claude Sonnet 4.6, but REGEN should become
model-aware and backend-aware rather than more Claude-specific.

### 3. Long Context Is A Capability, Not A Blanket Default

The plan assumes REGEN should learn to exploit larger context windows when
useful, but should not simply replace the current budget with "use 1M."

### 4. Parent Propagation Should Follow Actual Parent Inputs

The target model is dependency-based propagation, not legacy continuation for
its own sake.

### 5. Product Calls Should Be Resolved Incrementally But Durably

The implementer must not silently choose through material product tradeoffs
inside a phase. When a phase exposes a real product call, the phase pauses and
the findings are recorded durably before continuation is cleared.

### 6. Documentation Alignment Is Part Of Completion

The implementer must not treat docs as a final cleanup pass. Any phase that
changes the current REGEN behaviour, subsystem boundary, diagnostic contract,
or cross-cutting rule must explicitly review and update the authoritative docs
for that subject.

## Non-goals

- no broad redesign of sync lifecycle ownership outside REGEN-relevant seams
- no default portable-brain format change unless later review proves it is
unavoidable
- no immediate rollout of same-wave parallel LLM execution in the early phases
- no assumption that larger context windows should always be fully consumed
- no commitment to split summary and journal into separate model calls unless
an explicit phase gate approves that product change
- no broad observability platform or dashboard project
- no generic workflow engine or plugin system
- no new runtime table for REGEN diagnostics unless a later review or approval
artifact explicitly authorizes it

## Durable Phase Gate Model

The phase gates in this plan are not conversational only.

### Required durable artifact

Once an approved revision exists, the implementer must create and maintain the
matching notes artifact:

- `docs/plans/plan_regen-refactor_<approved-iteration>_notes.md`

That notes file is the durable checkpoint trail for this plan's execution.

### Required checkpoint sections

Each completed phase must append a new checkpoint section to the notes file
with at least:

- phase name and completion date
- changed code/doc surfaces
- tests run and their result
- baseline-versus-current metrics relevant to the phase
- findings summary
- product calls surfaced
- docs reviewed
- docs changed
- docs reviewed but intentionally unchanged
- recommended next action:
  - proceed unchanged
  - proceed with narrowed scope
  - pause for replanning

### Minimum proof bundle

No phase checkpoint passes without enough proof for a reviewer or user to
judge continuation. At minimum, each checkpoint must include:

- one concrete evidence bundle tied to the phase goals
- one before/after comparison where the phase claims improvement
- explicit mention of any regressions or ambiguous results
- explicit mention of any unresolved product decision

Examples of acceptable proof:

- measured token delta on the Phase 0 corpus
- measured chunk-rate delta on representative cases
- explicit action/outcome matrix comparisons
- test names proving contract coverage
- doc review table proving authority alignment

Examples of insufficient proof:

- "looks better locally"
- pure chat narration with no durable notes update
- implementer assertion that the next phase is safe without metrics or tests

### Who can clear the next phase

The implementer may never self-clear the next phase.

After each phase checkpoint, continuation may be cleared only by:

- the user explicitly, or
- an explicitly assigned reviewer / implementation reviewer acting with that
delegated authority

If a checkpoint exposes a scope change, product decision, normative rule
change, or version/compatibility implication, the default required clearer is
the user unless the user has already delegated that choice.

### When continuation must stop

The implementer must stop and seek clearance when any of the following are
true:

- quality signals are ambiguous or regressed
- the best next step depends on a product tradeoff
- the planned next phase no longer matches what the prior phase revealed
- a new invariant appears necessary
- a doc-surface owner becomes ambiguous
- a runtime schema, compatibility, or versioning trigger appears possible

## Scope

In scope for the implementation stage:

- establishing REGEN baselines for cost, latency, quality, and documentation
surfaces
- establishing a bounded backend-capability contract before prompt-budget work
- separating evaluation from execution
- refactoring prompt assembly and context budgeting
- tightening dirty detection and parent propagation rules
- making summary and journal artifact boundaries explicit in the pipeline
- strengthening REGEN observability and diagnostic explainability
- narrowing and clarifying REGEN service seams
- limited scheduler and backend-capability work needed to prepare later
optimization safely
- documentation review and updates required to keep the new behaviour
intentionally aligned

## Phase Order

The implementation should be organized into seven gated phases.

1. Phase 0: baseline, corpus, and decision baseline
2. Phase 1: evaluation boundary and bounded backend-capability contract
3. Phase 2: prompt assembly and budgeting refactor
4. Phase 3: dirty detection and propagation precision
5. Phase 4: artifact-aware pipeline hardening
6. Phase 5: observability and cost diagnostics closure
7. Phase 6: scheduler and backend-capability readiness

Later phases are not automatic. Each phase requires a durable checkpoint and
explicit continuation clearance.

## Phase 0: Baseline, Corpus, And Decision Baseline

Goals:

- establish a measurable baseline before structural changes begin
- make quality protection concrete instead of aspirational
- expose early product calls before architecture is changed
- identify the documentation surfaces most likely to change

Required outcomes:

- one representative fictional REGEN evaluation corpus covering:
  - small leaf areas
  - large leaf areas
  - parent areas with many children
  - `_core`
  - rename-only churn
  - metadata-only/backfill-style paths
- baseline measurement for:
  - token usage per node
  - chunked vs non-chunked run counts
  - prompt size by major component
  - latency per node
  - skip reason frequency
  - ancestor propagation frequency
- a quality evaluation approach strong enough to catch obvious factual loss,
summary thinning, or structural degradation
- a documentation impact inventory for at least:
  - `docs/regen/README.md`
  - `docs/architecture/ARCHITECTURE.md`
  - `docs/RULES.md`
  - `docs/runtime/README.md`
  - `docs/runtime/SCHEMAS.md`
  - `docs/COMPATIBILITY.md`
  - `docs/VERSIONING.md`

Required checkpoint output:

- a concise findings report summarizing current REGEN behaviour on the corpus
- the main cost drivers observed in practice
- the main false-positive regen drivers observed in practice
- the first concrete product calls exposed by the data
- the initial doc-alignment map for later phases

Phase 0 decision gate:

- do the measurements support the planned phase ordering
- are prompt budgeting and dirty propagation still the top next targets
- is the quality harness strong enough to guard later changes
- are the likely doc homes identified clearly enough

The implementer must pause after Phase 0 and reflect findings before Phase 1.

## Phase 1: Evaluation Boundary And Bounded Backend-Capability Contract

Goals:

- make REGEN decisions explicit and testable without invoking the backend
- split "should we regen?" from "perform regen"
- establish the minimal backend-capability contract Phase 2 is allowed to use

Required outcomes:

- explicit evaluation outputs for one node, covering at minimum:
  - path existence / cleanup
  - no-content
  - unchanged
  - structure-only
  - content-changing
  - metadata-only backfill
- explicit execution inputs that consume evaluation results rather than
recomputing policy inline
- a narrower REGEN public service boundary so non-REGEN packages do not depend
on broad engine internals
- one bounded capability contract that Phase 2 must consume instead of using
model-string or Claude-specific prompt heuristics directly

The bounded capability contract must define, at minimum:

- effective prompt budget class or max prompt tokens
- structured-output contract support for the current summary/journal shape
- system-prompt / invocation mode expectations required for REGEN prompt
planning
- any known prompt-overhead class needed for budgeting

Implementation constraint:

- Phase 2 may not invent new backend heuristics outside this contract
- if the contract is insufficient, the implementer must stop and extend it via
checkpoint clearance before proceeding

Required checkpoint output:

- a summary of the extracted decision model
- any behaviour mismatches found between walk-up and wave flows
- the proposed bounded capability contract and its owning code seam
- any newly exposed invariants that later phases must respect
- a doc review note describing whether:
  - `docs/regen/README.md` still matches current implementation after this
  phase
  - `docs/architecture/ARCHITECTURE.md` needs boundary updates
  - any normative rule appears to be changing

Phase 1 decision gate:

- is the decision model explicit enough to safely optimize prompts next
- is the bounded capability contract concrete enough that Phase 2 will not
re-encode Claude-specific policy
- do any current behaviours need to be declared as intentional product rules
before changing them

The implementer must pause after Phase 1 before Phase 2.

## Phase 2: Prompt Assembly And Budgeting Refactor

Goals:

- reduce token burn while preserving or improving summary quality
- stop using a single small fixed budget as the effective limit for every
model and every node shape
- make context inclusion and truncation rules explicit and explainable

Required outcomes:

- prompt budgeting derived from the Phase 1 bounded capability contract rather
than one hard-coded universal budget
- a clearer component budget for at least:
  - instructions
  - global `_core` context
  - direct files
  - child summaries
  - existing summary
- budget-aware chunking so a file is not chunked solely because it exceeds a
static size threshold when raw inclusion would still fit comfortably
- more explicit inclusion priority rules for current node content versus child
summaries versus lower-value carry-forward context
- diagnostics explaining:
  - why a file was deferred to chunking
  - why child summaries were omitted
  - how much budget each component consumed

Required checkpoint output:

- before/after measurements for token burn, chunk rate, and latency on the
baseline corpus
- a summary of which prompt components gained or lost budget
- any quality regressions or ambiguous cases
- any product calls exposed around long-context usage, truncation, or `_core`
handling
- a doc review note describing whether prompt/context sections in
`docs/regen/README.md` and any architecture/runtime docs now need updates

Phase 2 decision gate:

- should REGEN stay conservative by default or use a materially larger budget
envelope
- are the new inclusion priorities producing the desired summary quality
- is chunk-and-merge still correctly positioned as fallback behaviour
- do the docs still describe reality accurately enough to proceed

The implementer must pause after Phase 2 before Phase 3.

## Phase 3: Dirty Detection And Propagation Precision

Goals:

- stop unnecessary node and ancestor regens
- make propagation rules match actual parent dependencies
- remove behaviour asymmetries that survive only for historical reasons

### Target propagation contract

This phase must converge REGEN onto one shared propagation contract for both
single-path and wave execution.

The target contract is:


| Outcome                   | Parent-visible input changed? | Propagate upward? | Reason                                       |
| ------------------------- | ----------------------------- | ----------------- | -------------------------------------------- |
| `regenerated`             | yes                           | yes               | child summary changed on disk                |
| `skipped_no_content`      | yes                           | yes               | child summary/input disappeared              |
| `cleaned_up`              | yes                           | yes               | child summary/input disappeared              |
| `skipped_rename`          | yes                           | yes               | parent structure input changed               |
| `skipped_unchanged`       | no                            | no                | no parent input changed                      |
| `skipped_similarity`      | no                            | no                | summary on disk unchanged                    |
| `skipped_backfill`        | no                            | no                | metadata only; no on-disk input changed      |
| `failed` / raised failure | no                            | no                | failed work must not dirty parent by default |


Implementation rule:

- single-path walk-up and wave processing must converge on this matrix unless a
later cleared checkpoint explicitly records one intentional exception

Required outcomes:

- a more explicit dirty-reason model, for example:
  - direct content changed
  - child summary changed
  - structure-only change
  - metadata-only change
  - cleanup/removal
- one authoritative propagation rule set shared by:
  - single-path walk-up
  - full-tree wave execution
  - queue wave execution
- parent invalidation based on actual parent inputs rather than legacy
continuation shortcuts

Required checkpoint output:

- before/after evidence on false-positive ancestor regen rate
- concrete examples of paths that now skip correctly
- any cases where the desired behaviour remains product-sensitive
- explicit confirmation that the implementation matches the target propagation
matrix above, or a clearly approved exception list
- a doc review note describing whether:
  - `docs/regen/README.md` transition tables or diagrams need changes
  - `docs/architecture/ARCHITECTURE.md` needs updated responsibility or flow
  wording
  - `docs/RULES.md` needs a normative rule update

Phase 3 decision gate:

- does the implementation now match the target matrix
- are any remaining exceptions real product decisions or just legacy carryover
- did this phase trigger any normative doc change that must be resolved before
continuation

The implementer must pause after Phase 3 before Phase 4.

## Phase 4: Artifact-Aware Pipeline Hardening

Goals:

- make REGEN outputs explicit artifacts rather than implicit side effects
- prepare for partial regeneration and artifact-specific policy later
- reduce coupling between summary and journal handling

### Fixed product contract for this phase

This plan pins down the Phase 4 artifact contract to avoid implementer
guesswork.

The intended contract is:

- summary remains the primary required artifact for a successful model-backed
REGEN invocation
- journal remains a secondary durable artifact that may be committed only when
a valid summary payload was produced
- malformed or journal-only structured output is invalid and must fail the run
without producing new durable artifacts
- `skipped_similarity` remains a valid success case in which a non-empty
journal may still be written because the summary payload was valid even
though the summary rewrite was discarded
- `skipped_unchanged` remains a no-call case and does not synthesize journal
output
- if a non-empty journal is part of the result contract for a successful run,
journal commit failure must be surfaced as a run failure rather than silently
ignored

Required outcomes:

- an explicit artifact model for at least:
  - summary
  - journal
- artifact-aware evaluation and execution surfaces
- clearer handling of cases where:
  - summary stays unchanged
  - journal is written
  - one artifact fails while another would otherwise be valid

Required checkpoint output:

- a summary of the resulting artifact model
- explicit confirmation that the Phase 4 fixed product contract above is what
the implementation now does
- evidence that the new shape simplifies later policy rather than just adding
abstraction
- a doc review note describing whether:
  - `docs/regen/README.md` needs artifact-model updates
  - `docs/architecture/ARCHITECTURE.md` needs subsystem-boundary updates
  - `docs/RULES.md` needs wording updates for durable artifact semantics
  - compatibility or versioning docs are affected

Phase 4 decision gate:

- does the implementation match the fixed summary/journal contract above
- is the artifact boundary strong enough to justify later partial regeneration
- are all affected docs still aligned

The implementer must pause after Phase 4 before Phase 5.

## Phase 5: Observability And Cost Diagnostics Closure

Goals:

- make REGEN explain itself well enough for future tuning and operations
- turn existing telemetry and event surfaces into a sharper diagnostic contract

### Fixed observability contract for this phase

This plan pins down the intended diagnostic surfaces to avoid runtime-schema
guesswork.

The intended contract is:

- `operational_events` is the durable surface for semantic lifecycle and
decision events such as why a path ran, skipped, propagated, or failed
- `token_events` is the durable surface for per-call token, duration, and
chunk/non-chunk cost telemetry
- `regen_locks` remains the durable surface for current runtime coordination
and terminal lock state, not for historical decision analytics
- logs remain supplementary and may add detail, but they are not the
authoritative contract the plan depends on
- this phase should prefer strengthening and typing those existing surfaces
rather than creating a new runtime table
- if the phase cannot satisfy its goals without changing runtime schema, the
implementer must stop and seek a new plan/review decision before proceeding

Documentation/versioning rule for this phase:

- changes that alter runtime table shape or supported runtime config shape
require updates to:
  - `docs/runtime/README.md`
  - `docs/runtime/SCHEMAS.md`
  - `docs/VERSIONING.md`
  - `docs/COMPATIBILITY.md`
- if no runtime schema or supported config contract changed, the checkpoint
must record that those docs were reviewed and intentionally left unchanged

Required outcomes:

- durable diagnostics for:
  - why a path ran
  - why a path was skipped
  - why a parent propagated
  - prompt size by component
  - per-artifact token cost
  - chunk count and chunk cost
  - high-churn paths

Required checkpoint output:

- a compact diagnostic report proving the subsystem can now explain its major
decisions
- evidence that baseline and post-change comparisons are now easy to produce
- explicit confirmation that the observability contract above is what the phase
now relies on
- a doc review note describing whether REGEN, runtime, or architecture docs
needed observability wording updates

Phase 5 decision gate:

- is the diagnostic surface sufficient for future tuning
- did the phase stay within the fixed observability contract above
- are the diagnostic docs aligned with the implementation

The implementer must pause after Phase 5 before Phase 6.

## Phase 6: Scheduler And Backend-Capability Readiness

Goals:

- clean up the remaining execution-shape debt after the decision model is
trustworthy
- leave the subsystem ready for later throughput optimization without forcing
early concurrency changes

Required outcomes:

- scheduler logic that depends on explicit REGEN decisions rather than hidden
engine side effects
- extension of the Phase 1 bounded capability contract into a more durable
backend-capability seam for future policy such as:
  - context budget
  - max concurrency
  - startup overhead expectations
  - structured-output reliability
- clearer reasoning around when a single-path walk-up should remain a special
case versus when one shared wave model should be used everywhere

Required checkpoint output:

- a final phase report on what scheduler/backend work is now unblocked
- any remaining product calls intentionally deferred from this plan
- a final doc review note summarizing all docs reviewed and updated across the
implementation

Phase 6 decision gate:

- is REGEN now structurally ready for later parallelism or backend expansion
without reopening earlier phases
- is the doc set aligned enough that the new current state is trustworthy

## Cross-Cutting Documentation Alignment Rule

Every phase must review the relevant doc surfaces before claiming completion.

At minimum, the implementer must explicitly consider:

- `docs/regen/README.md` for current-state REGEN behaviour
- `docs/architecture/ARCHITECTURE.md` for subsystem ownership, boundaries, and
process-flow explanation
- `docs/RULES.md` for cross-cutting invariants, guarantees, and precedence
rules
- `docs/runtime/README.md` and `docs/runtime/SCHEMAS.md` for runtime-state or
telemetry contract changes
- `docs/COMPATIBILITY.md` and `docs/VERSIONING.md` if compatibility or version
scope changes intentionally
- `README.md` only if user-facing operation changes

The correct rule is:

- if behaviour or authority changed, update the authoritative doc for that
subject
- if behaviour did not change, record that the doc was reviewed and remains
accurate

## Cross-Cutting Test Fortress Expectations

Each phase should leave stronger proof behind, not just changed code.

### Unit

- evaluation-result tests with no backend call
- prompt-budget planner tests covering inclusion, truncation, and chunking
- dirty-reason and propagation tests
- artifact-behaviour tests for summary and journal
- diagnostics/telemetry contract tests

### Integration

- real filesystem plus fake backend coverage for changed prompt plans
- parent/child propagation behaviour across nested knowledge trees
- artifact persistence and failure handling coverage

### E2E Or Regression

- unchanged-content no-op protection
- parent false-positive regression cases
- large-context / low-context behaviour on representative corpus cases
- queue scheduling behaviour for equivalent single-path and multi-path inputs

## Overall Acceptance Criteria

The implementation should not be considered complete unless it demonstrates at
least the following:

1. REGEN has a durable baseline/eval harness that can compare token burn,
  latency, chunking, and quality before and after refactor work.
2. The approved-plan notes file contains a durable checkpoint trail for every
  completed phase.
3. Phase checkpoints produced real findings that informed later phase choices,
  rather than being treated as formality.
4. REGEN evaluation can be tested without invoking the active backend.
5. Prompt budgeting is no longer governed solely by the current fixed
  `120k`-token ceiling and static early chunking thresholds.
6. Phase 2 relied on the bounded capability contract established in Phase 1
  rather than on ad hoc model-string heuristics.
7. Single-path and multi-path ancestor propagation match the target matrix in
  this plan unless an explicitly cleared exception is recorded.
8. The REGEN pipeline models summary and journal explicitly as artifacts and
  matches the fixed Phase 4 contract.
9. REGEN diagnostics can explain why a path ran, skipped, propagated, or
  chunked using the fixed Phase 5 contract surfaces.
10. Baseline comparisons show material improvement in at least one of:
  token burn, chunk rate, unnecessary parent regen rate, or wall-clock
    performance, without demonstrated quality regression.
11. REGEN remains backend-agnostic enough that later non-Claude backends can
  use the same decision and execution architecture.
12. The authoritative doc set is reviewed and aligned across REGEN and any
  affected adjacent docs, with explicit justification for docs that were
    reviewed but did not need changes.

## Review Focus

The first review pass for this revision should focus especially on:

- whether the phase gates are now durable and non-self-approving enough for
real execution control
- whether Phase 1 now gives Phase 2 a sufficiently bounded backend-capability
contract
- whether the target propagation matrix is explicit enough to remove
implementer guesswork
- whether the fixed Phase 4 summary/journal contract is acceptable as a product
direction
- whether the fixed Phase 5 observability contract is specific enough to avoid
runtime-schema ambiguity
- whether the sequencing still makes sense under the tightened gate model


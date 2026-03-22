# PLAN_regen-refactor: REGEN Hardening And Refactor

## Status

Planning artifact only. This document defines the phased implementation plan
for hardening and refactoring REGEN after the current-state explainer was added
in `docs/regen/README.md`.

This stage does **not** approve implementation. It records scope, sequencing,
design constraints, product decision points, and acceptance gates for later
review and approval.

## Objective

Raise REGEN to a state where it:

- burns materially fewer unnecessary tokens
- performs materially fewer unnecessary regens
- preserves or improves generated meaning quality
- improves end-to-end regen latency and throughput
- exposes cleaner seams for future artifact specialization and backend
expansion
- becomes easier to reason about, test, and observe

This is not a code-cleanup-only plan. It is a product-and-architecture
hardening plan for derived meaning generation.

## Relationship To Current Docs

This plan is intentionally derived from the current-state baseline now captured
in:

- `docs/regen/README.md`

That REGEN doc is explanatory current state. This plan is the future-facing
execution artifact that proposes how to move from that baseline to a harder,
clearer, and cheaper REGEN architecture.

The current-state doc should be treated as the starting behavioural reference
unless later review artifacts intentionally revise that understanding.

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
concerns in one place and still leaves too much money and latency on the
table.

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
7. queueing and scheduling are serviceable, but later optimization is harder
  than it should be because the decision model is not yet explicit

The result is a subsystem that already works, but still makes important
performance, cost, and maintainability tradeoffs implicitly instead of
explicitly.

## Goals

This plan targets five concrete outcomes.

### 1. Skip More Work

The cheapest regen is the one that never runs. REGEN should get more precise
about when a node is actually semantically dirty and when an ancestor truly has
new inputs.

### 2. Send Better Context

When REGEN does run, prompts should preserve the highest-value context and
avoid lossy chunking or broad truncation unless the budget truly requires it.

### 3. Separate Decision-Making From Execution

The implementation should make it easy to answer:

- why did this path run?
- why did this parent run?
- what was included in the prompt?
- why was content truncated or chunked?
- why was an output persisted or skipped?

### 4. Preserve Or Improve Meaning Quality

Token reduction is not success if summaries become thinner, noisier, or less
trustworthy. Quality protection must be built into the plan rather than treated
as a follow-up concern.

### 5. Prepare For Future Growth

The final architecture should make later work easier:

- artifact-specific regeneration
- backend expansion beyond Claude CLI
- better scheduling and possible same-wave parallelism
- stronger diagnostics and tuning

## Non-goals

- no broad redesign of sync lifecycle ownership outside REGEN-relevant seams
- no default portable-brain format change unless later review proves it is
unavoidable
- no immediate rollout of same-wave parallel LLM execution in the early phases
- no assumption that larger context windows should always be fully consumed
- no commitment to split summary and journal into separate model calls unless
later phase review approves that product change
- no broad observability platform or dashboard project
- no generic workflow engine or plugin system
- no backend lock-in to Claude-specific semantics

## Planning Assumptions And Proposed Product Direction

These are the proposed planning assumptions for review. They should be
challenged during review, but the implementation plan needs a concrete
direction to sequence work.

### 1. Quality Is A Hard Gate

The plan assumes "maintain or improve meaning quality" is a harder constraint
than "minimize tokens at any cost." Cost and latency wins that materially
degrade summaries should be rejected.

### 2. REGEN Policy Should Be Backend-Agnostic

The current default REGEN model is Claude Sonnet 4.6, but the architecture
should not become more Claude-specific. Budgeting, scheduling, and execution
should evolve toward model-aware and backend-aware policies rather than
hard-coded Claude-only assumptions.

### 3. Long Context Is A Capability, Not A Default Target

The plan assumes REGEN should become model-aware and capable of exploiting
larger context windows when beneficial, but it should not simply replace
today's conservative `120k` budget with "use 1M by default."

### 4. Parent Propagation Should Follow Actual Parent Inputs

The plan assumes the target model is dependency-based propagation:

- parent REGEN should depend on what the parent actually consumes
- metadata-only child changes should not dirty the parent
- structure-only and content-changing rules should be explicit and testable

The exact final propagation matrix should still be reviewable.

### 5. Observability Must Arrive Early Enough To Guide Refactoring

The plan assumes REGEN should explain itself before aggressive optimization is
attempted. Baseline metrics and decision diagnostics are part of the early
work, not a final reporting phase.

## Scope

In scope for the implementation stage:

- establishing REGEN baselines for cost, latency, and quality
- separating evaluation from execution
- refactoring prompt assembly and context budgeting
- tightening dirty detection and parent propagation rules
- making summary and journal artifact boundaries explicit in the pipeline
- strengthening REGEN observability and diagnostic explainability
- narrowing and clarifying REGEN service seams
- limited scheduler and backend-capability work needed to prepare later
optimization safely
- documentation and tests required to keep the new behaviour intentional

## Workstreams

The implementation should be organized into six phases.

### Phase 0: Baseline, Corpus, And Success Metrics

Goals:

- establish a measurable baseline before structural changes begin
- make quality protection concrete instead of aspirational
- define what "better" means per node and per run

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

Implementation notes:

- keep the corpus fictional and repository-safe
- prefer committed fixtures and deterministic tests over one-off local notes
- prompt capture and telemetry should be usable for baseline creation, but the
plan should not depend on manual log reading as the only proof

Validation gate:

- the repository has a durable REGEN benchmark/eval baseline
- reviewers can compare later phases against concrete cost, latency, and
quality evidence

### Phase 1: Separate Evaluation From Execution

Goals:

- make REGEN decisions explicit and testable without invoking the backend
- split "should we regen?" from "perform regen"
- converge the single-path and multi-path flows onto shared decision surfaces

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
- clearer ownership boundaries for:
  - state loading
  - dirty classification
  - prompt planning
  - LLM invocation
  - persistence and terminal state recording
- a narrower REGEN public service boundary so non-REGEN packages do not depend
on broad engine internals

Validation gate:

- unit tests can exercise REGEN evaluation without model calls
- a reviewer can identify one shared decision model feeding both walk-up and
wave execution
- `regen.engine` is materially smaller or more decomposed by responsibility

Checkpoint review focus:

- whether evaluation outputs are concrete enough to remove implementer
guesswork in later phases
- whether the REGEN service boundary is becoming narrower rather than broader

### Phase 2: Prompt Assembly And Budgeting Refactor

Goals:

- reduce token burn while preserving or improving summary quality
- stop using a single small fixed budget as the effective limit for every
model and every node shape
- make context inclusion and truncation rules explicit and explainable

Required outcomes:

- model-aware or capability-aware prompt budgeting instead of one hard-coded
universal budget
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
- logging and telemetry that explain:
  - why a file was deferred to chunking
  - why child summaries were omitted
  - how much budget each component consumed

Implementation constraints:

- preserve deterministic prompt assembly
- keep `_core` handling explicit and testable
- do not assume "more context" automatically means "better summary"
- if token estimation remains approximate in an interim step, keep the design
open for later exact token counting

Validation gate:

- baseline comparisons show a lower chunk rate and/or lower token burn on the
corpus without quality regression
- the prompt planner can explain its inclusion decisions per node
- tests cover long-context-capable models without hard-coding Claude-only
assumptions into REGEN policy

Checkpoint review focus:

- whether the plan is truly preserving higher-value raw context first
- whether the new budgeting rules are explicit enough to be debugged and tuned

### Phase 3: Dirty Detection And Propagation Precision

Goals:

- stop unnecessary node and ancestor regens
- make propagation rules match actual parent dependencies
- remove current behaviour asymmetries that survive only for historical
reasons

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
- clearer handling of folder moves, file renames, add/delete churn, and
metadata backfill

Implementation direction:

- the current wave semantics should be treated as the stronger conceptual
baseline where parent propagation depends on parent-visible input changes
- any intentional exception must be explicit and test-covered

Validation gate:

- `regen_path()` and wave processing no longer disagree on equivalent
propagation cases without an intentional documented exception
- false-positive ancestor regen decreases on the corpus
- rename-only and metadata-only cases remain cheap and predictable

Checkpoint review focus:

- whether propagation semantics are now dependency-based and explainable
- whether the new dirty-reason model is concrete enough for future scheduling
and artifact work

### Phase 4: Artifact-Aware Pipeline Hardening

Goals:

- make REGEN outputs explicit artifacts rather than implicit side effects of
one broad flow
- prepare for partial regeneration and artifact-specific policy later
- reduce coupling between summary and journal handling

Required outcomes:

- an explicit artifact model for at least:
  - summary
  - journal
- artifact-aware evaluation and execution surfaces, even if the first revision
still keeps some shared invocation behaviour
- artifact-specific skip and persistence reasoning
- clearer handling of cases where:
  - summary stays unchanged
  - journal is written
  - one artifact fails while another would otherwise be valid

Implementation note:

- this phase is about architecture first, not necessarily about immediately
splitting summary and journal into separate model requests
- if review concludes that summary and journal should remain coupled in one
invocation for now, the pipeline should still model them explicitly as
distinct artifacts

Validation gate:

- the artifact model is explicit in code and tests
- summary/journal behaviour no longer depends on hidden coupling inside one
large function
- later artifact-specific caching or partial regeneration can be added without
reopening the whole engine design

Checkpoint review focus:

- whether artifact boundaries are now real enough to justify the added
abstraction
- whether the phase stayed bounded and did not balloon into a full product
redesign

### Phase 5: Observability And Cost Diagnostics Closure

Goals:

- make REGEN explain itself well enough for future tuning and operations
- turn existing telemetry and event surfaces into a sharper diagnostic contract

Required outcomes:

- stronger typed or catalog-backed REGEN-facing event usage where needed
- durable diagnostics for:
  - why a path ran
  - why a path was skipped
  - why a parent propagated
  - prompt size by component
  - per-artifact token cost
  - chunk count and chunk cost
  - high-churn paths
- tests that lock the REGEN-facing diagnostic contract strongly enough for
later refactors

Implementation note:

- this phase should build on the operational event hardening already completed
elsewhere in the repository rather than duplicating that project

Validation gate:

- baseline and post-change comparisons can be produced from in-repo telemetry
and tests without relying on ad hoc log archaeology
- reviewers can prove key REGEN decisions from durable data

Checkpoint review focus:

- whether the new diagnostics are decision-grade rather than merely verbose
- whether the observability surface is precise enough to support later
scheduler and backend work

### Phase 6: Scheduler And Backend-Capability Readiness

Goals:

- clean up the remaining execution-shape debt after the decision model is
trustworthy
- leave the subsystem ready for later throughput optimization without forcing
early concurrency changes

Required outcomes:

- scheduler logic that depends on explicit REGEN decisions rather than hidden
engine side effects
- backend-capability seams for future policy such as:
  - context budget
  - max concurrency
  - startup overhead expectations
  - structured-output reliability
- clearer reasoning around when a single-path walk-up should remain a special
case versus when one shared wave model should be used everywhere

Implementation note:

- same-wave parallel execution is not required in this plan's first approved
implementation unless later review chooses to include it
- the phase should prepare the seam for later parallelism rather than force it
prematurely

Validation gate:

- REGEN scheduling logic is simpler and more explicit than the current split
- later backend diversification or same-wave parallelism would not require
reopening prompt or dirty-detection architecture

Checkpoint review focus:

- whether the phase stayed preparatory and bounded
- whether the subsystem is genuinely easier to extend after the earlier
phases

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

## Documentation Expectations

The implementation derived from this plan should update docs intentionally.

At minimum, later implementation is expected to update:

- `docs/regen/README.md` for the new current state
- `docs/architecture/ARCHITECTURE.md` where subsystem boundaries or
responsibilities change
- `docs/RULES.md` only if a normative cross-cutting rule changes
- `docs/VERSIONING.md` and `docs/COMPATIBILITY.md` only if contract or
compatibility policy changes intentionally

## Review Decision Points

The first review pass for the revision derived from this artifact should
challenge these specific product and architecture choices rather than letting
them hide inside implementation:

1. how aggressively should model-aware budgeting exploit long context by
  default
2. whether one dependency-based propagation model should replace the current
  walk-up versus wave asymmetry entirely
3. whether summary and journal should stay one invocation in the first
  artifact-aware phase
4. whether similarity-based non-rewrite remains the right anti-churn policy
  once evaluation and artifact boundaries are clearer
5. how much REGEN telemetry is necessary to be operationally useful without
  becoming observability sprawl

## Sequencing

Recommended order:

1. Phase 0: baseline, corpus, and success metrics
2. Phase 1: separate evaluation from execution
3. Phase 2: prompt assembly and budgeting refactor
4. Phase 3: dirty detection and propagation precision
5. Phase 4: artifact-aware pipeline hardening
6. Phase 5: observability and cost diagnostics closure
7. Phase 6: scheduler and backend-capability readiness

Phases 2 and 3 may iterate together in practice, but the approved plan should
still require Phase 1 first so later changes are grounded in explicit decision
surfaces.

## Overall Acceptance Criteria

The implementation should not be considered complete unless it demonstrates at
least the following:

1. REGEN has a durable baseline/eval harness that can compare token burn,
  latency, chunking, and quality before and after refactor work.
2. REGEN evaluation can be tested without invoking the active backend.
3. Prompt budgeting is no longer governed solely by the current fixed
  `120k`-token ceiling and static early chunking thresholds.
4. Single-path and multi-path ancestor propagation no longer disagree for
  equivalent dependency cases without an intentional documented exception.
5. The REGEN pipeline models summary and journal explicitly as artifacts.
6. REGEN diagnostics can explain why a path ran, skipped, propagated, or
  chunked using durable repository-supported evidence.
7. Baseline comparisons show material improvement in at least one of:
  token burn, chunk rate, unnecessary parent regen rate, or wall-clock
   performance, without demonstrated quality regression.
8. REGEN remains backend-agnostic enough that later non-Claude backends can
  use the same decision and execution architecture.

## Review Focus

The first review pass for the revision derived from this artifact should focus
especially on:

- whether the phase boundaries are specific enough that implementers are not
left to invent the product direction
- whether quality protection is concrete enough to prevent "cheaper but worse"
REGEN outcomes
- whether the prompt-budgeting phase is explicit enough to take advantage of
newer long-context models without blindly maximizing context
- whether the propagation phase is tightening real dependency semantics rather
than just moving code around
- whether the artifact-aware phase is sufficiently bounded and justified
- whether the plan leaves REGEN materially easier to extend, debug, and
optimize than the current state


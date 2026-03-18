# plan_runtime-release-alignment_2

## Status

Plan revision 2.

This artifact supersedes `docs/plans/PLAN_runtime-release-alignment.md` for
review purposes and addresses the findings in
`docs/plans/plan_runtime-release-alignment_review_1_2026-03-18.md`.

This stage is still planning only. It does **not** approve implementation and
does **not** modify earlier plan or review artifacts.

## Objective

Restore release-oriented confidence in runtime behavior after the `v25`
runtime-schema expansion by:

- separating real bug fixes from broader runtime-surface growth
- re-centering the system on the documented rule that portable state is
  authoritative
- explicitly deciding what to keep, what to revert, and what to defer
- requiring per-table, per-consuming-workflow proof before any retained runtime
  state is allowed to remain in scope

The outcome of this plan is not direct implementation. The outcome is a
reviewable, narrowed disposition that must be approved before any follow-on
implementation work begins.

## Trigger

This revision responds to:

- the approved runtime-failure-hardening bundle in
  `docs/plans/plan_runtime-failure-hardening_3_approved_2026-03-18T15-47-10.md`
  being intentionally scoped as a bug-fix and hardening bundle
- the implemented `v25` bump in commit `6d7eb76` introducing additional runtime
  tables and workflow hooks beyond that narrow scope
- the review finding that the first release-alignment plan still delegated the
  decisive narrowing call to implementation
- explicit architectural guidance from the user that the runtime DB must remain
  "pluggable" to the portable brain and must never assume it is the only DB
  that has ever backed that brain

## Stable Invariants vs Provisional Claims

This revision draws a hard distinction between stable authority inputs and
table-specific claims introduced by the same change under review.

### Stable authority inputs

These are the normative invariants that predate or survive the current dispute:

- `docs/RULES.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/GLOSSARY.md`
- `docs/runtime/README.md`
- `AGENTS.md`
- `docs/plans/README.md`

These inputs establish the rules that matter here:

- the filesystem is authoritative
- durable portable state lives in the brain root
- runtime state is machine-local and rebuildable
- deleting runtime artifacts must not damage the brain
- runtime schema versioning is an implementation concern, not the definition of
  the portable brain

### Provisional table-specific claims

The table-specific text added or expanded by commit `6d7eb76` must be treated
as provisional until this plan closes:

- `docs/runtime/SCHEMAS.md` entries that describe the `v25` additions as part
  of the current runtime schema
- `docs/architecture/ARCHITECTURE.md` passages that classify those tables and
  workflows as acceptable runtime ownership

For this plan, those texts are claims to re-prove, not evidence for retention.

### Code and test inputs under review

The current implemented behavior must still be examined in:

- commit `6d7eb76` (`Harden regen and runtime ownership boundaries`)
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/application/reconcile.py`
- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/application/query_index.py`
- `src/brain_sync/application/sync_events.py`
- `src/brain_sync/application/source_state.py`
- `tests/unit/test_state.py`
- `tests/unit/test_query_index.py`
- `tests/unit/test_runtime_operational_events.py`
- `tests/compat/test_brain_format_v1.py`
- `tests/e2e/test_git_clone_scenario.py`

## Architecture Baseline for This Review

This plan adopts the following architectural baseline for all narrowing and
validation decisions:

- portable brain state always wins over runtime DB state
- the runtime DB may optimize and observe, but it must not define durable truth
- the current product posture is one active brain per machine-local config
  directory, not multi-brain concurrency within one runtime
- the same portable brain may still be modified elsewhere while this machine is
  idle
- therefore startup and reconcile must re-establish truth from the portable
  brain and filesystem, not from local runtime assumptions
- runtime state must remain "pluggable" to the portable brain: the DB on one
  machine must not assume it is the exclusive long-term backing store for that
  brain

### Ownership baseline for regen

This revision also adopts the following ownership direction as a design
constraint for any retained regen hardening work:

- guarded ownership semantics remain in force
- `save_regen_lock()` must not become an implicit acquisition or transfer path
- ownership claim and transfer must remain explicit
- the preferred model is engine-owned or queue-owned guarded acquisition close
  to the unit of regen work, not permissive first-write ownership through a
  persistence helper

If later review wants to refine the exact engine vs queue boundary, it may do
so, but this plan does not allow a fallback to permissive ownership writes.

## Current Findings

### 1. Scope expanded beyond the approved bug bundle

The implemented `v25` work added these new runtime tables:

- `dirty_knowledge_paths`
- `path_observations`
- `invalidation_tokens`
- `operational_events`

and threaded them into runtime decision paths for reconcile, watcher, and
query-index behavior.

That may include useful work, but it is broader than the bug-fix bundle that
was approved.

### 2. Runtime-only classification is necessary but not sufficient

A table being machine-local is not enough to justify retention.

The release question is stricter:

- can stale, missing, or divergent local rows suppress work that portable state
  requires?
- can a machine-local optimization become a hidden correctness dependency?
- can another machine legitimately observe the same brain and leave this local
  DB stale without breaking future behavior here?

### 3. Existing tests prove rebuildability, but not enough multi-machine safety

The current suite does prove:

- in-process runtime isolation through `BRAIN_SYNC_CONFIG_DIR`
- `v23` to `v25` runtime migration
- clone-without-DB rebuild from portable manifests and sidecars

It does **not yet clearly prove**:

- divergent machine-local runtime DBs for the same portable brain are safe
- stale rows in retained cache tables cannot suppress required work
- retained runtime surfaces remain advisory in every consuming workflow

### 4. Full RCA is still required

This plan treats the current evidence as enough to justify tightening and
narrowing. It does not yet treat that evidence as enough to fully explain every
observed breakage. A retrospective and RCA phase remains mandatory.

## Provisional Release Disposition

This classification is intentionally conservative and must be validated in the
phases below.

### Narrow bug-fix keep candidates

These are plausibly aligned with the original approved workstreams:

- logging rollover validation and any narrow residual logging fix
- guarded `regen_locks` ownership and replay-safety fixes
- bounded WinError 5 lock classification and deferral behavior
- Confluence `404` classification into the existing missing-source lifecycle
- `documents.url` caller identification and any narrow fix at the real owner

### Keep only by explicit scope decision

- `operational_events`

Retention conditions:

- append-only
- machine-local
- non-authoritative
- failure-to-write is non-fatal
- not required for correctness
- explicitly accepted as remaining in `0.6.0` scope

### Provisional cache-like surfaces under dispute

These remain provisional until per-table and per-consumer proof is complete:

- `dirty_knowledge_paths`
- `path_observations`
- `invalidation_tokens`

Default narrowing posture:

- revert or defer unless their safety is positively proven
- no retention on the basis of convenience or likely usefulness

## Pre-Release Rollback and Compatibility Policy

This revision makes the rollback posture explicit.

Because `0.6.0` is unreleased and the only affected runtime DBs are
developer/tester machine-local state:

- the branch is **not** required to preserve all currently created local `v25`
  DBs in place if narrowing removes or disables disputed runtime surfaces
- explicit runtime DB reset or rebuild is an allowed and preferred narrowing
  path for developer/tester machines
- portable brain compatibility remains mandatory
- no new runtime schema bump is allowed as part of this narrowing
- if narrowed behavior no longer accepts a previously created local DB shape,
  the product may reset or rebuild that local runtime DB rather than attempt an
  in-place downgrade

Release-facing implication:

- the supported user contract remains the portable brain contract
- the narrowed branch may require local runtime rebuild during development
  without violating that contract

Required documentation consequence:

- any narrowed branch must state clearly whether runtime startup resets or
  rebuilds pre-narrowing local DBs, and under what detection rule

## Non-Negotiable Constraints

The following rules apply throughout this plan:

- no new runtime schema bump without separate approval
- no new runtime persistence surface may be introduced while this plan is open
- no behavior may remain whose safety depends on "the local runtime DB is
  probably current enough"
- any retained runtime cache must be advisory only
- any retained runtime cache must yield to portable truth and filesystem truth
- any table-specific docs added by `6d7eb76` remain provisional until this plan
  closes
- implementation may not begin until a post-narrowing plan artifact is reviewed
  and approved

## Phased Plan

### Phase 0: Freeze and Evidence Inventory

Purpose:

- stop further runtime-surface drift
- produce a stable inventory of what `v25` actually changed

Actions:

- freeze additional runtime-state expansion
- inventory each `v25` runtime table, helper, and consuming workflow
- map each item to:
  - original bug evidence
  - approved workstream
  - current code owner
  - current docs that describe it

Validation:

- reviewers can audit the changed runtime surface without re-reading the full
  commit diff

Exit criteria:

- a concrete inventory exists

### Phase 1: Retrospective and RCA

Purpose:

- distinguish known breakages from hypotheses and overreach risk

Actions:

- review the original logs, approved bug plan, and implemented diff
- classify each concern into:
  - confirmed user-visible failure
  - validated overreach risk
  - open hypothesis
- identify where the implementation exceeded the approved bug scope

Validation:

- no later keep or revert decision depends only on intuition
- every major claim is tagged as evidence-backed or hypothesis-backed

Exit criteria:

- the retrospective clearly separates known failures from open questions

### Phase 2: Runtime Authority Audit

Purpose:

- prove that each retained runtime surface remains non-authoritative

Actions:

- classify each table as:
  - correctness-critical
  - advisory optimization
  - observability only
  - removable
- define stale-state behavior for each table
- define delete-and-rebuild behavior for each table
- define divergent-other-machine behavior for each table

Required outputs:

- one disposition row per runtime table with:
  - owner
  - authoritative input
  - rebuild source
  - stale-state failure mode
  - divergent-machine failure mode
  - proposed keep/revert/defer outcome

Validation:

- no table may remain with an undefined stale-state or divergent-machine
  behavior story

Exit criteria:

- the authority model is explicit and auditable

### Phase 3: Concrete Narrowing Decision

Purpose:

- produce the actual keep/revert/defer outcome before implementation

Actions:

- decide for each disputed surface whether it is:
  - kept now
  - reverted now
  - deferred to a later explicit plan
- define exact rollback handling for local developer/tester DBs
- define the narrowed supported runtime surface after the decision

Required outputs:

- a concrete keep/revert/defer table
- a concrete local runtime rebuild/reset policy
- a concrete list of docs that remain provisional vs docs that may be updated
  after approval

Validation:

- no contested runtime surface remains in "decide during implementation" state

Exit criteria:

- the narrowed disposition is complete and reviewable

## Hard Gate After Phase 3

Phase 3 does **not** authorize implementation.

Instead, completion of Phases 0-3 must produce:

- a new narrowed plan revision, or equivalent planner artifact, that records
  the actual keep/revert/defer decisions and rollback posture
- a new reviewer pass over that narrowed disposition
- a separate approval artifact before any Phase 4 implementation begins

No implementation work may begin from this revision alone.

### Phase 4: Narrow Workstream Implementation

Purpose:

- implement only the already-approved narrowed scope

Allowed workstreams:

- logging rollover validation and any narrow residual fix
- `regen_locks` guarded ownership and replay discipline
- bounded WinError 5 lock classification and deferral
- Confluence `404` missing-state integration
- any explicitly approved retention of `operational_events`
- only those cache-like runtime surfaces that survive the post-Phase-3 review

Rules:

- no re-expansion of runtime persistence surface
- no hidden architectural decisions during execution
- no new runtime tables or files without separate approval

Validation:

- each implementation change maps to an approved narrowed decision

Exit criteria:

- code changes remain within the approved narrowed scope

### Phase 5: Per-Table, Per-Workflow Validation

Purpose:

- prove retained runtime surfaces are safe in the exact workflows that consume
  them

Required negative-proof matrix:

- `dirty_knowledge_paths`
  - startup reconcile
  - watcher-driven enqueue behavior
  - rename or move propagation
- `path_observations`
  - startup reconcile candidate narrowing
  - post-reconcile observation refresh
  - divergent-other-machine stale observation behavior
- `invalidation_tokens`
  - query-index invalidation
  - query-index rebuild and reload
  - stale token behavior across machine-local divergence
- `operational_events`
  - append-only persistence
  - non-fatal write failure
  - proof that no correctness path reads it as authority

For every retained table and every consuming workflow above, tests must prove:

- stale rows do not suppress required work
- missing rows do not suppress required work
- divergent rows on another machine do not suppress required work
- table deletion or DB rebuild restores correctness

Additional required tests:

- two different `BRAIN_SYNC_CONFIG_DIR`s against the same portable brain
- portable state changed elsewhere while local runtime DB remains stale
- runtime DB deletion and rebuild recovery
- retained observability writes fail without changing correctness

Exit criteria:

- each retained table has passed per-workflow negative proof

### Phase 6: Documentation and Governance Tightening

Purpose:

- align the docs only after narrowing is approved and validated

Actions:

- update provisional schema and architecture text only after the narrowed
  design is approved
- record the final keep/revert/defer outcome and rationale
- add explicit release-hardening guidance that runtime-surface expansion
  requires:
  - named user-visible problem
  - authoritative input analysis
  - stale/divergent-state behavior
  - exact validating tests

Validation:

- docs no longer self-justify disputed runtime surfaces
- future plans can detect and stop this category of scope drift earlier

Exit criteria:

- final docs reflect approved and validated runtime behavior only

## Required Validation Matrix

Every retained runtime surface must answer all of the following before
approval:

- What portable truth does it depend on?
- What happens if its local row is stale?
- What happens if its local row is missing?
- What happens if another machine has divergent local state for the same
  portable brain?
- What happens if the runtime DB is rebuilt?
- Can failure to write this state affect correctness, or only observability or
  performance?
- Which exact automated tests prove those claims for each consuming workflow?

If any retained surface cannot answer those questions, it is not release-ready.

## Review Focus

Reviewers should challenge this revision on:

- whether the hard gate after Phase 3 is explicit enough
- whether the split between stable invariants and provisional `6d7eb76` claims
  is clear enough
- whether the pre-release local DB rebuild policy is concrete enough
- whether the per-table, per-workflow proof burden is strong enough
- whether the architecture baseline correctly captures the "pluggable runtime"
  model for a portable brain that may be modified elsewhere
- whether any key narrowing or rollback decision still leaks to implementation

## Exit Criteria

This revision is ready for approval only when a reviewer can confirm that it:

- removes implementer discretion over the decisive keep/revert call
- treats `6d7eb76` table-specific schema and architecture text as provisional
- defines an explicit unreleased-local-DB rollback policy
- requires per-table, per-consuming-workflow negative proof before retention
- preserves the rule that runtime DB state is machine-local and
  non-authoritative
- requires a second review and approval gate before any implementation begins

If review feedback identifies further gaps, the planner should create another
new revision rather than editing this file in place.

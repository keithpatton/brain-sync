# PLAN_runtime-release-alignment

## Status

Canonical root plan.

This artifact is planning only. It does **not** approve implementation and does
**not** modify or supersede existing approval artifacts by itself.

## Objective

Restore release-oriented confidence in runtime behavior after the `v25`
runtime-schema expansion, while preserving real bug fixes and re-centering the
system on the documented contract that:

- the filesystem and portable brain state are authoritative
- machine-local runtime state is rebuildable and non-portable
- a runtime DB on one machine must not become the hidden source of truth for
  the same brain on another machine

The immediate goal is not to defend or condemn every recent change. The goal is
to produce a rigorous alignment path that determines what to keep, what to
revert, and what to fix before stable release.

## Trigger

This plan is derived from three facts that now need to be reconciled:

- the approved runtime-failure-hardening bundle in
  `docs/plans/plan_runtime-failure-hardening_3_approved_2026-03-18T15-47-10.md`
  was scoped as a bug-fix and hardening bundle, not as a broad runtime-state
  expansion
- the implemented `v25` bump in commit `6d7eb76` added multiple new runtime DB
  tables and new cross-module runtime decision paths
- release confidence is now reduced because the implemented surface appears
  materially wider than the original request, especially during an ongoing
  architecture refactor

## Authoritative Inputs

Implementation and review for this plan must treat the following as primary
constraints:

- `docs/RULES.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/GLOSSARY.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`
- `docs/plans/README.md`

This plan also depends on the current approved and implemented context in:

- `docs/plans/plan_runtime-failure-hardening_3_approved_2026-03-18T15-47-10.md`
- commit `6d7eb76` (`Harden regen and runtime ownership boundaries`)
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/application/reconcile.py`
- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/application/query_index.py`
- `src/brain_sync/application/sync_events.py`
- `tests/unit/test_state.py`
- `tests/unit/test_query_index.py`
- `tests/unit/test_runtime_operational_events.py`
- `tests/compat/test_brain_format_v1.py`
- `tests/e2e/test_git_clone_scenario.py`

## Contract Baseline

The current higher-authority rules already define the expected runtime posture:

- `docs/RULES.md` says the filesystem is authoritative and runtime state must be
  reconstructable from portable state
- `docs/RULES.md` says deleting runtime artifacts must never damage the brain
- `docs/RULES.md` says the runtime DB is machine-local, not inside the brain
  root, and that most runtime tables are non-authoritative and rebuildable
- `docs/VERSIONING.md` says runtime schema versioning is an engineering concern,
  not the public definition of what version of brain this is
- `docs/runtime/SCHEMAS.md` says supported runtime schema versions should
  migrate in place, but rebuild remains the fallback for missing, corrupt, or
  unsupported runtime state

This plan treats those statements as normative. Any implementation that cannot
be shown to satisfy them must be narrowed, redesigned, or removed.

## Current Findings

### 1. The implemented surface appears broader than the approved bug bundle

The approved runtime-failure-hardening plan explicitly scoped out a broad
runtime persistence redesign. The implemented `v25` work nevertheless added:

- `dirty_knowledge_paths`
- `path_observations`
- `invalidation_tokens`
- `operational_events`

and threaded those tables into reconcile, query-index, watcher, and runtime
event workflows.

This does not automatically make the work wrong, but it does mean the current
implementation should be treated as a scope expansion that now requires its own
release-alignment review.

### 2. The new tables are documented as runtime-only, but not all are equally low-risk

On paper, the current docs classify the new `v25` tables as machine-local and
rebuildable:

- `operational_events` is local observability
- `dirty_knowledge_paths`, `path_observations`, and `invalidation_tokens` are
  described as advisory runtime coordination state

That is directionally consistent with the documented rules.

However, the risk is not only whether the tables are portable. The risk is
whether they influence behavior in a way that can suppress needed work when the
same brain is opened against a different machine-local runtime DB or against a
stale local DB.

### 3. Existing validation is meaningful but incomplete for the release concern

Current tests do prove several important properties:

- in-process tests isolate `BRAIN_SYNC_CONFIG_DIR`, so the suite does not touch
  the real runtime DB
- `tests/unit/test_state.py` and `tests/compat/test_brain_format_v1.py` prove
  supported migration from `v23` to `v25`
- `tests/e2e/test_git_clone_scenario.py` proves that a clone with no runtime DB
  can rebuild state from portable manifests and sidecars

But the current suite does **not yet clearly prove** the most important
cross-machine trust boundary:

- two different machine-local runtime DBs may back the same portable brain over
  time
- stale runtime coordination state must not cause false "nothing changed"
  outcomes
- runtime caches must not suppress reconcile, regen, or query-index updates
  that portable state and filesystem truth require

### 4. A full retrospective is still required to identify actual breakage causes

The current evidence is enough to say:

- scope likely expanded
- risk increased
- coverage is incomplete for the release boundary

It is **not** enough to claim the precise root cause of every breakage.

A full retrospective and RCA pass is therefore required before final keep or
revert decisions are treated as closed.

### 5. The release posture must now favor narrowness over convenience

Because `0.6.0` has not yet been released, the correct bias is:

- no new runtime behavior should remain in the release candidate unless it is
  clearly justified
- ambiguity should resolve toward rollback or deferral, not toward optimistic
  retention
- no non-obvious retained change should proceed without explicit approval

## Preliminary Change Classification

This classification is provisional and must be validated in the plan phases
below.

### Candidate keep set

These changes are plausibly aligned with the original bug bundle, subject to
proof:

- logging rollover validation and any narrow residual logging fix
- guarded ownership and replay-safety fixes around `regen_locks`
- bounded WinError 5 lock classification and deferral behavior
- Confluence `404` classification into the existing missing-source lifecycle

### Candidate keep only if separately justified

These changes may be acceptable, but they must be justified as intentionally
retained release scope rather than bug-bundle incidental expansion:

- `operational_events` as append-only, non-fatal, machine-local observability

Retention conditions:

- must remain strictly non-authoritative
- must not be required for correctness
- must have non-fatal failure behavior
- must have targeted docs and tests that prove those properties

### Candidate revert set

These changes should be treated as rollback candidates unless validated by a
separate, explicit release justification:

- `dirty_knowledge_paths`
- `path_observations`
- `invalidation_tokens`
- any runtime decision path that relies on those tables for correctness rather
  than optimization
- any query-index or reconcile behavior that cannot prove stale runtime state
  will not suppress required work

### Investigate before deciding

These items need focused scope confirmation before keep or revert:

- whether any part of `child_discovery_requests` is entangled with the `v25`
  work even though its schema introduction predates `v25`
- whether any remaining `documents.url` write path exists in normal execution
- whether retained observability should stay in the release branch or be
  deferred behind a smaller follow-up plan

## Non-Negotiable Release Constraints

The following rules apply to every phase of this plan:

- no new runtime schema bump without explicit follow-up approval
- no additional runtime persistence surface may be introduced while this plan
  is open
- no behavior whose safety depends on "the runtime DB is probably fresh enough"
  may ship without explicit approval
- any retained runtime cache must be advisory only and must yield to portable
  state and filesystem truth
- if a release-safe proof cannot be produced, the change must be reverted or
  deferred

## Phased Plan

### Phase 0: Freeze and Evidence Capture

Purpose:

- stop additional scope drift
- capture a stable baseline for review and rollback decisions

Actions:

- declare a temporary freeze on further runtime-schema and runtime-state
  behavior expansion
- record the exact `v25` schema additions, touched modules, and tests added in
  commit `6d7eb76`
- map each newly introduced table, helper, and workflow hook to:
  - the original bug evidence it was meant to address
  - the approved workstream it claims to satisfy
  - the runtime contract it relies on

Validation:

- produce an implementation-facing inventory that reviewers can audit without
  reading the full commit diff
- confirm no new schema or runtime coordination features land while the plan is
  under review

Exit criteria:

- a stable inventory exists
- no unresolved "what changed?" ambiguity remains

### Phase 1: Retrospective and RCA

Purpose:

- separate observed breakages from inferred causes
- avoid cargo-cult rollback or cargo-cult retention

Actions:

- perform a retrospective over the original log evidence, the approved plan,
  and the implemented diff
- classify each observed bug or concern into:
  - confirmed user-visible breakage
  - likely over-implementation risk
  - speculative concern that still needs proof
- identify where the implementation deviated from the approved plan's intended
  scope

Required outputs:

- a short RCA artifact or review input that lists:
  - known failures
  - hypotheses
  - evidence gaps
  - non-hypothetical findings

Validation:

- no retention or rollback decision is justified only by intuition
- every major claim is tagged as evidence-backed or hypothesis-backed

Exit criteria:

- reviewers can tell what is known, what is suspected, and what remains open

### Phase 2: Runtime Authority and Multi-Machine Safety Audit

Purpose:

- prove that runtime state remains advisory and machine-local
- make the home/work same-brain workflow a first-class validation target

Actions:

- audit each retained runtime table and classify it as:
  - correctness-critical
  - advisory optimization
  - observability only
  - removable
- write explicit invariants for multi-machine behavior:
  - opening the same brain with a different `BRAIN_SYNC_CONFIG_DIR` must remain
    safe
  - stale runtime DB state must not suppress reconcile or regen that portable
    state requires
  - deleting the runtime DB must restore correct behavior without hidden loss
  - runtime observability history may be lost without correctness impact

Required outputs:

- a table of each runtime artifact with:
  - owner
  - authoritative input
  - rebuild source
  - stale-state failure mode
  - release disposition proposal

Validation:

- design review confirms that no retained table acts as hidden durable truth
- any table that cannot explain its stale-state behavior is marked for revert
  or redesign

Exit criteria:

- the runtime authority model is explicit enough to review line-by-line against
  `docs/RULES.md`

### Phase 3: Keep/Revert Decision and Narrowing

Purpose:

- reduce the release branch to a justified runtime surface

Actions:

- split the implemented `v25` changes into three buckets:
  - keep now
  - revert now
  - defer behind a later explicit plan
- revert any advisory table or code path that lacks a release-safe proof
- if `operational_events` is retained, keep it only as append-only,
  machine-local, non-fatal observability
- if `dirty_knowledge_paths`, `path_observations`, or `invalidation_tokens`
  are retained, require explicit approval that they remain in release scope

Validation:

- each retained surface has a written reason tied to a user-visible problem or
  release-approved capability
- each reverted surface has a clean rollback path and schema consequence
  documented

Exit criteria:

- there is no ambiguous "maybe we need this later" runtime behavior left in the
  release branch

### Phase 4: Bug-Fix Re-Implementation by Narrow Workstream

Purpose:

- address the original bug classes directly, with smaller and more reviewable
  changes

Workstreams:

- logging rollover validation and any narrow fix
- `regen_locks` ownership and replay discipline
- WinError 5 bounded retry and defer behavior
- Confluence `404` missing-state integration
- `documents.url` caller identification and, if needed, a narrow fix at the
  real owner

Rules for this phase:

- each workstream must be independently landable
- no workstream may smuggle in broader runtime-state ownership changes
- any new observability added for proof must remain strictly optional and
  non-authoritative

Validation:

- targeted tests exist for each bug class
- no workstream relies on an unreviewed runtime optimization to claim success

Exit criteria:

- the original bug classes are addressed directly and narrowly

### Phase 5: Validation Expansion and Release Gate

Purpose:

- prove release safety with the workflows that matter

Required validation additions:

- a test that uses two different machine-local config dirs against the same
  portable brain and proves stale runtime state on one machine does not block
  required work on the other
- a test that changes portable state while a cached runtime view exists, then
  proves reconcile and regen still do the right thing
- a test that deletes the runtime DB and proves behavior fully recovers
- tests that prove retained runtime observability tables are non-fatal when
  writes fail
- tests that prove retained runtime caches are advisory and yield to portable
  truth
- targeted integration or e2e coverage for the release-critical home/work
  scenario where the same brain moves between machines

Release gate:

- no `0.6.0` release candidate is accepted until these validation targets pass
- any remaining runtime-state ambiguity requires explicit sign-off, not silent
  acceptance

Exit criteria:

- the release branch demonstrates the documented runtime contract rather than
  merely describing it

### Phase 6: Documentation and Process Tightening

Purpose:

- prevent recurrence of scope drift during release hardening

Actions:

- update the planning and architecture docs as needed to record:
  - what was kept
  - what was reverted
  - why those decisions were made
- add a release-oriented rule or checklist requiring runtime-schema changes to
  name:
  - the user-visible problem being solved
  - whether the new state is correctness-critical or advisory
  - how stale cross-machine runtime state behaves
  - the exact tests that prove it remains non-authoritative
- ensure future bug-fix plans state explicitly whether observability work is:
  - validation-only
  - narrowly required
  - or intentionally a separate scope item

Validation:

- docs align with the final retained runtime design
- future planners and reviewers can detect this category of overreach early

Exit criteria:

- the final documentation explains the retained runtime model in a way that is
  reviewable and stable for release

## Required Validation Matrix

Every retained runtime feature must answer all of the following before release:

- What portable truth does it depend on?
- What happens if its local DB row is stale?
- What happens if its entire table is deleted?
- What happens if another machine has different local runtime state for the
  same brain?
- Can failure to write this state change correctness, or only observability or
  performance?
- Which automated tests prove those claims?

If any retained feature cannot answer those questions, it is not release-ready.

## Review Focus

Reviewers should challenge this plan on:

- whether the provisional keep/revert split is strict enough
- whether the multi-machine same-brain workflow is treated as a first-class
  requirement rather than a side note
- whether `operational_events` is genuinely separable from correctness
- whether advisory caches are being held to a strong enough proof standard
- whether the plan is conservative enough for an unreleased `0.6.0`
- whether any phase leaves risky decisions to implementer guesswork

## Exit Criteria

This plan is ready for approval only when a reviewer can confirm that it:

- fully centers the documented rule that runtime state is machine-local and
  non-authoritative
- requires a retrospective before irreversible keep or revert decisions
- gives a rigorous phased path to narrow the runtime surface for release
- makes the home/work multi-DB scenario an explicit validation requirement
- forces each retained runtime feature to justify itself with tests
- prevents further scope drift without explicit approval

If review feedback identifies missing controls or unclear rollback criteria, the
planner should create a new revision rather than editing this file in place.

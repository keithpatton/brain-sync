# Approval

Approved: 2026-03-18T18-38-21
Approved by: codex-gpt-5

Notes:

- no unresolved reviewer findings remain
- plan is approved as the authoritative narrowing-workflow artifact
- code implementation remains gated by the approved post-Phase-3 review and approval step defined inside the plan

---

# plan_runtime-release-alignment_4

## Status

Approved plan revision 4. This artifact preserves
`docs/plans/plan_runtime-release-alignment_4_2026-03-18.md` as the approved
execution artifact for this narrowing workflow and supersedes
`docs/plans/plan_runtime-release-alignment_3_2026-03-18.md` for review
purposes. It does **not** modify earlier plan or review artifacts.

## Objective

Restore release-oriented confidence in runtime behavior after the disputed
`v25` runtime-schema expansion by:

- separating narrow bug fixes from broader runtime-surface growth
- re-centering the system on portable-state authority
- determining the exact keep/revert/defer disposition for every retained
  runtime-surface candidate before any code changes
- forcing per-table, per-consuming-workflow proof for any retained runtime
  surface
- making pre-release compatibility and rollback policy explicit rather than
  leaving it to later execution judgment

The approved output of this plan is the narrowed, reviewable decision process
recorded below. Per the hard gate in this plan, code implementation remains
blocked until the normal post-Phase-3 plan revision is itself reviewed and
approved.

## Trigger

This revision responds to:

- the approved runtime-failure-hardening bundle in
  `docs/plans/plan_runtime-failure-hardening_3_approved_2026-03-18T15-47-10.md`
  being intentionally scoped as a bug-fix and hardening bundle
- commit `6d7eb76` introducing additional runtime tables and workflow hooks
  beyond that narrow scope
- the prior review findings that:
  - the post-Phase-3 gate was still too weak
  - the current `0.6.0` / `v25` compatibility story still looked too
    authoritative during a narrowing effort
  - disputed runtime tables could still survive via a
    "correctness-critical" loophole
  - the exact post-narrowing runtime shape was still not forced early enough
  - `operational_events` was not yet forced through the same mandatory
    narrowing outputs as the other retained candidates
- explicit user guidance that:
  - runtime DB state must remain machine-local and "pluggable" to the portable
    brain
  - pre-release local DBs may be rebuilt if narrowing requires it
  - a forward-only portable format change is allowed if it is the natural
    semantic fix, but it must be intentional and not used unnecessarily

## Stable Invariants vs Provisional Claims

This revision explicitly de-circularizes the authority model.

### Stable authority inputs

These remain authoritative during the current dispute:

- `docs/RULES.md`
- stable, cross-cutting parts of `docs/VERSIONING.md`
- stable, cross-cutting parts of `docs/GLOSSARY.md`
- `docs/runtime/README.md`
- `AGENTS.md`
- `docs/plans/README.md`

For this plan, the stable higher-order rules are:

- filesystem and portable state are authoritative
- durable state required to reconstruct the brain lives in the brain root
- runtime state is machine-local and rebuildable
- deleting runtime artifacts must not damage the brain
- runtime schema versioning is not the definition of the portable brain

### Provisional compatibility and schema claims

The following are provisional until this narrowing closes:

- the current `0.6.0` / runtime schema `v25` row in
  `docs/COMPATIBILITY.md`
- current `v25` runtime-schema references in the table-specific parts of
  `docs/VERSIONING.md`
- the `v25` table definitions and current-shape claims in
  `docs/runtime/SCHEMAS.md`
- the table-specific ownership and runtime-surface descriptions added to
  `docs/architecture/ARCHITECTURE.md`

For this plan, those texts are not durable authority. They are claims to be
re-proved, revised, or withdrawn.

### Current code and tests under review

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

This plan adopts the following architectural baseline:

- portable brain state always wins over runtime DB state
- the runtime DB may optimize and observe, but it must not define durable truth
- one machine-local runtime config supports one active brain at a time
- the same portable brain may be modified elsewhere while this machine is idle
- therefore startup and reconcile must re-establish truth from the portable
  brain and filesystem, not from local runtime assumptions
- runtime DB state must remain "pluggable" to the portable brain: the DB on
  one machine must not assume it is the exclusive long-term backing store for
  that brain

### Consequence for retained runtime-surface candidates

This revision closes the prior loophole:

- if a retained runtime-surface candidate proves to be correctness-critical for
  startup reconcile, watcher enqueue, rename/move propagation, query-index
  invalidation, or any other retained workflow, that surface fails retention in
  this narrowing effort
- such a surface must then be:
  - reverted
  - deferred to a later explicit architecture plan
  - or escalated into an intentional architecture or portable-format change
    with its own explicit approval

It may not remain in scope as a "correctness-critical runtime cache" or
"correctness-critical runtime observability surface."

### Ownership baseline for regen

This revision also adopts the following ownership direction:

- guarded ownership semantics remain in force
- `save_regen_lock()` must not become an implicit acquisition or transfer path
- ownership claim and transfer must remain explicit
- the preferred model is guarded acquisition at the engine or queue work
  boundary close to the path being regenerated, not permissive first-write
  ownership through a persistence helper

This plan does not allow fallback to permissive ownership writes.

### Portable format change policy

The default assumption remains "no portable format change unless needed."

However:

- if the correct semantic fix naturally requires a forward-only portable format
  change, that is allowed
- such a change must be explicit, intentional, and reviewed as a portable
  contract change
- it must not be smuggled in as an incidental side effect of runtime hardening
- if chosen, it must update the appropriate brain, versioning, and
  compatibility docs and tests intentionally

## Current Findings

### 1. Scope expanded beyond the approved bug bundle

The implemented `v25` work added:

- `dirty_knowledge_paths`
- `path_observations`
- `invalidation_tokens`
- `operational_events`

and threaded them into runtime decision paths for reconcile, watcher, and
query-index behavior.

That is broader than the approved bug-fix bundle.

### 2. Runtime-only classification is necessary but not sufficient

A table being machine-local is not enough to justify retention.

The stricter questions are:

- can stale, missing, or divergent local rows suppress work that portable state
  requires?
- can a machine-local optimization or observability surface become a hidden
  correctness dependency?
- if that happens, is the right answer runtime retention, architecture change,
  or portable-format change?

### 3. Existing tests prove rebuildability, but not enough retained-surface safety

The current suite proves:

- in-process runtime isolation
- `v23` to `v25` runtime migration
- clone-without-DB rebuild from portable manifests and sidecars

It does **not yet clearly prove**:

- divergent machine-local DBs for the same portable brain are safe
- stale rows in retained runtime-surface candidates cannot suppress required
  work
- the retained surfaces remain advisory in every consuming workflow

### 4. Full RCA is still required

The current evidence justifies tightening and narrowing. It does not yet fully
explain every observed breakage. A retrospective and RCA phase remains
mandatory.

## Compatibility Posture During Narrowing

This revision makes the compatibility posture explicit.

### Stable release compatibility target

The release-facing compatibility question that matters is:

- what is the final supported upgrade path from released `0.5.0` / runtime DB
  schema `v23` to the final unreleased `0.6.0` runtime and portable shape?

That final answer remains an output of this narrowing effort.

### Provisional pre-release local state

The currently created developer/tester local `v25` runtime DBs generated during
the disputed work are provisional pre-release local state, not a promised
long-term compatibility surface.

Therefore:

- narrowing may invalidate those local DBs
- explicit reset or rebuild is allowed
- this does not, by itself, break the intended eventual `0.5.0` to final
  `0.6.0` release migration story

### Current compatibility docs during review

Until this plan closes:

- the current `0.6.0` / `v25` row in `docs/COMPATIBILITY.md` is treated as a
  provisional pre-release statement under review
- it must not be used as evidence that current `v25` continuity is already
  architecturally settled
- the final release row may remain `0.6.0` / `v25`, may narrow within that
  runtime schema, or may change if an intentional portable or runtime
  compatibility decision later requires it

## Provisional Retained Runtime-Surface Candidates

This classification is intentionally conservative.

### Narrow bug-fix keep candidates

These remain plausible keep candidates:

- logging rollover validation and any narrow residual logging fix
- guarded `regen_locks` ownership and replay-safety fixes
- bounded WinError 5 lock classification and deferral behavior
- Confluence `404` classification into the existing missing-source lifecycle
- `documents.url` caller identification and any narrow fix at the real owner

### Retained runtime-surface candidates requiring explicit disposition

The following candidates must all be named in the Phase 2 authority disposition
and in the Phase 3 concrete keep/revert/defer output:

- `dirty_knowledge_paths`
- `path_observations`
- `invalidation_tokens`
- `operational_events`

### Special retention conditions for `operational_events`

If `operational_events` is retained, it must remain:

- append-only
- machine-local
- non-authoritative
- non-fatal on write failure
- not required for correctness

It may not survive by implication. It must receive an explicit keep/revert/defer
decision in the narrowed decision artifact.

### Default narrowing posture

- `dirty_knowledge_paths`, `path_observations`, and `invalidation_tokens`
  default to revert or defer unless their safety is positively proven
- `operational_events` defaults to explicit keep or explicit defer, never
  implicit keep
- if any retained runtime-surface candidate proves correctness-critical, it
  fails retention in this narrowing effort

## Pre-Release Rollback and Runtime-Shape Policy

This revision forces Phase 3 to choose one exact runtime-shape strategy.

Because `0.6.0` is unreleased and only developer/tester machine-local runtime
DBs are affected:

- the branch is not required to preserve all currently created local `v25` DBs
  in place
- explicit runtime DB reset or rebuild is allowed and preferred when narrowing
  needs it
- portable brain compatibility remains mandatory
- no new runtime schema bump is allowed as part of this narrowing

But this generic allowance is not enough by itself. Phase 3 must choose exactly
one of the following outcomes:

1. Keep current `v25` runtime shape and retain named runtime-surface candidates
Condition:
those surfaces survive review and validation

2. Keep runtime schema label `v25`, but treat pre-narrowing local DBs as
unsupported and rebuild on explicit detection
Condition:
the narrowed branch no longer trusts the pre-narrowing retained-surface set,
but does not bump runtime schema again during pre-release narrowing

3. Escalate to an explicit compatibility or portable-format decision
Condition:
the correct semantic fix cannot be represented safely within the narrowed
runtime-only posture

Phase 3 may not finish without selecting one of those concrete outcomes.

## Non-Negotiable Constraints

The following rules apply throughout this plan:

- no new runtime schema bump without separate approval
- no new runtime persistence surface may be introduced while this plan is open
- no behavior may remain whose safety depends on "the local runtime DB is
  probably current enough"
- any retained runtime surface must be advisory only
- any retained runtime surface must yield to portable truth and filesystem truth
- any retained runtime-surface candidate that proves correctness-critical fails
  retention in this narrowing effort
- provisional `6d7eb76` table-specific docs must not be treated as settled
  authority while this plan is open
- implementation may not begin until a normal next plan revision is reviewed
  and approved

## Phased Plan

### Phase 0: Freeze and Evidence Inventory

Purpose:

- stop further runtime-surface drift
- inventory the exact retained-surface candidates under review

Actions:

- freeze further runtime-state expansion
- inventory each retained runtime-surface candidate, helper, and consuming
  workflow
- map each item to:
  - original bug evidence
  - approved workstream
  - current code owner
  - current docs that describe it

Exit criteria:

- a concrete inventory exists

### Phase 1: Retrospective and RCA

Purpose:

- distinguish known failures from hypotheses and scope overreach

Actions:

- review original logs, approved bug plan, and implemented diff
- classify each concern into:
  - confirmed user-visible failure
  - validated overreach risk
  - open hypothesis
- identify where implementation exceeded approved scope

Exit criteria:

- the retrospective clearly separates known failures from open questions

### Phase 2: Runtime Authority Audit

Purpose:

- determine whether each retained runtime-surface candidate is truly advisory

Actions:

- classify each retained runtime-surface candidate as:
  - advisory optimization
  - observability only
  - removable
  - correctness-critical
- define stale-state behavior
- define missing-row behavior
- define divergent-other-machine behavior
- define delete-and-rebuild behavior

Required outputs:

- one disposition row per retained runtime-surface candidate with:
  - name
  - owner
  - authoritative input
  - rebuild source
  - stale-state failure mode
  - divergent-machine failure mode
  - proposed keep/revert/defer outcome

Mandatory narrowing consequence:

- if a retained runtime-surface candidate is classified as correctness-critical,
  it cannot remain as a retained runtime-only surface in this plan

Exit criteria:

- every retained runtime-surface candidate has an explicit authority
  disposition, including `operational_events`

### Phase 3: Concrete Narrowing Decision

Purpose:

- produce the exact keep/revert/defer outcome before any implementation

Actions:

- decide for each retained runtime-surface candidate whether it is:
  - kept now
  - reverted now
  - deferred to a later explicit plan
- choose the exact post-narrowing runtime-shape outcome from the allowed list
  in the rollback policy above
- define exact detection and rebuild/reset behavior for provisional
  pre-narrowing local DBs
- define whether the final narrowed branch still targets the current portable
  format or requires a separate explicit format-change decision

Required outputs:

- a concrete keep/revert/defer table naming every retained runtime-surface
  candidate, including `operational_events`
- a concrete runtime-shape outcome
- a concrete local DB detection and rebuild/reset policy
- a concrete statement of which compatibility/versioning/schema doc claims
  remain provisional until implementation completes

Exit criteria:

- no retained runtime-surface candidate remains in "decide during
  implementation" state
- no runtime-shape consequence remains ambiguous

## Hard Gate After Phase 3

Phase 3 does **not** authorize implementation.

Instead, completion of Phases 0-3 must produce:

- a normal next plan revision using the repo naming rules, specifically a new
  `plan_runtime-release-alignment_<next iteration>_<date>.md` artifact
  recording the concrete narrowed decisions
- a new review artifact for that revision if changes are still required, or an
  approval artifact if it is acceptable

No supporting note, equivalent artifact, or ad hoc planner output may stand in
for that next plan revision.

No implementation work may begin from this revision alone.

### Phase 4: Narrow Workstream Implementation

Purpose:

- implement only the already-approved narrowed scope

Allowed workstreams:

- logging rollover validation and any narrow residual fix
- `regen_locks` guarded ownership and replay discipline
- bounded WinError 5 lock classification and deferral
- Confluence `404` missing-state integration
- only those retained runtime-surface candidates that survive the post-Phase-3
  review

Rules:

- no runtime-surface re-expansion
- no hidden architecture decisions during execution
- no new runtime tables or files without separate approval
- no silent portable-format change

Exit criteria:

- implementation remains within the approved narrowed scope

### Phase 5: Per-Table, Per-Workflow Validation

Purpose:

- prove retained runtime surfaces are safe in each exact consuming workflow

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

- each retained runtime-surface candidate has passed per-workflow negative proof

### Phase 6: Documentation, Compatibility, and Governance Tightening

Purpose:

- align the docs only after narrowing is approved and validated

Actions:

- update provisional schema, compatibility, and architecture text only after
  the narrowed design is approved
- record the final keep/revert/defer outcome and rationale for every retained
  runtime-surface candidate
- update compatibility docs to reflect the final intended released `0.5.0` to
  `0.6.0` story rather than the provisional pre-release state under review
- if a portable-format change is explicitly chosen, update the portable-format
  docs and tests intentionally rather than working around the semantic change
- add explicit governance text that runtime-surface expansion during hardening
  requires:
  - named user-visible problem
  - authoritative input analysis
  - stale/divergent-state behavior
  - exact validating tests

Exit criteria:

- docs reflect only approved and validated runtime and compatibility behavior

## Required Validation Matrix

Every retained runtime-surface candidate must answer all of the following
before approval:

- What portable truth does it depend on?
- What happens if its local row is stale?
- What happens if its local row is missing?
- What happens if another machine has divergent local state for the same
  portable brain?
- What happens if the runtime DB is rebuilt?
- Can failure to write this state affect correctness, or only observability or
  performance?
- Which exact automated tests prove those claims for each consuming workflow?

If any retained runtime-surface candidate cannot answer those questions, it is
not release-ready.

## Review Focus

Reviewers should challenge this revision on:

- whether every retained runtime-surface candidate now goes through the same
  mandatory Phase 2 and Phase 3 decision path
- whether `operational_events` can still survive by implication anywhere
- whether the post-Phase-3 gate now conforms cleanly to the planning workflow
- whether the current `0.6.0` / `v25` compatibility story is sufficiently
  marked provisional during narrowing
- whether the correctness-critical loophole is now fully closed
- whether the post-narrowing runtime-shape choice is forced early enough
- whether the plan treats portable-format change as allowed but intentionally
  gated
- whether any narrowing, compatibility, or rollback decision still leaks to
  implementation

## Exit Criteria

This revision is ready for approval only when a reviewer can confirm that it:

- forces `operational_events` through the same Phase 2 and Phase 3 disposition
  path as the other retained candidates
- uses only normal plan-review-approval artifacts after Phase 3
- treats current `0.6.0` / `v25` compatibility and table-specific schema claims
  as provisional during narrowing
- closes the correctness-critical retention loophole for retained runtime
  surfaces
- forces an exact post-narrowing runtime-shape outcome
- preserves the rule that runtime DB state is machine-local and
  non-authoritative
- allows explicit portable-format change only when intentionally chosen and
  reviewed

If review feedback identifies further gaps, the planner should create another
new revision rather than editing this file in place.

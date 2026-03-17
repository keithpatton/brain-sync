# Architecture Review Template

## Purpose

Use this template to review whether brain-sync is structurally ready for
further investment without changing the evaluation standard between review
rounds.

This is a reference template. It is intended to be reused with the same fixed
assessment areas so review scores remain comparable over time.

## Review Contract

Every architecture review should:

- anchor claims in observed code, tests, and repository docs
- distinguish documented intent from implementation reality
- call out ambiguity as an architectural flaw
- prefer scenario-based failure analysis over abstract opinion
- state whether Brain Format `1.0` is being preserved intentionally
- remain a review artifact, not an execution plan

Every claim should cite concrete evidence such as:

- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- `tests/unit/test_architecture_boundaries.py`
- package `__init__.py` ownership docstrings
- implementation files where the behavior is expressed

## Required Inputs

At minimum, read:

- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `tests/unit/test_architecture_boundaries.py`

Inspect the current versions of:

- `src/brain_sync/application/`
- `src/brain_sync/interfaces/`
- `src/brain_sync/brain/`
- `src/brain_sync/runtime/`
- `src/brain_sync/sync/`
- `src/brain_sync/regen/`
- `src/brain_sync/query/`
- `src/brain_sync/sources/`

## Required Scenarios

Do not score the system without checking these scenarios explicitly:

1. Source registration and update intent:
  add, update, move, and remove a source; verify where durable intent lives.
2. Sync materialization:
  follow unchanged, changed, and failed source fetch paths.
3. Startup reconcile:
  evaluate offline file move, delete, and source-missing recovery.
4. Online watcher path:
  evaluate folder move, file change, debounce, and regen enqueue behavior.
5. Regen lifecycle:
  evaluate enqueue, ownership, retry, cooldown, and failure recording.
6. Runtime rebuild:
  verify what can be deleted and rebuilt without harming Brain Format `1.0`.
7. Multi-brain or root selection:
  verify whether root-scoped behavior is actually isolated.
8. Scale path:
  inspect any whole-tree scans, repeated hashing, index rebuilds, or repeated
   recomputation that will worsen with a larger brain.

## Fixed Assessment Areas

Use the same areas on every rerun.


| Area                                         | What to assess                                                                                         | Typical failure signals                                                                                   |
| -------------------------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- |
| Package ownership and naming                 | Whether package names match real subsystem ownership and whether code lands in the right package       | dumping-ground packages, ownership split across unrelated modules                                         |
| Dependency direction and orchestration       | Whether import direction matches `docs/RULES.md` and whether orchestration stays in the named surfaces | off-graph imports, transport-owned policy, broadened exception lists                                      |
| State authority and persistence integrity    | Whether portable brain state and runtime state have a clear source of truth and consistent write path  | duplicate state owners, projection drift, no-op state APIs                                                |
| Contract and concept integrity               | Whether glossary/rules concepts are reflected faithfully in code and durable formats                   | tolerated concept drift, fields that exist but are intentionally dropped, leaky transitional concepts     |
| Workflow and data-flow clarity               | Whether major flows can be followed end to end without hidden side effects or split ownership          | side-channel state updates, implicit cache invalidation, multiple flow owners                             |
| Concurrency, idempotence, and crash recovery | Whether loops, retries, queueing, and write ordering survive interruption or repeated events           | non-idempotent retries, half-applied moves, unclear ownership after crash                                 |
| Complexity concentration and hidden coupling | Whether complexity is localized behind useful seams or spread via private/helper coupling              | oversized modules, barrel exports of internals, peer subsystems importing each other's guts               |
| Testability and enforcement                  | Whether architecture can be tested directly and whether seams are actually enforced                    | missing boundary tests, hard-to-mock flows, reliance on transport-level tests only                        |
| Performance and scale behavior               | Whether the structure avoids obvious whole-tree or repeated-work traps                                 | scan-on-query, repeated hash walks, regen storms, unnecessary rebuilds                                    |
| Observability and diagnosability             | Whether the system can support structured logs, event timelines, and production debugging              | no correlation ids, no typed events, transport-local diagnostics only                                     |
| Extensibility and refactor readiness         | Whether new subsystems, stages, commands, and adapters can be added without cross-cutting edits        | extension via copy-paste, implicit extension points, refactors requiring many packages to change together |
| Compatibility and Brain Format safety        | Whether Brain Format `1.0` is isolated from runtime churn and whether compatibility claims are tested  | accidental portable-contract changes, upgrade ambiguity, runtime logic leaking into the brain contract    |


## Scoring Rubric

Score each area from 1 to 10:

- `1-3`: fundamentally broken or actively misleading
- `4-5`: workable but structurally risky
- `6-7`: mostly sound with important limitations
- `8-9`: strong and ready for further investment
- `10`: reference-quality for this class of system

Confidence must be stated as `Low`, `Med`, or `High`.

## Output Format

### 1. Scorecard


| Area | Score | Confidence | Summary |
| ---- | ----- | ---------- | ------- |


### 2. Critical Findings

List the top 5 only. For each finding include:

- what is wrong
- why it matters
- evidence
- likely failure mode if left alone

### 3. Strengths

List the top 3 only, with evidence.

### 4. Refactor Risk Map

Identify:

- fragility points
- scaling risks
- expected breakpoints for the next major subsystem refactor

### 5. Verdict

State clearly:

- `Ready` or `Not Yet`
- the top 3 blocking issues before the next major refactor

### 6. Compatibility and Observability Readiness

Answer both:

- Is Brain Format `1.0` protected from the proposed refactors?
- Is the current architecture structurally ready for typed events,
structured logs, replay/debugging, or event-sourced-style analysis?

### 7. Surgical Recommendations

List at most 7 changes. They must be structural, high leverage, and tied to
specific findings.

### 8. Derived Plans

If the review directly produces tracked implementation work, list the related
approved `docs/plans/` artifacts here.

This section is optional for a standalone review and required only when the
review has already spawned approved plan artifacts.

## Review Gates

The review should be treated as `Not Yet` if any of these are true:

- `State authority and persistence integrity` scores `5` or below
- `Contract and concept integrity` scores `5` or below
- `Dependency direction and orchestration` scores `5` or below
- the reviewer cannot explain crash recovery for core write paths
- the reviewer cannot explain how a REGEN refactor would stay local

## Rerun Discipline

On future reruns:

- keep the same assessment areas and score meanings
- note whether evidence improved, worsened, or merely moved
- avoid score inflation unless a failure mode was actually removed
- prefer comparing blast radius and ambiguity reduction over code movement
- when work is spawned from the review, track it in `docs/plans/`
- plans may link back to the motivating review immediately
- reviews should list only approved derived plans

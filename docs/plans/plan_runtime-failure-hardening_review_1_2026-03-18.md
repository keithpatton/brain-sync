# plan_runtime-failure-hardening Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-03-18
**Reviewed document:** `docs/plans/PLAN_runtime-failure-hardening.md`
**Reviewed against:**
- `docs/plans/README.md`
- `AGENTS.md`
- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- current runtime, sync, regen, and source code in `src/brain_sync/`
- machine-local evidence in `%USERPROFILE%\.brain-sync\logs\brain-sync.log`

**Purpose:** Review the runtime-failure-hardening plan as the reviewer agent,
with explicit focus on bundling, scope boundaries, acceptance criteria,
sequencing, disk-before-DB authority, idempotency, Windows lock handling,
upstream `404` classification, and evidence-trail quality.

---

## Verdict

Changes required.

The bundle is still reasonable as one review plan, but this revision is not
ready for approval. The main problems are stale scope around the logging
workstream, missing conflict-policy detail for the SQLite/idempotency work,
under-specified ownership for upstream `404` handling, and evidence anchors
that are not yet durable enough for future investigators.

This review artifact does **not** approve the plan and does **not** authorize
implementation. The planner should create a revised plan artifact rather than
editing `PLAN_runtime-failure-hardening.md` in place.

---

## Critical Issues

### C1. Workstream 1 is scoped and sequenced as net-new implementation even though the repo already contains the named mitigation

The plan says this stage records "remaining fixes" and then makes shared-log
rollover hardening the first implementation workstream and first landing step
([`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):9-10,
[`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):166,
[`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):217-246,
[`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):349-350).

Current code reality is different:

- [`logging.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/util/logging.py#L24) already defines `ResilientRotatingFileHandler`
  with fallback-to-per-run-file behavior.
- [`logging.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/util/logging.py#L55) already catches `PermissionError`
  around `doRollover()`.
- [`test_logging.py`](C:/Users/keith/source/repos/brain-sync/tests/unit/test_logging.py#L45) already tests rollover fallback.

That means the plan currently mixes at least two different realities:

- "remaining fixes" still to do
- one workstream whose primary fix shape is already in-tree

As written, an implementer would have to guess whether Workstream 1 means:

- validate the already-landed fallback against the cited 2026-03-18 evidence
- close residual gaps only
- or replace the current approach with a different handler strategy

That is a scope and sequencing problem, not just a wording nit. It also weakens
the user's requested question about keeping four bugs in one plan while keeping
implementation separable, because one of the four is no longer clearly an
"implementation" workstream in the same sense as the others.

**Required revision:** Recast Workstream 1 as one of these explicit paths:

1. "Validation and residual-gap review of the existing logging fallback," with
   concrete remaining issues if any still exist.
2. "Replace the current fallback strategy," with a stated reason the existing
   `ResilientRotatingFileHandler` is insufficient.
3. Remove Workstream 1 from the remaining-fixes bundle if the current code
   already satisfies the plan's intended outcome.

The revised plan should also update sequencing to avoid treating already-landed
behavior as the first thing that must still be implemented.

### C2. Workstream 2 does not define the actual conflict policy, so the implementer would still have to guess the product behavior

The plan correctly identifies uniqueness failures on `insight_state` and
`documents`, but it stops at "adopt an explicit conflict policy per table and
caller" without actually stating that policy
([`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):194-198,
[`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):255-280).

That is too open for approval because the two cases do not have the same
semantics:

- `knowledge_path` is part of the portable-insight plus runtime-lifecycle
  workflow, and current application code writes portable state first, then
  runtime lifecycle ([`insights.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/application/insights.py#L70)).
- `documents.url` is a runtime DB uniqueness boundary with `canonical_id` as
  the primary key and `url` as a separate unique constraint
  ([`repository.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/runtime/repository.py#L58)).

The plan never answers the questions that matter for implementation:

- If the same `knowledge_path` is discovered twice, which write is allowed to
  win, and what state transition is expected?
- If the same URL appears with a competing `canonical_id`, should the existing
  row be reused, updated, rejected with classification, or treated as a deeper
  invariant breach?
- If duplicate discovery happens after a portable write but before a runtime
  write, what exact behavior preserves disk-before-DB authority without
  silently masking a real duplicate-discovery defect?
- What observable result distinguishes "safe idempotent replay" from "true
  identity collision"?

Without those rules, the acceptance criteria are not specific enough to prevent
implementer guesswork, which the planning workflow explicitly says is grounds
to withhold approval.

**Required revision:** Add a table-by-table conflict contract for at least:

- `knowledge_path`
- `documents.url`

For each, state:

- the logical identity being protected
- whether duplicate writes are replay-safe, merge-safe, or invariant violations
- what row must win when values differ
- what must be logged or surfaced when the duplicate indicates a deeper bug
- how the chosen behavior preserves disk-before-DB authority

The revised acceptance criteria should test those exact outcomes, not just
"no longer fails with UNIQUE constraint failed."

---

## Significant Issues

### S1. Workstream 4 does not clearly attach to the existing missing-source lifecycle, so scope boundaries are still blurry

The plan says upstream `404` should become an intentional product state, but it
frames that as if the state does not yet exist
([`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):148-160,
[`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):205-208,
[`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):317-345).

Current code reality is more specific:

- [`sources.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/application/sources.py#L235)
  already resolves missing-status sources through manifest fallback.
- [`sources.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/application/sources.py#L520)
  already implements a two-stage missing protocol in reconcile.
- [`googledocs/rest.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/sources/googledocs/rest.py#L81)
  and [`googledocs/rest.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/sources/googledocs/rest.py#L148)
  already special-case `404`.
- [`confluence/rest.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/sources/confluence/rest.py#L115)
  still raises generic HTTP failures except for the version-check helper
  swallowing them into `None`.

So the real planning question is not "invent missing-source state." It is:

- which adapters are in scope for this hardening round
- where `404` is classified first
- how adapter-level classification feeds the existing two-stage missing-source
  lifecycle rather than creating a second missing-state path

As written, Workstream 4 leaves those boundaries open. An implementer could
easily add Confluence-specific "missing" handling directly in the adapter,
another could wire it in the sync pipeline, and a third could lean on
reconcile's existing missing protocol. That is exactly the sort of ambiguity
the reviewer standard says not to approve.

**Required revision:** Make Workstream 4 explicit about:

- whether this round is Confluence-only or cross-adapter
- which layer owns first classification:
  adapter, pipeline, application source lifecycle, or a shared abstraction
- how `404` classification integrates with the existing missing-status and
  reconcile flow
- what remains out of scope for other adapters in this plan revision

### S2. Workstream 3 says retries must be bounded, but it never defines the bounded policy

The plan is right to focus on lock pressure and `Access is denied` loops, and
the cited 2026-03-12 window does show repeated warnings at `07:10:06`,
`07:10:36`, and `07:11:36`. But the workstream still leaves the actual
behavior too open
([`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):290-315).

Right now the implementer still has to guess:

- which operations retry immediately versus defer to the next queue cycle
- what the retry cap is
- whether the backoff is local to one attempt, one process, or one
  `knowledge_path`
- when repeated lock contention becomes an explicit classified state rather than
  another warning
- which retry/defer path is safe after partial filesystem side effects

That matters because the risk here is not just noisy logs. It is also repeated
re-entry into the same locked subtree and accidental drift between portable and
runtime state if one phase succeeded before the lock surfaced.

**Required revision:** Add an operation-class matrix for Workstream 3 that
states, at minimum:

- the retry/defer/fail rule for each operation class
- the maximum retry count or retry window
- the owner of deferred reprocessing
- what event or status marks a path as lock-contended
- what evidence proves no partial-success drift was recorded

---

## Moderate Issues

### M1. The evidence anchors are not yet durable enough for the 2026-03-18 logging case

The plan does a good job naming the machine-local log path and rough windows
([`PLAN_runtime-failure-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_runtime-failure-hardening.md):62-93),
but the most fragile case is also the first workstream:

- the cited end timestamp `2026-03-18T13:32:22` is not present in the current
  shared log
- the shared log around `2026-03-18T13:31:31` is dominated by normal HTTP and
  sync activity, not a clearly labeled rollover failure
- the current fallback diagnostic in [`logging.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/util/logging.py#L78)
  is written to `stderr`, not into the shared log

That means a future investigator starting only from the plan and the shared log
may not be able to recover the logging case cleanly, even though the plan says
they should begin from those windows.

This does not invalidate the whole plan, but it does mean the evidence trail is
not yet strong enough for the user's stated review focus.

**Required revision:** Strengthen the evidence anchors for each failure class,
especially the logging case, by adding at least one of:

- run IDs
- exact adjacent messages to search for
- whether the evidence was in shared log, stderr, console output, or traceback
- a note that the timestamp window is approximate and which nearby message
  proves the case

For the logging workstream specifically, the plan should not imply that the
shared log alone is sufficient if the decisive evidence was emitted elsewhere.

---

## What Works

1. Keeping the four failures in one review bundle is reasonable in principle:
   they are all runtime-hardening issues and can still land as separate changes.
2. The plan's non-goals are directionally correct and avoid turning this into a
   broad runtime redesign.
3. Disk-before-DB authority is called out in the right places and should remain
   central in the next revision.
4. The timestamp windows and local-log path are useful starting points even
   though they need tightening.

---

## Required Plan Changes

Before approval, revise the plan so it:

1. Re-scopes Workstream 1 around current code reality and stops treating the
   logging mitigation as obviously net-new implementation.
2. Adds explicit conflict-policy contracts and acceptance criteria for
   `knowledge_path` and `documents.url`, including disk-before-DB behavior.
3. Defines Workstream 3's bounded retry/defer policy concretely enough that
   queue behavior and lock classification are not left to implementation
   judgment.
4. States how upstream `404` handling integrates with the existing missing
   source lifecycle and which adapters are in scope for this plan revision.
5. Tightens the evidence anchors so another investigator can reliably recover
   the cited failures from the named windows.

---

## Conclusion

The bundle itself is defensible. The current revision is not yet precise enough
to approve.

The next revision should keep the four-workstream structure only if it also
sharpens the per-workstream ownership and success conditions enough that each
change can land independently without duplicated effort or semantic drift.

# Review

Plan under review: `docs/plans/PLAN_remote-last-changed-backoff.md`
Reviewer: codex-gpt-5
Date: 2026-03-26

## Summary

The plan has the right overall direction and it gets several important
boundaries right:

- `materialized_utc` stays portable local-materialization truth
- `remote_last_changed_utc` belongs in runtime state, not the portable manifest
- cross-device runtime divergence is described honestly as a machine-local
  scheduling consequence rather than being hidden behind false portability

I am not approving it yet because three approval blockers remain. Two of them
are explicitly left open inside the plan itself, and the third is a
schema-authority omission caused by treating this as a runtime schema change
without carrying the required versioning and compatibility trail.

## Findings

### 1. The meaning of `remote_last_changed_utc` and the Google Docs enforcement seam are still left to implementer judgment

The plan repeatedly says the implementation must still decide whether
`remote_last_changed_utc` means:

- raw provider last-modified time
- or the adapter's best timestamp for a change that matters to synchronized
  content

That is not a minor implementation detail. It is the core semantic contract for
the new field. It directly determines:

- whether the field remains compatible with the stated separation from
  `materialized_utc`
- whether Confluence version metadata is sufficient by itself
- whether Google Docs false-positive version bumps are suppressed at the
  adapter seam or leak upward into shared lifecycle/scheduler code
- whether existing `last_changed_utc` compatibility surfaces in sync/admin
  state remain honest or silently drift in meaning

The plan already says adapter-owned semantics should remain authoritative, but
then reopens that same question in Phase 0, the risk section, and the open
questions. That leaves too much room for an implementation that introduces a
provider-agnostic lifecycle branch for Google Docs or that stores raw provider
timestamps even when they are known not to reflect synchronized markdown
freshness.

Required revision:

- define `remote_last_changed_utc` explicitly in the approved plan
- state exactly where Google Docs false-positive suppression lives
- state whether existing `last_changed_utc` read models stay tied to
  `materialized_utc` or are intentionally refactored, so the portable/runtime
  boundary does not drift by accident

### 2. The rollout/reset of `sync_polling` is still too under-specified for approval

The plan correctly identifies rollout as a critical risk, but it still stops at
"choose one explicit rollout mechanism" and leaves the actual decision open
between:

- clearing `sync_polling` rows during migration
- or an application-level rebuild that invalidates stale timing data

That is too open for an approved execution artifact because current code
reuses persisted `next_check_utc` and `interval_seconds` on startup. If the
rollout path is not exact, upgraded runtimes can continue honoring stale
pre-upgrade schedule state even after the new column exists.

The plan needs to specify more than "invalidate or rebuild." It should say:

- which mechanism is authoritative
- when it runs
- which rows or columns are cleared or rewritten
- how active versus missing/inactive sources are handled
- whether upgraded active sources become immediately due or take some other
  deterministic first-check path
- how the reset avoids reintroducing missing sources into active polling

Without that, the implementer still has to invent the real migration semantics,
and the acceptance criteria are not strong enough to prevent schedule drift.

### 3. The documentation and test update set is incomplete for a runtime schema change

This plan is explicitly in scope to:

- add a field to `sync_polling`
- update runtime DB migration logic

That is a runtime DB schema change, not just a scheduler refactor. Under
`AGENTS.md`, a runtime schema change must intentionally update:

- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- related migration or compatibility tests

The current plan names runtime, sync, and architecture docs, but it does not
carry the required versioning and compatibility trail. That is a schema/doc
authority gap, because the authoritative docs currently still state:

- runtime DB schema `v29`
- supported migration rows ending at `v29`
- compatibility statements tied to `v29`

Approval should not rely on the implementer to remember that versioning work
later. The plan needs to include:

- the intended runtime schema bump
- the required `VERSIONING.md` and `COMPATIBILITY.md` updates
- compatibility and migration proof updates for the new runtime schema row
- any `docs/runtime/README.md` summary updates needed because it currently
  describes the active `v29` split explicitly

## Verdict

Changes required.

Create a new plan revision that resolves the findings in this review.
This review artifact does not approve the plan and does not authorize
implementation.

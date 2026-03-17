# PLAN_source-fetch-hardening: Startup Source Fetch Hardening

## Status

Planning artifact only. This document defines the remediation plan for the
startup-path issue where brain-sync sometimes performs full source fetches for
unchanged sources on the first daemon cycle, then settles into version-only
checks later in the same run.

This stage does **not** change product behavior. It records the intended
implementation workstreams, design constraints, and acceptance criteria for a
later execution stage.

## Objective

Restore a reliable unchanged-source fast path on daemon startup without losing
the existing portability and runtime-state guarantees.

The implementation must make the first daemon cycle behave consistently with
later cycles:

- unchanged Confluence sources with sufficient freshness state should stop at
  update check
- missing attachment-local context must not force an unnecessary full page/body
  fetch
- runtime and portable source state must compose cleanly when one side is
  partial
- valid source updates must still materialize normally

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/RULES.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/GLOSSARY.md`
- `docs/brain/README.md`
- `docs/runtime/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`

It must also align with the current source-state and sync seams:

- `src/brain_sync/application/source_state.py`
- `src/brain_sync/brain/manifest.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sources/base.py`
- `src/brain_sync/sources/confluence/__init__.py`
- `src/brain_sync/sources/confluence/attachments.py`

## Confirmed Findings

The current investigation established the following facts.

### 1. The noisy behavior is concentrated in the startup or first-cycle path

Persisted logs show the daemon doing full Confluence fetches early in a run,
then later in the same daemon session checking the same sources via
`?expand=version` only.

That means the system is capable of the cheap unchanged path, but it does not
consistently reach it on startup.

### 2. The unchanged fast path is blocked by `context_missing`

`src/brain_sync/sync/pipeline.py` skips an unchanged source only when all of
the following are true:

- adapter update check returns `UNCHANGED`
- an existing local managed file is found
- `context_missing` is false

Today, `context_missing` becomes true when `sync_attachments` is enabled and
the target-local `.brain-sync/attachments` directory does not exist.

That is too broad. Missing attachment-local context should not automatically
force a full body/comments fetch for an otherwise unchanged source.

### 3. Portable seeding does not preserve update-check fingerprints

`seed_source_state_from_hint()` can restore `content_hash` and timing from a
portable manifest hint, but it does not restore `metadata_fingerprint`.

Portable `SyncHint` itself currently stores only:

- `content_hash`
- `last_synced_utc`

This means that when runtime DB state is unavailable or partial, startup may
recover enough state to avoid regen, but not enough state to satisfy a source
adapter's freshness check.

### 4. Runtime state composition is currently all-or-nothing

When a runtime DB row exists for a source, `load_state()` uses that row and
does not fall back to manifest-derived values for missing fields.

That behavior is safe when runtime rows are complete, but brittle when they are
partial. A source can have enough persisted state to block portable seeding but
not enough freshness state to avoid a full fetch.

### 5. Full fetches rewrite manifest sync hints even when markdown is unchanged

Once a source falls through to full fetch, normal materialization updates the
manifest sync hint timestamp.

For unchanged sources this currently produces manifest churn without markdown
content churn. That is not necessarily wrong by itself, but it amplifies the
impact of unnecessary startup fetches and makes the brain worktree noisier than
the real content delta.

### 6. Real source updates are mixed with false-positive fetches

The investigation also confirmed genuine content changes for a smaller subset
of sources. The remediation must not weaken the valid update path in pursuit of
reducing startup noise.

## Scope

In scope for the implementation stage:

- startup fast-path hardening for Confluence sources
- state composition changes needed to recover freshness metadata safely
- attachment-context handling changes needed to avoid unnecessary full fetches
- skip-decision logging and targeted diagnostics
- tests covering startup, partial state, and attachment-context cases
- documentation updates required by any portable or runtime state contract
  change

## Non-goals

- no broad redesign of the source adapter architecture
- no change to valid full-fetch behavior for genuinely changed sources
- no attempt to eliminate all manifest timestamp updates by policy
- no change to portable brain contract unless the implementation explicitly
  requires new portable freshness fields
- no change to normal runtime scheduling intervals beyond what is needed to
  verify the startup fast path

## Fixed Design Decisions

These decisions should be treated as settled unless a later review artifact
identifies a material issue.

### 1. Later-cycle behavior is the target startup behavior

The implementation should make startup converge on the same unchanged-source
decision quality already observed later in the same daemon run.

### 2. Missing attachment directories are a repair concern, not a freshness signal

A missing target-local attachments directory must not by itself imply that the
page body, comments, or source markdown are stale.

The implementation may still repair attachment-local context, but that repair
must be narrower than a forced full source fetch unless the adapter truly lacks
enough information to do otherwise.

### 3. Source freshness state must be recoverable field-by-field

Portable hint seeding and runtime DB progress must compose by field rather than
as a simple "runtime row wins entirely" rule.

If runtime state is present but incomplete, startup should still recover any
safe portable hint data that fills the gap.

### 4. Confluence freshness semantics must be made explicit

The implementation must choose and document which state determines whether a
source is unchanged for startup fast-path purposes:

- page version only
- page version plus attachment or comment freshness inputs
- page version plus separate attachment-local context checks

The code must not continue to mix a narrow freshness check with a much broader
forced-fetch path without explicit design intent.

### 5. `sync_hint.last_synced_utc` is not automatically a defect

This remediation should not assume that updating
`sync_hint.last_synced_utc` after a successful verification or materialization
is inherently wrong.

The implementation should first restore correct fast-path behavior. Only after
that should the team revisit whether manifest timestamp churn is acceptable
portability behavior or whether semantics need to split into multiple
timestamps.

## Workstreams

### Phase 0: Contract Clarification and Observability Baseline

Goals:

- document the intended unchanged-source decision model
- make later verification straightforward

Implementation requirements:

- add explicit debug logging around startup skip decisions, including:
  - canonical id
  - adapter status
  - fetched fingerprint
  - stored fingerprint
  - existing-file resolution
  - attachment-context decision
- document the chosen Confluence unchanged-source semantics in architecture
  docs if the implementation changes their meaning

Primary modules:

- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sources/confluence/__init__.py`
- `docs/architecture/ARCHITECTURE.md`

### Phase 1: State Composition Hardening

Goals:

- make startup freshness recovery resilient when runtime state is missing or
  partial

Implementation requirements:

- replace all-or-nothing runtime-versus-portable composition with field-aware
  merging
- define which source-state fields are safe to seed from portable hints when a
  runtime row exists but leaves them empty
- ensure startup can recover Confluence freshness metadata when safe to do so

Design options to evaluate:

- extend portable `SyncHint` to carry adapter freshness metadata
- keep `SyncHint` minimal and add selective fallback from runtime/manifest
  sources
- introduce a source-type-specific portable hint only if cross-source design
  remains clean

Primary modules:

- `src/brain_sync/application/source_state.py`
- `src/brain_sync/brain/manifest.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sources/base.py`

### Phase 2: Attachment Context Narrowing

Goals:

- stop missing attachment-local context from forcing unnecessary full fetches

Implementation requirements:

- replace the current coarse `context_missing` gate with a narrower decision
  that distinguishes:
  - source content freshness
  - attachment-local state repair
  - true missing prerequisite state
- preserve valid attachment syncing for changed sources
- preserve existing attachment repair behavior where genuinely needed

Primary modules:

- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sources/confluence/attachments.py`
- `src/brain_sync/brain/repository.py`

### Phase 3: Manifest and Runtime Timestamp Semantics Review

Goals:

- make the post-fix timestamp behavior explicit

Implementation requirements:

- document the current intended meaning of:
  - runtime `last_checked_utc`
  - runtime `last_changed_utc`
  - portable `sync_hint.last_synced_utc`
- decide whether the current portable timestamp semantics remain acceptable
  after the startup fast-path fix
- if semantics must change, update docs and code in one bounded follow-up
  instead of mixing that redesign into the fast-path fix accidentally

Important rule:

This phase is a bounded semantics review, not permission for a broad portable
state redesign unless that redesign becomes necessary to satisfy Phase 1.

Primary modules:

- `src/brain_sync/application/source_state.py`
- `src/brain_sync/brain/manifest.py`
- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`

### Phase 4: Tests and Verification

Goals:

- lock in the startup behavior and make regressions obvious

Implementation requirements:

- add unit and integration coverage for:
  - unchanged Confluence source with complete freshness state on startup
  - runtime row present but missing freshness fingerprint
  - manifest sync hint available with matching local file
  - `sync_attachments=True` with missing attachment dir for unchanged source
  - changed source still forcing normal fetch and materialization
- add an integration or system-level assertion that first-cycle behavior
  matches later-cycle behavior for unchanged sources

Primary test areas:

- `tests/unit/`
- `tests/integration/`
- `tests/system/`

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. On daemon startup, an unchanged Confluence source with sufficient freshness
   state stops at the adapter update check and does not fetch full body,
   comments, or attachments.
2. A missing target-local attachments directory does not by itself force a full
   page or comments fetch for an unchanged source.
3. Partial runtime state no longer blocks safe recovery of portable freshness
   hints needed for unchanged-source decisions.
4. Genuinely changed sources still fetch, materialize, and update runtime and
   portable state correctly.
5. Skip-decision logs make it possible to explain why a source did or did not
   take the startup fast path.
6. Tests cover the startup and partial-state cases that produced the current
   field evidence.
7. Any change to portable or runtime state semantics is documented in the
   authoritative docs named above.

## Approval Requirements

This plan is ready for approval only when a reviewer or approver can confirm
all of the following from the plan text itself:

1. The plan clearly separates the confirmed startup fast-path bug from the
   separate question of whether portable manifest timestamp churn is acceptable.
2. The remediation path does not depend on changing the meaning of
   `sync_hint.last_synced_utc` unless the fast-path fix still leaves a real
   product problem afterward.
3. The implementation sequence is specific enough that an implementer does not
   need to guess:
   - how startup state composition should be hardened
   - how attachment-context handling should be narrowed
   - what verification and logging must be added
4. The plan preserves correct behavior for genuinely changed sources and does
   not optimize the startup path by weakening valid fetch behavior.
5. The acceptance criteria are testable and strong enough to prove that
   first-cycle behavior now matches later-cycle behavior for unchanged sources.
6. Any portable or runtime contract change required by implementation has an
   explicit documentation obligation in the plan.
7. No material ambiguity remains about scope, sequencing, or success criteria.

## Risks and Mitigations

### Risk: Fast-path broadening hides real updates

Mitigation:

- keep changed-source cases in integration coverage
- make freshness semantics explicit before narrowing fetch behavior

### Risk: Portable-state changes overfit Confluence

Mitigation:

- prefer source-agnostic field-composition rules first
- add source-type-specific portable freshness fields only if clearly justified

### Risk: Attachment repair behavior regresses

Mitigation:

- separate attachment-local repair from source-content freshness decisions
- cover missing-attachment-dir cases explicitly in tests

### Risk: Timestamp semantics debate delays the real fix

Mitigation:

- treat timestamp semantics as a bounded review after fast-path restoration
- do not block Phase 1 and Phase 2 on a broader portability redesign unless the
  fix proves impossible without it

## Reviewer / Approver Focus

The reviewer or approver should focus on these questions:

1. Does the plan clearly separate the core startup bug from the secondary
   manifest churn discussion?
2. Is the proposed state-composition hardening specific enough to prevent
   implementer guesswork?
3. Does the attachment-context workstream preserve valid attachment syncing
   without forcing full source fetches?
4. Are the acceptance criteria strong enough to prove startup and later-cycle
   behavior now match for unchanged sources?

## Next Step After Review

If review feedback identifies issues, the planner should create a revised plan
artifact rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

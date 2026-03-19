# plan_source-state-boundary Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-03-19
**Reviewed document:** `docs/plans/PLAN_source-state-boundary.md`
**Reviewed against:**
- `docs/plans/README.md`
- `AGENTS.md`
- `docs/RULES.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- current source-state code in `src/brain_sync/application/source_state.py`, `src/brain_sync/brain/manifest.py`, `src/brain_sync/runtime/repository.py`, and `src/brain_sync/sources/base.py`

**Purpose:** Review the source-state-boundary plan with explicit focus on
future-proof portable-brain contract design, clarity of the runtime-versus-brain
seam, migration weight for brain-format changes, and whether the source
manifest field model is terse, apt, and extensible without conceptual drift.

---

## Verdict

Changes required.

The plan is directionally strong and correctly treats the portable brain as the
durable authority for synced-source truth. It is not ready for approval yet,
because the proposed manifest contract still leaves too much policy to the next
revision around state taxonomy, placement intent, portable-field semantics, and
the exact migration/compatibility story.

This review artifact does **not** approve the plan and does **not** authorize
implementation. The planner should create a revised plan artifact rather than
editing `PLAN_source-state-boundary.md` in place.

---

## Critical Issues

### C1. The proposed manifest shape still lacks a state-model contract, so future additions could become conceptually muddy

`docs/plans/PLAN_source-state-boundary.md:186-223` proposes a new portable
field set, and `docs/plans/PLAN_source-state-boundary.md:225-240` adds the
moved-source `materialization_status = pending` flow. But the plan never
defines the manifest as a set of field families with allowed combinations and
invariants. The later gating questions and acceptance criteria
(`docs/plans/PLAN_source-state-boundary.md:320-339`,
`docs/plans/PLAN_source-state-boundary.md:422-436`) ask for exact semantics on
only a subset of those fields.

That is not enough for a migration-heavy portable contract. Today the source
manifest is intentionally compact and easy to reason about:
`docs/brain/SCHEMAS.md:51-74` and `docs/RULES.md:726-771` define one document
that combines identity, placement intent, lifecycle, and an advisory hint.
The new proposal introduces at least four distinct concept classes:

- identity and registration: `canonical_id`, `source_url`, `source_type`
- location and operator intent: `materialized_path`, possibly `target_path`
- lifecycle: `status`, `missing_since_utc`
- materialization and freshness observation: `content_hash`,
  `remote_fingerprint`, `materialized_utc`, `materialization_status`

Without a state-model table, the next revision could still leave implementers
guessing about invalid or ambiguous combinations such as:

- `status = missing` with `materialization_status = pending`
- whether `content_hash` remains meaningful after a missing transition
- whether `remote_fingerprint` is still authoritative after rediscovery
- whether `materialized_path` may be empty while `status = active`

That is exactly the kind of future conceptual confusion the user asked to
avoid in the source manifest.

**Required revision:**
- add a field-family table for the source manifest that classifies each field
  as identity, registration intent, observed materialization location,
  lifecycle, or remote-observation/materialization state
- add a valid-state matrix covering the allowed combinations of `status`,
  `missing_since_utc`, `materialized_path`, `materialization_status`,
  `content_hash`, `remote_fingerprint`, and `materialized_utc`
- state which fields are required, optional, or forbidden in each lifecycle
  state so future field additions have a stable conceptual frame

### C2. The plan leaves placement intent materially unresolved even though the current contract treats it as a separate durable concept

`docs/plans/PLAN_source-state-boundary.md:213-216` leans toward dropping
`target_path`, and `docs/plans/PLAN_source-state-boundary.md:325-328` leaves
that as an open question for the next revision. But the current portable
contract explicitly distinguishes placement intent from live filesystem truth:

- `docs/brain/SCHEMAS.md:59-64` defines both `materialized_path` and
  `target_path`
- `docs/RULES.md:755-761` explains that `target_path` is placement intent while
  `materialized_path` is observed filesystem reality

That distinction matters to the exact seam this plan is trying to clean up.
If the portable manifest is supposed to be the durable home for synced-source
truth, the next revision must decide whether placement intent is still part of
that truth or whether the product is intentionally collapsing "where the user
wants this source to live" into "where the file currently is."

As written, the next implementer would still have to guess:

- whether a later "re-home this source" feature would have any durable intent
  field left
- whether moved-source rediscovery should preserve prior placement intent or
  treat the new location as the only durable truth
- whether `materialization_status = pending` rematerializes back into current
  filesystem reality or into a remembered intended area

That is a contract decision, not an implementation detail.

**Required revision:**
- make one explicit decision on `target_path`: retain, remove, or keep as a
  compatibility-only transitional field
- if the field is removed, name the replacement ownership model for placement
  intent and explain why that is future-proof rather than merely simpler
- if the field is retained, describe its invariant relationship to
  `materialized_path` during moves, rediscovery, and forced re-materialization

---

## Significant Issues

### S1. `remote_fingerprint` is directionally better than `metadata_fingerprint`, but the portable meaning is still too underspecified

`docs/plans/PLAN_source-state-boundary.md:203-205` and
`docs/plans/PLAN_source-state-boundary.md:217-219` replace
`metadata_fingerprint` with `remote_fingerprint`, which is a good move away
from local-markdown terminology. But the plan still does not define what kind
of portable fact this is.

In current code, the shared adapter surface is generic:
`src/brain_sync/sources/base.py` exposes `UpdateCheckResult.fingerprint` and
`SourceFetchResult.metadata_fingerprint` without constraining that value to one
remote concept such as version number, ETag, or revision ID. That means the
portable contract needs to say more than "remote freshness token" if this field
is going to live in the manifest.

The next revision should state whether `remote_fingerprint` is:

- an adapter-owned opaque token
- only comparable within the same `source_type` and `canonical_id`
- allowed to be absent for adapters that cannot produce a stable token
- strictly a last-successful remote observation, not a local materialization
  fact

Without that, the renamed field is still at risk of becoming a vague bucket for
"whatever the adapter happened to know," which would reintroduce conceptual
drift later.

**Required revision:**
- define the exact semantics and comparison scope for `remote_fingerprint`
- state whether the name is meant to be universal across adapters or whether a
  more obviously opaque name should be used
- make the field's portability rationale explicit in the next revision, not
  only in follow-on docs

### S2. The migration and compatibility story is still framed as an open choice instead of an approval-level decision

The plan correctly says portable-brain changes are allowed when justified
(`docs/plans/PLAN_source-state-boundary.md:26-28`,
`docs/plans/PLAN_source-state-boundary.md:117-121`), but it also leaves the
release story open at the point where approval must become concrete:

- `docs/plans/PLAN_source-state-boundary.md:246-255` explicitly says there is
  no commitment yet on deterministic migration versus guided migration
- `docs/plans/PLAN_source-state-boundary.md:304-317` and
  `docs/plans/PLAN_source-state-boundary.md:336-337` keep the compatibility and
  migration mode as questions for later choice

That is too open given the repo's versioning model. `docs/VERSIONING.md`
requires a deliberate distinction between Brain Format version, runtime schema
version, and app version, and `docs/COMPATIBILITY.md` requires explicit
supported rows and transition statements. If this plan is intentionally willing
to change the portable contract, the next revision must pin down the criteria
for when that becomes Brain Format `1.1` and what upgrade path `0.6.x` is
actually promising.

This is especially important for the user's stated concern: the team should not
be afraid to change the brain format when necessary, but that choice needs to
be explicit and future-facing rather than left as an implementation-time
judgment call.

**Required revision:**
- choose one explicit migration mode for this plan revision: deterministic
  in-app migration, read-old/write-new compatibility window, guided migration,
  or intentional break
- state the exact criterion for a Brain Format bump versus a same-format field
  clarification
- add the minimum cross-machine proof scenarios the implementation must test,
  including at least one case where two machines with different runtime DB
  state converge on the same durable source truth from the shared manifest

---

## What Works

1. The plan is right to treat this as a boundary-reset problem rather than a
   narrow runtime-table cleanup.
2. The intent to make runtime state polling-only is directionally sound and
   matches the repo's durable-versus-runtime rules.
3. The plan correctly refuses to treat "avoid brain-format change" as an
   absolute rule when that would keep the contract muddy.
4. The moved-source `pending` re-materialization direction is a promising
   simplification compared with hidden best-effort merge semantics.

---

## Required Plan Changes

Before approval, revise the plan so it:

1. Defines the source manifest as a stable field taxonomy with explicit
   invariants and allowed state combinations.
2. Makes a final decision on whether placement intent remains a durable source
   concept and how that is represented after this refactor.
3. Specifies the exact portable semantics of `remote_fingerprint` so the field
   name is terse and extensible without becoming vague.
4. Converts the migration/versioning section from an open decision list into a
   concrete release and compatibility path, including cross-machine authority
   proof obligations.

---

## Conclusion

The architectural direction is good, and the plan is already asking many of
the right questions. The reason for withholding approval is not that the team
should avoid changing the brain format. It is the opposite: if the manifest is
going to become the durable home for more source truth, the next revision needs
to make that contract sharper before the repo pays the migration cost.

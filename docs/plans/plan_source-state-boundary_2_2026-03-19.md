# plan_source-state-boundary_2

## Status

Plan revision 2.

This revision supersedes
`docs/plans/PLAN_source-state-boundary.md` for review purposes and addresses
the findings in
`docs/plans/plan_source-state-boundary_review_1_2026-03-19.md`.

This artifact is still planning only. It does not approve implementation.

## Objective

Reset the boundary between portable source state and machine-local runtime
polling state so the portable brain carries the durable state machine for each
synced source's knowledge file and the runtime DB is narrowed to polling and
scheduler coordination only.

This revision sharpens the portable contract before any migration cost is paid.
The central product decision is that the source manifest should describe one
portable knowledge-file state machine directly rather than splitting file
lifecycle across multiple loosely-related fields.

## Product Decisions Confirmed For This Revision

The user has made explicit product decisions that this revision now treats as
settled design input:

1. Portable placement intent is intentionally collapsed into one anchored file
   path. The manifest will not retain a separate durable `target_path`.
2. The portable manifest should use one file-oriented lifecycle field,
   `knowledge_state`, rather than a separate `status` plus
   `materialization_status` pair.
3. The portable path field should be `knowledge_path`, meaning the path the
   synced source's knowledge file currently corresponds to or should next
   materialize to.
4. A moved or rediscovered file should be represented by `knowledge_state =
   stale`, not by a separate moved-only lifecycle axis.
5. Portable state transitions that matter for correctness must be written as
   early as possible so another process on another machine can continue from
   the same brain without depending on the previous machine's runtime DB.

## Authoritative Inputs

Stable authority for this revision:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/GLOSSARY.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/plan_source-state-boundary_review_1_2026-03-19.md`
- `docs/plans/plan_source-fetch-hardening_2_approved_2026-03-18T11-00-51.md`
- `docs/plans/plan_source-fetch-hardening_2_notes.md`
- `docs/migrations/v21-v23.md`

Code and tests that the implementation and later review must align with:

- `src/brain_sync/application/source_state.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/brain/manifest.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sources/base.py`
- `tests/unit/test_brain_repository.py`
- `tests/unit/test_pipeline.py`
- `tests/integration/test_source_fetch_hardening.py`

## Final Portable Contract Direction

### 1. The manifest owns one portable knowledge-file state machine

This revision replaces the earlier candidate model of:

- `materialized_path`
- `target_path`
- `status`
- `materialization_status`

with one anchored path plus one file lifecycle field:

- `knowledge_path`
- `knowledge_state`

The intent is to keep the portable contract terse and future-proof:

- `knowledge_path` answers "which knowledge file does this source correspond
  to now, or where should the next materialization land?"
- `knowledge_state` answers "what is the portable lifecycle state of that
  knowledge file?"

No separate durable source-file-placement intent field remains in the manifest.

### 2. Runtime DB state is polling-only

The runtime DB is still narrowed to machine-local polling and scheduler
coordination.

Portable source integrity, file lifecycle, and forced re-materialization
requirements must live in the source manifest so they survive:

- process death
- machine changes
- runtime DB deletion
- different local polling histories

### 3. Portable state transitions must be written early

This revision makes a specific durability rule explicit:

If a source lifecycle transition changes what a later sync run must do, that
transition must be written to the portable manifest before any later runtime
polling or cleanup step is allowed to become the sole record of that
obligation.

Examples:

- source registration must write `knowledge_state = awaiting` immediately
- moved-source rediscovery must write `knowledge_path = <new path>` and
  `knowledge_state = stale` immediately
- first-pass missing must write `knowledge_state = missing` and
  `missing_since_utc` immediately

The goal is that a second machine opening the same brain sees the same durable
source truth even if the first machine died mid-flow.

## Source Manifest v1.1 Proposal

### Field taxonomy

| Field | Family | Required | Meaning |
|---|---|---|---|
| `version` | schema | yes | Source manifest schema version |
| `canonical_id` | identity | yes | Stable source identity |
| `source_url` | identity | yes | Canonical remote URL |
| `source_type` | identity | yes | Source adapter type |
| `sync_attachments` | durable setting | yes | Whether source-owned attachments should materialize |
| `knowledge_path` | file anchor | yes | Relative path from `knowledge/` to the markdown file this source currently corresponds to or should next materialize to |
| `knowledge_state` | file lifecycle | yes | Durable lifecycle state of the underlying knowledge file |
| `missing_since_utc` | file lifecycle | conditional | First timestamp when the source entered `missing` |
| `content_hash` | last-successful observation | conditional | Last successful materialized body hash |
| `remote_fingerprint` | last-successful observation | conditional | Last successful remote freshness token from the adapter |
| `materialized_utc` | last-successful observation | conditional | Timestamp of the last successful full materialization |

### Field semantics

#### `knowledge_path`

`knowledge_path` is the single durable file anchor for the source.

Its meaning depends on `knowledge_state`:

- in `awaiting`, it is the intended first materialization path
- in `materialized`, it is the current known materialized file path
- in `stale`, it is the anchored path the source has been updated to, but the
  file is not yet considered settled
- in `missing`, it is the last anchored path preserved through the missing
  lifecycle

`knowledge_path` is always a file path, never only an area path.

#### Registration-time path rule

Because `target_path` is removed, the first durable path must still be known
before the first successful fetch.

This revision therefore chooses one explicit rule:

- source registration receives an area/path hint as command input
- the application derives a deterministic provisional `knowledge_path` from
  that area plus a filename derived from the source's portable source-dir ID
- example shape: `<area>/<source_dir_id>.md`

That provisional path is portable durable state immediately.

At first successful materialization, the implementation may rewrite
`knowledge_path` to the final resolved materialized filename if the
materializer chooses a different slugged title-based name.

This rule is intentional. It removes the need for a separate durable
placement-intent field while still giving the brain a portable first
materialization anchor.

#### `knowledge_state`

`knowledge_state` is the only portable lifecycle field for the knowledge file.

Chosen values:

- `awaiting`
- `materialized`
- `stale`
- `missing`

This field is intentionally scoped only to the knowledge file, not to broader
remote-source lifecycle or auth status.

#### `remote_fingerprint`

`remote_fingerprint` is the chosen portable name for the remote freshness
token.

Its contract is:

- adapter-owned and opaque
- required after a successful settled materialization
- compared only within the same `source_type` and `canonical_id`
- last successful remote observation, not a local markdown fact
- portable because later machines need the same durable freshness baseline
  without inheriting another machine's runtime DB

It may hold a page version, ETag, revision ID, or another adapter-specific
token, but the manifest contract does not interpret its internal structure.

## Knowledge-State Matrix

### State meanings

| `knowledge_state` | Meaning |
|---|---|
| `awaiting` | Source is registered but has not yet completed its first successful materialization |
| `materialized` | The knowledge file exists at `knowledge_path` and is the settled happy-path state |
| `stale` | The knowledge file is no longer considered settled and must undergo a full re-fetch / re-materialization before it can return to `materialized` |
| `missing` | No knowledge file for this source can currently be found; the manifest remains anchored to the last known `knowledge_path` during the missing lifecycle |

### State / field validity matrix

| `knowledge_state` | File presence expectation | `missing_since_utc` | `content_hash` | `remote_fingerprint` | `materialized_utc` |
|---|---|---|---|---|---|
| `awaiting` | File not expected | must be null | must be null | must be null | must be null |
| `materialized` | File required at `knowledge_path` | must be null | must be set | must be set | must be set |
| `stale` | File may be present at `knowledge_path` | must be null | must be set | must be set | must be set |
| `missing` | File must not be present / could not be found | must be set | may be set | may be set | may be set |

### State invariants

1. `knowledge_state` is the only portable lifecycle field for the knowledge
   file.
2. `missing_since_utc` is non-null if and only if `knowledge_state = missing`.
3. `stale` is not a general error bucket. In this revision it means that the
   source must be fully re-materialized before it is trusted as settled again.
   The motivating case is moved or rediscovered sources.
4. `materialized_utc` always means "last successful full materialization." It
   does not mean "file currently present."
5. `content_hash`, `remote_fingerprint`, and `materialized_utc` are historical
   last-successful facts. They are not cleared merely because a later state is
   `stale` or `missing`.
6. Unchanged-source fast paths must never treat `knowledge_state = stale` as
   equivalent to `materialized`, even when `remote_fingerprint` matches.

## Portable State Transition Rules

### 1. Registration

On source registration:

- write the manifest immediately with:
  - `knowledge_state = awaiting`
  - derived provisional `knowledge_path`
  - `missing_since_utc = null`
  - `content_hash = null`
  - `remote_fingerprint = null`
  - `materialized_utc = null`
- only after that may the runtime layer create or update machine-local polling
  rows

This makes first materialization restart-safe and cross-machine-safe.

### 2. First successful materialization

On first successful full materialization:

- update `knowledge_path` to the final resolved materialized file path if it
  differs from the provisional one
- set `knowledge_state = materialized`
- clear `missing_since_utc`
- set `content_hash`
- set `remote_fingerprint`
- set `materialized_utc`

This is the only transition from `awaiting` to the settled happy path.

### 3. Moved-source rediscovery

If a source file is rediscovered at a different path:

1. update `knowledge_path` immediately to the rediscovered file path
2. set `knowledge_state = stale` immediately
3. persist that manifest transition before any follow-on fetch or cleanup work
4. on a later successful full materialization, transition to
   `knowledge_state = materialized`

This revision intentionally uses `stale` for the moved-source case. The
portable obligation is "must fully re-materialize and re-check everything,"
not merely "path changed."

### 4. Missing first pass

If reconciliation or watcher recovery cannot find the file:

1. set `knowledge_state = missing`
2. set `missing_since_utc`
3. preserve `knowledge_path` as the last anchored path
4. preserve historical last-successful fields when present

That transition must be durable before any runtime-only scheduling decisions.

### 5. Missing second pass

If the next reconciliation still finds the source missing:

- delete the source registration manifest
- delete source-owned portable managed artifacts according to existing cleanup
  rules
- delete machine-local runtime polling rows

### 6. Recovering from `stale` or `missing`

Only a successful full materialization may clear `stale` or `missing` back to
`materialized`.

The transition must:

- set `knowledge_state = materialized`
- clear `missing_since_utc`
- set fresh `content_hash`
- set fresh `remote_fingerprint`
- set fresh `materialized_utc`

## Runtime Schema Direction

### Runtime table naming and ownership

This revision keeps the plan's runtime narrowing direction:

- rename runtime `sync_cache` to `sync_polling`
- keep runtime ownership machine-local and rebuildable
- remove durable source-truth fields from runtime ownership

### Proposed runtime `sync_polling` fields

| Field | Meaning |
|---|---|
| `canonical_id` | Source canonical ID; primary key |
| `last_checked_utc` | When this machine last checked the source |
| `current_interval_secs` | Active polling interval / backoff value |
| `next_check_utc` | Next scheduled poll time on this machine |
| `interval_seconds` | Persisted scheduler interval baseline |

Fields intentionally removed from runtime ownership:

- `last_changed_utc`
- `content_hash`
- `metadata_fingerprint`

Portable truth now lives in:

- `knowledge_path`
- `knowledge_state`
- `content_hash`
- `remote_fingerprint`
- `materialized_utc`
- `missing_since_utc`

## Versioning And Compatibility Decision

### Chosen portable versioning path

This revision chooses one explicit release path:

- portable source-manifest change requires Brain Format `1.1`
- runtime polling narrowing requires runtime DB schema `v26`
- this work is not a `0.6.x` continuity change because it alters the supported
  portable manifest contract
- implementation should target the next app major compatibility row after
  `0.6.0`; absent a separate release-policy decision, that means `1.0.0`

This directly answers the review finding that the migration story must stop
being an open choice.

### Chosen migration mode

This revision chooses one explicit migration mode:

- guided migration for Brain Format `1.0 -> 1.1`
- in-place deterministic migration for runtime DB `v25 -> v26`

Portable migration is guided rather than automatic because this refactor:

- renames and repurposes key manifest fields
- removes `target_path`
- introduces registration-time provisional `knowledge_path`
- changes the durable lifecycle model itself

The plan should prefer a conservative, reviewable migration path over hidden
automatic rewrite complexity during normal startup.

### Guided migration requirements

Implementation must ship a migration artifact under `docs/migrations/`
describing the supported path from Brain Format `1.0` to `1.1`.

That migration artifact must include:

- backup expectations
- exact field mapping from old source manifests to new source manifests
- how existing `materialized_path` and `target_path` map into `knowledge_path`
- how old `status` / `missing_since_utc` / `sync_hint` values map into the new
  state machine
- how to treat pre-materialized or unusual source manifests conservatively
- explicit note that the migration preserves portable source truth and does not
  depend on any prior machine's runtime DB contents

### Compatibility statements the docs must adopt

The implementation docs must state the new row in the canonical versioning
form, for example:

`brain-sync 1.0.0 supports Brain Format 1.1 with runtime DB schema v26`

and must state that:

- Brain Format `1.0` is an upgrade source via the guided migration path
- runtime DB `v25` migrates to `v26` in place
- deleting runtime DB state still must not alter Brain Format `1.1` source
  truth

## Cross-Machine Proof Obligations

The implementation is not acceptable without tests that prove the portable
state machine, not local runtime state, is the durable authority.

Minimum required scenarios:

1. Two machines, same shared brain, different local polling rows:
   both must read the same source manifest and derive the same durable source
   truth.
2. Machine A detects a moved source, updates `knowledge_path`, and writes
   `knowledge_state = stale`, then stops before re-materialization:
   machine B must open the same brain and force full materialization from the
   manifest alone.
3. Machine A marks a source `missing` and writes `missing_since_utc`, then
   stops:
   machine B must continue the missing lifecycle from the manifest alone.
4. One machine deletes its runtime DB and rebuilds it:
   the rebuilt runtime state must not alter `knowledge_path`,
   `knowledge_state`, or the historical last-successful fields.
5. A source in `stale` with matching `remote_fingerprint` must still full
   materialize:
   local fast-path freshness must not override portable `stale`.

## Documentation Updates Required

### `docs/brain/SCHEMAS.md`

Must be updated to replace the old source-manifest field contract with:

- `knowledge_path`
- `knowledge_state`
- the state/field validity matrix
- `remote_fingerprint` semantics

### `docs/RULES.md`

Must be updated to define:

- the portable/runtime boundary for source truth
- `knowledge_path` as the single durable file anchor
- `knowledge_state` meanings and invariants
- the early durable write rule for source lifecycle transitions
- moved-source `stale` behavior

### `docs/architecture/ARCHITECTURE.md`

Must explain:

- why `target_path` was intentionally removed from portable state
- why `knowledge_state` replaces the split lifecycle model
- why portable state transitions are written before runtime-only follow-up work
- why cross-machine continuity depends on the manifest rather than runtime DB

### `docs/runtime/SCHEMAS.md`

Must be updated for:

- runtime schema `25 -> 26`
- `sync_polling` table name
- polling-only field set

### `docs/VERSIONING.md`

Must be updated for:

- Brain Format `1.1`
- runtime schema `v26`
- next supported app-version compatibility row

### `docs/COMPATIBILITY.md`

Must be updated to add:

- the new supported compatibility row
- Brain Format `1.0 -> 1.1` guided migration statement
- runtime `v25 -> v26` in-place migration statement
- compatibility test obligations for the new portable source-state model

### Migration docs

Must add one guided migration document under `docs/migrations/`.

## Phase Plan

### Phase 0: Contract Lock

Purpose:

- freeze the new portable source-manifest contract before code changes

Required outputs:

- final field taxonomy
- final `knowledge_state` matrix
- final `knowledge_path` registration-time rule
- final `remote_fingerprint` semantics

Exit criteria:

- no manifest field meaning or lifecycle pairing remains ambiguous

### Phase 1: Portable And Runtime Schema Design

Purpose:

- define the final on-disk source manifest and runtime polling schemas

Required outputs:

- Brain Format `1.1` source-manifest schema proposal
- runtime `v26` `sync_polling` schema proposal
- exact mapping from old durable fields to new durable fields

Exit criteria:

- implementers can change schema code and docs without inventing policy

### Phase 2: Portable State-First Refactor Sequencing

Purpose:

- sequence implementation so portable state changes happen before runtime-only
  coordination

Required outputs:

- registration sequencing for `awaiting`
- moved-source sequencing for `stale`
- missing sequencing for `missing`
- successful materialization sequencing for `materialized`

Exit criteria:

- no lifecycle transition depends on hidden runtime authority

### Phase 3: Migration, Docs, And Compatibility

Purpose:

- land the refactor with a complete migration and release story

Required outputs:

- guided Brain Format `1.0 -> 1.1` migration document
- runtime `v25 -> v26` migration plan
- updated versioning and compatibility docs
- compatibility and cross-machine proof tests

Exit criteria:

- release and migration behavior is explicit enough for approval

## Acceptance Criteria For Approval

This revision is ready for approval only when the reviewer can confirm that it:

1. resolves the field-taxonomy ambiguity by defining one portable
   knowledge-file state machine
2. makes a final contract decision to remove `target_path`
3. defines one exact meaning for `knowledge_path` in every `knowledge_state`
4. defines one exact `knowledge_state` matrix with required and forbidden
   field combinations
5. defines `remote_fingerprint` as an opaque adapter-owned remote freshness
   token with explicit comparison scope
6. makes portable state-first transition ordering explicit for registration,
   moved-source handling, and missing detection
7. chooses one explicit versioning and compatibility path:
   Brain Format `1.1`, runtime schema `v26`, guided portable migration
8. includes cross-machine proof obligations showing that different runtime DBs
   cannot diverge on durable source truth

## Implementation Gate

Do not implement this refactor from this revision alone until it is approved
under the normal planning workflow.

The next required action is reviewer evaluation of this revision and then,
only if acceptable, creation of the corresponding approval artifact.

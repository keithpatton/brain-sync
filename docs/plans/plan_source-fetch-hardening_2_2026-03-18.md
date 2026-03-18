# Startup Source Fetch Hardening

## Status

Planning artifact only. This revision supersedes the root plan for the next
review pass and resolves the prior review findings about attachment repair,
Confluence unchanged-source semantics, and portable manifest gating.

This file is not approval and does not authorize implementation by itself.

## Objective

Restore a reliable unchanged-source startup fast path without weakening valid
changed-source behavior or leaving attachment repair stranded behind full
fetches.

The implementation must make the first daemon cycle behave consistently with
later cycles:

- unchanged Confluence sources with sufficient freshness state stop at update
  check for page/body/comments freshness
- unchanged sources with `sync_attachments=True` still run the required
  lightweight attachment repair path
- partial runtime state no longer blocks safe recovery of portable freshness
  hints
- genuinely changed sources still fetch, materialize, and update durable and
  runtime state normally

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `AGENTS.md`
- `docs/RULES.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`

It must also align with the current source-state and sync seams:

- `src/brain_sync/application/source_state.py`
- `src/brain_sync/brain/manifest.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sources/base.py`
- `src/brain_sync/sources/confluence/__init__.py`
- `src/brain_sync/sources/confluence/attachments.py`
- `src/brain_sync/sync/attachments.py`

## Confirmed Findings

The current implementation context establishes the following facts.

### 1. Startup noise is caused by the startup or first-cycle decision path

Persisted evidence shows the daemon doing full Confluence fetches early in a
run and later using the cheaper `fetch_page_version` path for the same source.

### 2. The skip path is blocked by coarse attachment-context logic

`src/brain_sync/sync/pipeline.py` currently treats a missing
`.brain-sync/attachments/` directory as `context_missing`, which prevents the
unchanged-source skip even when the page version matches and the local managed
file exists.

### 3. Confluence freshness is currently page-version-based

`src/brain_sync/sources/confluence/__init__.py` classifies unchanged versus
changed using only `fetch_page_version()` compared with
`source_state.metadata_fingerprint`.

Comments are only fetched during full fetch today. Attachment discovery is also
currently coupled to the full-fetch path.

### 4. Attachment repair is currently coupled to full fetch

`process_attachments()` performs legacy-context migration, ensures the
per-source attachment directory exists, discovers remote attachments, and
downloads attachment binaries. That helper is only called after full fetch in
`process_source()`.

If unchanged sources stop falling through to full fetch without another repair
path, deleted attachment directories or files can remain broken indefinitely.

### 5. Runtime and portable state composition is all-or-nothing today

`load_state()` currently uses the runtime `sync_cache` row wholesale when one
exists. `seed_source_state_from_hint()` only runs when no runtime row exists,
so partial runtime rows can block safe portable seeding.

### 6. Manifest timestamp churn is a separate question

Unnecessary full fetches currently rewrite `sync_hint.last_synced_utc`, but
that timestamp-churn question remains separate from the startup fast-path bug.

## Scope

In scope for the implementation stage:

- startup fast-path hardening for Confluence sources
- field-aware composition of runtime progress and portable hint data
- explicit unchanged-source attachment repair for Confluence
- durable documentation of unchanged-source semantics in the authoritative docs
- targeted logging and tests that prove startup and later-cycle behavior match
- versioning, compatibility, and compatibility-test updates if portable
  manifest fields change

## Non-goals

- no broad source-adapter redesign
- no weakening of valid changed-source fetch behavior
- no mixing of the timestamp-churn discussion into the core startup-path fix
- no portable manifest change without the explicit Brain Format and
  compatibility gate defined below
- no page/comments freshness expansion beyond the semantics chosen in this plan

## Fixed Design Decisions

These decisions are settled for this plan revision.

### 1. Later-cycle behavior is the target startup behavior

Startup should reach the same unchanged-source decision quality later cycles
already reach today for page freshness.

### 2. Confluence unchanged-source semantics for this fix are page version plus separate attachment repair

For the startup fast path, Confluence source-content freshness is determined by
page-version equality:

- `check_for_update()` compares the remote page version with the stored
  `metadata_fingerprint`
- matching page version means the source is unchanged for page markdown and
  comments in this stage
- attachment repair is a separate maintenance step and must not by itself flip
  an unchanged page into the full page/comments fetch path

This decision must be stated durably in the authoritative docs rather than left
as an implementation inference.

### 3. Missing attachment files or directories remain repairable for active sources

The fast-path fix must preserve the rules expectation that users may delete
attachment files or attachment directories and brain-sync may re-download them
on a later sync while the source remains active.

That expectation must no longer depend on unchanged sources falling through to
full page/comments fetch.

### 4. Unchanged-source attachment repair must be lighter than full source fetch

For unchanged Confluence sources with `sync_attachments=True`, the required
repair behavior is:

- migrate legacy attachment context into `.brain-sync/attachments/<source_dir_id>/`
- ensure the per-source attachment directory exists
- discover the current remote attachment set for the page
- restore missing local attachment files from that remote attachment set
- preserve existing local attachment files unless attachment-specific logic says
  they need refresh

This repair path must not fetch page body HTML, must not fetch comments, and
must not rewrite source markdown solely to heal attachment state.

### 5. Lightweight attachment repair runs on the unchanged-source path

For Confluence sources with `sync_attachments=True`, attachment repair runs
after the source is classified as unchanged and before the sync attempt returns
as a completed no-page-fetch cycle.

It is not a startup-only special case. Later syncs must use the same
unchanged-source repair path so deleted attachment files remain recoverable on a
later sync.

### 6. Source freshness state must compose field-by-field

Portable hint data and runtime `sync_cache` data must merge by field. A partial
runtime row must not suppress safe portable seeding for fields it does not
provide.

### 7. Portable manifest changes require an explicit Brain Format and compatibility decision

If implementation adds or repurposes durable source-manifest fields, including
any `sync_hint` expansion, that same change must include:

- an intentional Brain Format assessment against `docs/VERSIONING.md`
- updates to `docs/brain/SCHEMAS.md` and any other authoritative portable docs
  that now describe the field
- updates to `docs/COMPATIBILITY.md` for any new or changed supported row or
  transition statement
- compatibility-test coverage for the portable change, placed in `tests/compat/`
  or another clearly named compatibility-focused suite

Portable contract changes are not left as an implementation-time judgment call.

## Workstreams

### Phase 0: Contract Clarification and Observability Baseline

Goals:

- make the Confluence unchanged-source contract durable and authoritative
- make attachment-repair decisions observable
- remove ambiguity before behavior is narrowed

Implementation requirements:

- add a normative statement to `docs/RULES.md` that Confluence unchanged-source
  startup behavior is page-version-based with separate attachment repair for
  active sources that sync attachments
- add matching explanatory rationale to `docs/architecture/ARCHITECTURE.md`
- if portable or runtime schemas change later in the work, update
  `docs/brain/SCHEMAS.md` or `docs/runtime/SCHEMAS.md` in the same change set
- add debug logging around the startup and later-cycle decision path, including:
  - canonical id
  - adapter status
  - fetched fingerprint
  - stored fingerprint
  - existing-file resolution
  - whether the source took the unchanged fast path
  - whether attachment repair ran
  - why attachment repair did or did not run
  - whether repair recreated a directory, restored files, or no-oped

Primary modules:

- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sources/confluence/__init__.py`
- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`

### Phase 1: State Composition Hardening

Goals:

- make startup freshness recovery resilient when runtime state is missing or
  partial
- keep any portable-manifest change behind an explicit versioning gate

Implementation requirements:

- replace the current all-or-nothing runtime-versus-portable composition with
  field-aware merging
- define an explicit precedence table for source-state fields:
  - manifest remains authoritative for registration intent
  - runtime `sync_cache` remains authoritative for populated runtime freshness
    fields
  - verified portable hint data may fill only the runtime freshness fields that
    are absent or empty
- ensure Confluence `metadata_fingerprint` recovery is handled intentionally:
  - if it stays runtime-only, startup must still merge portable hint fields
    around missing runtime values without regression
  - if it becomes durable, implementation must execute the portable-contract
    gate in Fixed Decision 7
- keep the durable/runtime split explicit in docs and tests

Exit gate:

Before Phase 1 is considered done, the implementation must have taken one of
these two explicit paths:

1. No portable manifest field change.
   Result:
   - `docs/brain/SCHEMAS.md`, `docs/VERSIONING.md`, and
     `docs/COMPATIBILITY.md` stay unchanged for portable schema
   - tests prove the runtime-only/field-merge path works

2. Portable manifest field change.
   Result:
   - Brain Format and compatibility assessment is updated intentionally
   - authoritative docs are updated in the same change set
   - compatibility tests are added for the supported portable row

Primary modules:

- `src/brain_sync/application/source_state.py`
- `src/brain_sync/brain/manifest.py`
- `src/brain_sync/runtime/repository.py`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/SCHEMAS.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`

### Phase 2: Unchanged-Source Attachment Repair Split

Goals:

- stop missing attachment-local state from forcing unnecessary full fetches
- preserve attachment repair for unchanged active sources

Implementation requirements:

- split the current coarse `context_missing` decision into three explicit
  branches:
  - page/comments freshness decision
  - unchanged-source attachment repair decision
  - true full-fetch requirement
- define the full-fetch requirement narrowly:
  - remote page version changed
  - update status is unknown and the adapter cannot safely classify unchanged
  - the materialized source file is missing or otherwise cannot support a safe
    unchanged-source return
- implement a Confluence attachment-repair helper or refactor the existing
  attachment helper so unchanged-source repair can run without calling
  `fetch_page_body()` or `fetch_structured_comments()`
- require unchanged-source repair to handle:
  - missing per-source attachment directory
  - missing local attachment files for still-active remote attachments
  - legacy attachment-context migration
- keep changed-source attachment syncing on the normal full-fetch path
- ensure attachment repair does not rewrite source markdown or update the page
  freshness decision by itself

Sequencing requirements:

1. Run update check.
2. Resolve whether the local materialized source file exists.
3. If the source is changed or cannot safely take the unchanged path, do the
   existing full fetch.
4. If the source is unchanged and `sync_attachments=False`, return unchanged.
5. If the source is unchanged and `sync_attachments=True`, run the lightweight
   attachment repair path, then return unchanged without page/comments fetch.

Primary modules:

- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sources/confluence/attachments.py`
- `src/brain_sync/sync/attachments.py`
- `src/brain_sync/brain/repository.py`

### Phase 3: Manifest and Runtime Timestamp Semantics Review

Goals:

- keep the timestamp-churn question separate from the startup fast-path fix
- make timestamp meanings explicit after the core behavior is restored

Implementation requirements:

- document the intended meanings of:
  - runtime `last_checked_utc`
  - runtime `last_changed_utc`
  - portable `sync_hint.last_synced_utc`
- evaluate whether the restored fast path leaves a real remaining product issue
  around portable timestamp churn
- if timestamp semantics must change, do that as a bounded follow-up decision
  with matching doc and test updates rather than folding it silently into Phase
  1 or Phase 2

Important rule:

This phase does not reopen the core fast-path or attachment-repair decisions in
this plan.

Primary modules:

- `src/brain_sync/application/source_state.py`
- `src/brain_sync/brain/manifest.py`
- `docs/RULES.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/SCHEMAS.md`

### Phase 4: Tests and Verification

Goals:

- lock in the unchanged-source startup fast path
- prove attachment repair still happens without forcing full page/comments fetch
- prove any portable-contract change is versioned and tested intentionally

Implementation requirements:

- add unit and integration coverage for:
  - unchanged Confluence source with complete freshness state on startup
  - runtime row present but missing `metadata_fingerprint`
  - manifest sync hint available and safely merged around partial runtime state
  - unchanged source with `sync_attachments=True` and missing attachment
    directory
  - unchanged source with `sync_attachments=True` and one deleted local
    attachment file
  - changed source still forcing full fetch and materialization
- add an integration or system-level assertion that first-cycle and later-cycle
  behavior match for unchanged Confluence sources:
  - same page/comments fetch decision
  - same attachment-repair behavior
- add assertions that unchanged-source attachment repair does not call the full
  page/comments fetch path
- if portable manifest fields change, add compatibility tests that prove:
  - the supported portable row is readable and writable intentionally
  - the documented Brain Format / compatibility statement matches actual code

Primary test areas:

- `tests/unit/`
- `tests/integration/`
- `tests/system/`
- `tests/compat/` or another clearly named compatibility-focused suite when
  portable manifest changes are introduced

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. On daemon startup, an unchanged Confluence source with sufficient freshness
   state stops at the adapter update check for page/body/comments freshness and
   does not call the full page/comments fetch path.
2. The same unchanged Confluence source takes the same page/comments fast path
   on later daemon cycles, not only after startup has warmed runtime state.
3. For unchanged Confluence sources with `sync_attachments=True`, a lightweight
   attachment repair pass still runs and can recreate a missing per-source
   attachment directory without fetching page body or comments.
4. For unchanged Confluence sources with `sync_attachments=True`, deleting a
   local managed attachment file is repaired on a later sync by re-downloading
   the missing file without forcing full page/comments fetch.
5. Partial runtime state no longer blocks safe recovery of portable hint data
   for fields the runtime row does not provide.
6. Genuinely changed sources still fetch, materialize, and update runtime and
   portable state correctly.
7. `docs/RULES.md` contains the authoritative statement of Confluence
   unchanged-source semantics for this fast path, and
   `docs/architecture/ARCHITECTURE.md` explains the design.
8. Skip-decision logging makes it possible to explain why a source did or did
   not take the startup fast path and whether attachment repair ran.
9. If portable manifest fields changed, the implementation also updates:
   - `docs/brain/SCHEMAS.md`
   - `docs/VERSIONING.md`
   - `docs/COMPATIBILITY.md`
   - compatibility tests covering the supported portable row
10. If runtime schema semantics changed, `docs/runtime/SCHEMAS.md` and runtime
    migration or rebuild coverage are updated in the same change set.

## Intentionally Preserved Open Decisions

These choices remain open for reviewer or approver scrutiny, but not in a way
that leaves the implementer guessing about behavior.

### 1. Where Confluence freshness fingerprint recovery should live

This plan does not pre-decide whether `metadata_fingerprint` remains runtime
only or gains a portable hint field. It does require an explicit Brain Format
and compatibility gate if the portable path is chosen.

### 2. Exact helper shape for lightweight attachment repair

Implementation may introduce a new unchanged-source repair helper or refactor
`process_attachments()`. What is not open is the required behavior: unchanged
sources must repair attachments without full page/comments fetch.

### 3. Whether timestamp semantics need a later bounded follow-up

This plan preserves the separate timestamp-semantics review after the startup
bug is fixed. It does not predetermine that `sync_hint.last_synced_utc` must
change.

## Risks and Mitigations

### Risk: Fast-path broadening hides real updates

Mitigation:

- keep changed-source cases in integration coverage
- keep the full-fetch requirement explicit and narrow
- make the Confluence unchanged-source contract durable before changing code

### Risk: Attachment repair regresses when decoupled from full fetch

Mitigation:

- require unchanged-source attachment repair to run explicitly
- test both missing attachment directory and missing attachment file cases
- keep later-cycle repair behavior in scope, not just startup behavior

### Risk: Portable field changes slip in without versioning work

Mitigation:

- make the Brain Format and compatibility gate a fixed decision
- require doc and compatibility-test updates in the same change set as any
  portable manifest change

### Risk: Timestamp debate delays the actual fix

Mitigation:

- keep the timestamp review in a later bounded phase
- do not block Phase 1 or Phase 2 on a broader semantics redesign unless the
  implementation proves it is strictly necessary

## Approval Requirements

This plan revision is ready for approval only when a reviewer or approver can
confirm all of the following from the plan text itself:

1. The plan clearly separates the startup fast-path bug from the later
   timestamp-semantics question.
2. The plan makes Confluence unchanged-source semantics explicit and durable:
   page version for page/comments freshness, plus separate attachment repair.
3. The plan states exactly how unchanged-source attachment repair still happens,
   when it runs, and how it differs from full fetch.
4. The plan preserves the rules expectation that deleted attachment files or
   directories may be re-downloaded on a later sync.
5. The state-composition sequence is specific enough that an implementer does
   not have to guess how partial runtime state merges with portable hints.
6. The portable-contract gate is explicit enough that adding durable manifest
   fields cannot happen without versioning, compatibility, and compatibility
   test work.
7. The acceptance criteria are strong enough to prove both the unchanged
   startup fast path and the unchanged-source attachment repair behavior.

## Next Step After Review

If review feedback identifies issues, the planner should create a further plan
revision artifact rather than editing this file.

If this revision is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow.

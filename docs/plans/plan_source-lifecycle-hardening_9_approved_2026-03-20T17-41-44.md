# Approval

Approved: 2026-03-20T17-41-44
Approved by: Codex GPT-5 (reviewer/approver)

Notes:

- revision 9 resolves the prior move-authority and administrative-listing blockers
- explicit finalization, process-boundary runtime-row handling, and sync-owned lifecycle ownership are now specified tightly enough for implementation
- acceptance criteria and fortress tests are concrete enough to review against without implementer guesswork
- no unresolved approval-blocking ambiguities remain

---

# plan_source-lifecycle-hardening_9

## Status

Plan revision 9.

This revision supersedes
`docs/plans/plan_source-lifecycle-hardening_8_2026-03-20.md` for review
purposes and incorporates the runtime-state authority clarification requested
after revision 8.

This plan revision is approved by this artifact for implementation.

## Objective

Harden source lifecycle as a first-class sync-owned subsystem so that source
creation, update, movement, missing handling, rediscovery, explicit
finalization, and administrative listing all flow through one authoritative
lifecycle surface across:

- the portable brain plane
- the machine-local runtime plane
- daemon-driven observation
- reconcile-driven observation
- CLI and MCP command entrypoints
- doctor diagnostics and repair entrypoints

The implementation should make source lifecycle restart-safe, adversarially
testable, and hard to accidentally bypass.

## Product Decisions Confirmed For This Revision

The following product decisions are confirmed and should be treated as settled
design input unless a later review artifact identifies a material conflict.

1. Removing portable `missing_since_utc` is an intentional portable contract
   change. This work targets Brain Format `1.2`, not an in-place silent edit to
   Brain Format `1.1`.
2. The release target for this work is app version `0.7.0`.
3. This work targets runtime DB schema `v27` because it introduces new
   machine-local source lifecycle coordination beyond the current `v26`
   polling-only source runtime model.
4. Portable `knowledge_state = missing` remains part of durable source truth.
5. Destructive finalization starts explicit-only:
   - daemon may determine local eligibility
   - background convergence must not perform destructive finalization
   - destructive cleanup occurs only through dedicated explicit lifecycle
     entrypoints
6. Portable `knowledge_state = stale` remains a compact durable trustability
   state. Stale cause stays in runtime diagnostics and operational records,
   not portable schema.
7. Missing sources remain registered while unresolved. Administrative source
   listing surfaces should return them rather than hiding them.
8. Doctor may diagnose and may invoke official non-private lifecycle repair
   operations, but it must not auto-apply destructive finalization by default.
9. Existing destructive doctor entrypoints do not survive as independent
   product surfaces in `0.7.0`; they are removed and replaced by the dedicated
   finalization entrypoints defined in this plan.
10. Persisted runtime lifecycle rows are machine-local cached history across
    process boundaries. After process start or brain re-attachment, they must
    be reconciled against the currently attached portable brain before they can
    influence lifecycle decisions.

## Authoritative Inputs

Stable authority for this revision:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`
- `docs/plans/plan_source-lifecycle-hardening_7_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_6_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_5_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_4_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_3_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_2_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_review_1_2026-03-20.md`
- `docs/plans/plan_source-state-boundary_2_approved_2026-03-19T19-05-47.md`
- `docs/plans/plan_source-fetch-hardening_2_approved_2026-03-18T11-00-51.md`

Code and tests that the implementation and later review must align with:

- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/application/source_state.py`
- `src/brain_sync/application/sync_events.py`
- `src/brain_sync/application/child_discovery.py`
- `src/brain_sync/application/reconcile.py`
- `src/brain_sync/application/doctor.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/brain/manifest.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sources/base.py`
- `src/brain_sync/sources/confluence/attachments.py`
- `tests/unit/test_architecture_boundaries.py`

## Versioning And Migration Decisions

### 1. Supported row target

This revision targets the new current compatibility row:

- app version: `0.7.0`
- Brain Format: `1.2`
- runtime DB schema: `v27`

The current `0.6.0 / Brain Format 1.1 / runtime v26` row becomes the supported
upgrade source rather than the current row.

### 2. Brain Format `1.2` change scope

Brain Format `1.2` is justified because this change alters:

- the source manifest field contract
- what is considered portable versus runtime state

The concrete Brain Format `1.2` portable change in scope here is:

- remove `missing_since_utc` from source manifests

The on-disk `brain.json` major family remains `{"version": 1}` because this is
still within the first major portable format family, consistent with the
existing versioning model.

### 3. Runtime DB schema `v27`

Runtime schema `v27` is justified because this change introduces explicit
machine-local coordination for:

- missing-source local observation history
- explicit-finalization eligibility inputs
- source-level lifecycle serialization

### 4. Migration mode

This revision chooses one explicit migration mode:

- Brain Format `1.1 -> 1.2`: deterministic guided portable migration
- runtime DB `v26 -> v27`: in-place migration

The implementation must update:

- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/GLOSSARY.md`
- `docs/RULES.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`

The implementation must not leave repository docs claiming that
`missing_since_utc` is part of the supported portable contract after the
migration lands.

## Known Required Spec Updates

This revision intentionally conflicts with current repository docs in a few
named places, and those conflicts must be resolved as part of implementation.

The implementation must make at least these specific updates:

1. `docs/brain/README.md`
   - update the entry-point version text so it no longer claims Brain Format
     `1.0` is current
   - keep the README aligned with Brain Format `1.2` and the revised portable
     source lifecycle contract
2. `docs/brain/SCHEMAS.md`
   - remove `missing_since_utc` from the source manifest schema
   - update the source-manifest state matrix accordingly
   - update the current Brain Format label from `1.1` to `1.2`
3. `docs/GLOSSARY.md`
   - remove the current "portable anomaly `missing_since_utc`" wording
   - update glossary text for the two-stage missing protocol so it no longer
     treats the portable timestamp as the grace-period anchor
   - clarify that missing sources remain registered and visible in
     administrative source registry views
   - preserve the explicit statement that runtime DB state is blind to
     portable-brain mutations that happened while the runtime was detached
4. `docs/RULES.md`
   - replace the current two-stage missing protocol language that refers to
     writing `missing_since_utc`
   - replace current text that reserves second-stage cleanup for startup
     reconcile, explicit reconcile, or explicit doctor cleanup
    - update package-boundary text to remove the current `sync -> application`
      lifecycle exception surface when the code move lands
   - preserve the explicit rule that process start or brain re-attachment must
     treat persisted runtime rows as non-authoritative local history until
     reconciled against the currently attached portable brain
5. `docs/runtime/README.md`
   - update the runtime entry point to describe runtime schema `v27` and the
     role of `source_lifecycle_runtime`
   - keep the runtime README aligned with the polling-versus-lifecycle split
6. `docs/architecture/ARCHITECTURE.md`
   - remove the current statement that watcher policy and child-discovery
     policy live under `application/`
   - replace it with the new sync-owned lifecycle/module split
   - preserve the explicit process-boundary rule that restarted runtimes must
     assume the portable brain may have changed while they were offline
7. `docs/runtime/SCHEMAS.md`
   - add runtime schema `v27`
   - document `source_lifecycle_runtime`
   - keep `sync_polling` explicitly polling-only
   - preserve the explicit startup and re-attachment rule that runtime rows are
     cached local history, not cross-process proof of current source state
8. `docs/VERSIONING.md`
   - update the current row to `0.7.0 / Brain Format 1.2 / runtime v27`
9. `docs/COMPATIBILITY.md`
   - move `0.6.0 / Brain Format 1.1 / runtime v26` to upgrade-source status
   - add the `0.7.0 / Brain Format 1.2 / runtime v27` current row
   - carry forward the sharp stale compatibility rule
10. `README.md`
   - update user-facing CLI command documentation for the dedicated
     `finalize-missing` action
   - update user-facing source-listing documentation so administrative list
     output exposes lifecycle state explicitly for registered sources,
     including missing ones
   - remove or revise user-facing references to destructive doctor cleanup if
     they still appear
   - document the official MCP finalization surface
     `brain_sync_finalize_missing`
   - update MCP tool documentation so the old destructive doctor surface does
     not remain implied as an official user-facing entrypoint

## Problem Statement

The repository now has a much sharper portable source-state contract than it
did before, but the current implementation still spreads source lifecycle
authority across too many paths:

- `application/sources.py` handles registration, update, movement, missing
  transitions, explicit removal, reconcile, and migration
- `sync/daemon.py` coordinates due polling using an in-memory source view that
  can drift from later portable/runtime writes
- `sync/pipeline.py` still participates in lifecycle-sensitive fast paths and
  materialization outcomes
- watcher consequences are split between daemon flow and application-owned
  sync-event helpers
- doctor still reaches into source-management internals

This produces three classes of risk:

1. **Competing writer risk**: CLI, MCP, daemon, watcher repair, reconcile, and
   doctor can act against stale projections or private helper seams.
2. **Destructive cleanup ambiguity**: startup reconcile, explicit reconcile,
   and doctor cleanup all currently have destructive authority around missing
   sources.
3. **Package-boundary drift**: the documented `sync -> application` exception
   in `sync/daemon.py` is real code debt rather than a stable design target.

## Safeguards For Other Areas

This revision should not weaken adjacent subsystems while hardening source
lifecycle.

The implementation must preserve or intentionally restate these neighboring
truths:

- regen remains a peer subsystem; source lifecycle hardening must not move regen
  policy into `sync/`
- `sources/` remains provider-specific only; this revision must not turn source
  adapters into lifecycle owners
- query, browse, and local-file workflows must remain behaviorally stable
  except where administrative source-listing semantics intentionally change to
  include missing registered sources
- the existing exact off-graph allowance for
  `src/brain_sync/sources/confluence/attachments.py` must either remain exact
  or be intentionally updated in rules and architecture tests together

## Scope

In scope for the implementation stage:

- a source lifecycle contract with explicit:
  - commands
  - observations
  - invariants
  - transition table
  - commit ordering rules
  - concurrency rules
  - failure semantics
- Brain Format `1.2` manifest change removing `missing_since_utc`
- runtime schema `v27` support for missing/finalization coordination
- dedicated explicit finalization entrypoints for CLI and MCP
- sync-owned lifecycle policy and orchestration seams
- moving source lifecycle ownership from `application/` into `sync/`
- making startup reconcile and explicit reconcile non-destructive with respect
  to finalization
- tightening doctor authority to official lifecycle APIs only
- restoring accurate administrative listing of missing sources
- strengthening tests across unit, integration, mcp, system, compatibility,
  and e2e tiers

## Non-goals

- no broad redesign of regen policy or prompt behavior
- no broad redesign of query/search architecture
- no new portable stale-cause taxonomy
- no new source-adapter feature work beyond lifecycle hardening needs
- no daemon auto-finalization in this revision
- no broad change to local file management, browse, or query semantics outside
  source lifecycle admin surfaces

## Lifecycle Ontology

This revision keeps the lifecycle model reducer-first, not event-first.

The core concepts are:

- **commands**: intentional requests from CLI, MCP, doctor repair, or internal
  sync-owned flows
- **observations**: facts reported by watcher, reconcile, adapter update
  checks, or materialization outcomes
- **lifecycle policy**: pure transition rules and invariants
- **lifecycle orchestrator**: fresh-read revalidation, commit ordering,
  repository calls, runtime writes, and side-effect emission
- **drivers**: daemon, reconcile command, watcher reduction, CLI, MCP, and
  doctor entrypoints

Correctness is guaranteed by fresh revalidation at commit time, not by shared
timing or inherited observation history.

Different runtimes may disagree on when a missing source becomes locally
eligible for explicit finalization. They must not disagree on whether a
finalization commit is valid once the finalizing runtime has revalidated the
latest portable and runtime state.

## Portable Source Contract

### Portable source manifest `1.2`

The `1.2` source manifest should contain:

- `version`
- `canonical_id`
- `source_url`
- `source_type`
- `sync_attachments`
- `knowledge_path`
- `knowledge_state`
- `content_hash`
- `remote_fingerprint`
- `materialized_utc`

It should not contain:

- `missing_since_utc`
- any machine-local timing or grace-window field
- any portable stale-cause taxonomy

### Portable `knowledge_state`

Portable states remain:

- `awaiting`
- `materialized`
- `stale`
- `missing`

This revision carries forward the existing sharp semantics:

- `stale` means the durable anchor exists, but the current materialized
  representation is not trusted for downstream use until a successful full
  re-materialization
- `missing` means the source remains registered but unresolved

`stale` must continue to forbid unchanged-source fast paths even when the
stored `remote_fingerprint` still matches. That compatibility rule remains
mandatory in Brain Format `1.2`.

## Runtime Contract

### Runtime tables

This revision keeps `sync_polling` polling-only and adds a new runtime table:

- `source_lifecycle_runtime`

`source_lifecycle_runtime` is keyed by `canonical_id` and owns only
machine-local lifecycle coordination for registered sources that need local
observation history or source-level serialization.

Rows are not required for every registered source. A row must exist only when
at least one of these is true:

- the source is in portable `knowledge_state = missing`
- the source is undergoing explicit finalization coordination
- the source currently holds or is waiting on a source-level lifecycle lease

The required `v27` fields are:

- `canonical_id`
- `local_missing_first_observed_utc`
- `local_missing_last_confirmed_utc`
- `missing_confirmation_count`
- `lease_owner`
- `lease_expires_utc`

Persisted `source_lifecycle_runtime` rows are not cross-process claims about
current brain state. After process start or brain re-attachment, an existing
row may be reused only as machine-local history until the current process has
reconciled it against the currently attached manifest/filesystem state for that
source.

`sync_polling` remains active-polling-only. Missing sources must leave
`sync_polling` as part of first-stage missing handling, and they must remain in
`source_lifecycle_runtime` until:

- successful rediscovery / successful full re-materialization clears missing
  coordination
- or explicit finalization removes the source entirely

### Process-boundary rule for existing local runtime rows

This revision derives directly from the repository-wide authority invariant:
runtime state is machine-local and blind to portable-brain mutations that
happened while no process was attached.

Therefore, when a process starts or re-attaches to a brain root and finds an
existing `source_lifecycle_runtime` row, it must treat that row as suspect
local history until current-process revalidation says otherwise.

An existing row must not by itself:

- assert that the source manifest still exists
- assert that the manifest still has the same `knowledge_state`
- assert that the source is still locally eligible for explicit finalization
- preserve source-level lease authority across process boundaries
- authorize any destructive or lifecycle-significant mutation

Startup reconcile, explicit reconcile, and explicit finalization preflight may
reuse persisted runtime rows as local history inputs, but only after they
re-check the currently attached portable brain and refresh, discard, or ignore
runtime fields that no longer match present reality.

### Local eligibility reducer for explicit finalization

This revision keeps the existing two-stage missing model, but makes it
machine-local rather than portable-timestamp-based.

A source is locally eligible for explicit finalization only if all of the
following are true at the start of the destructive commit path:

1. the manifest still exists
2. the manifest still says `knowledge_state = missing`
3. a local `source_lifecycle_runtime` row already exists
4. `missing_confirmation_count >= 2`
5. the current explicit-finalization invocation performs fresh local
   revalidation against the currently attached portable brain and still
   observes the source as missing
6. no conflicting source-level lifecycle lease is active

Reducer rules:

- the first qualifying local missing observation creates the runtime row with
  `missing_confirmation_count = 1`
- a later independent qualifying local missing confirmation increments the
  count to at least `2`
- startup reconcile and explicit reconcile both record the same local missing
  confirmation semantics; neither has destructive authority
- explicit finalization preflight may create or refresh the runtime row, but it
  must not both create the first local row and destructively finalize in the
  same invocation
- a persisted runtime row from an earlier process is not sufficient by itself
  to preserve local finalization eligibility; the current process must freshly
  confirm missing state before treating the row as current
- if explicit finalization is invoked with no local row, or with
  `missing_confirmation_count < 2`, it must return a non-finalized result after
  recording or refreshing local confirmation state

This revision does not introduce a separate `source_lifecycle_runtime stale`
state. Finalization gating relies only on the explicit reducer conditions
above, lease validity, and fresh revalidation at invocation time.

### Cross-machine rule for portable `missing`

When a machine reads a source manifest already in `knowledge_state = missing`
and has no local `source_lifecycle_runtime` row yet, it must treat the source
as:

- still registered
- unresolved
- visible in administrative source listing
- absent from active polling projection
- not yet locally eligible for explicit finalization

That machine must create or refresh local runtime coordination only from a
fresh local observation path such as:

- startup reconcile
- explicit reconcile
- explicit finalization preflight

Portable `missing` is inherited across machines. Local finalization eligibility
is not.

The same rule applies across process boundaries on the same machine: persisted
local runtime rows do not carry lifecycle truth forward by themselves.

## Explicit Finalization Entry Points

This revision chooses one exact product rule for destructive finalization:

- startup daemon reconcile loses destructive finalization authority
- explicit `reconcile` loses destructive finalization authority
- doctor remains non-destructive by default and loses any default destructive
  missing-source cleanup path
- destructive finalization is performed only through dedicated explicit
  lifecycle entrypoints

The official entrypoints are:

- CLI: `brain-sync finalize-missing`
- MCP: `brain_sync_finalize_missing`

### Exact user-facing contract for explicit finalization

This revision makes the finalization surface exact and per-source.

`0.7.0` does not introduce bulk missing-source finalization. There is no
`--all`, no path-filter batch mode, and no MCP bulk-finalize variant in this
revision. That keeps the destructive surface aligned with per-`canonical_id`
leases and per-source local eligibility.

CLI contract:

- command shape: `brain-sync finalize-missing <canonical-id>`
- target identity: canonical ID only
- source URL, knowledge path, and bulk targeting are not accepted by this
  command in `0.7.0`

MCP contract:

- tool name: `brain_sync_finalize_missing`
- required argument: `canonical_id: str`
- no bulk flag, path filter, or URL-targeting argument in `0.7.0`

CLI and MCP must expose the same targeting semantics and the same terminal
result states.

The result contract is:

- `finalized`
  - the source was still registered, still `missing`, locally eligible, and
    was destructively finalized
- `pending_confirmation`
  - the source is still registered and `missing`, but local confirmation has
    not yet reached `missing_confirmation_count >= 2`
- `lease_conflict`
  - another lifecycle operation currently owns the source-level lease
- `not_missing`
  - the source exists but is no longer in portable `knowledge_state = missing`
- `not_found`
  - no registered source exists for that canonical ID

MCP payload contract:

- every handled lifecycle outcome must include `result_state`
- every handled lifecycle outcome must include `finalized: bool`
- every handled lifecycle outcome other than `not_found` must include
  `canonical_id`
- `not_found` must include the requested `canonical_id`

For `pending_confirmation`, the result must include enough information for the
caller to understand why no destructive action occurred:

- `canonical_id`
- `result_state: "pending_confirmation"`
- current portable `knowledge_state`
- current `missing_confirmation_count`
- `eligible: false`
- `finalized: false`

For `finalized`, the result must include at least:

- `canonical_id`
- `result_state: "finalized"`
- `finalized: true`

For `lease_conflict`, the result must include at least:

- `canonical_id`
- `result_state: "lease_conflict"`
- `finalized: false`
- `eligible: false`
- a user-facing `message`

For `not_missing`, the result must include at least:

- `canonical_id`
- `result_state: "not_missing"`
- current portable `knowledge_state`
- `finalized: false`

For `not_found`, the result must include at least:

- requested `canonical_id`
- `result_state: "not_found"`
- `finalized: false`
- `error: "not_found"`

MCP status contract:

- `finalized`, `pending_confirmation`, `lease_conflict`, and `not_missing`
  are handled lifecycle outcomes and must return `status: "ok"`
- `not_found` must return `status: "error"` with `error: "not_found"`
- malformed arguments or internal failures remain outside this lifecycle
  terminal-state contract and may use normal tool-error handling

CLI and MCP may include extra non-authoritative detail, but they must not
invent additional terminal states without a documented compatibility decision.

CLI contract:

- the CLI must surface the terminal `result_state` label in user-visible output
- `finalized`, `pending_confirmation`, and `not_missing` are success-like and
  must exit with status code `0`
- `lease_conflict` and `not_found` are non-success terminal outcomes and must
  exit with status code `1`

Current destructive doctor surfaces do not remain as parallel product
entrypoints:

- `brain-sync doctor --deregister-missing` is removed
- `brain_sync_doctor(mode="deregister_missing")` is removed

If compatibility handling is needed during migration, those old doctor surfaces
must fail with a directed migration message pointing users to
`finalize-missing`; they must not survive as hidden aliases or independent
destructive entrypoints.

These entrypoints operate only on registered sources already in portable
`knowledge_state = missing`.

They must:

- perform fresh revalidation
- refuse to finalize when local runtime coordination is absent or insufficient
- record auditable operational events
- be idempotent when retried

This revision intentionally keeps finalization as a dedicated action rather
than a flag on `reconcile`, so that reconciliation stays non-destructive and
the destructive boundary remains obvious in docs, logs, tests, and interface
semantics.

## Registered-Source Move Command Contract

This revision treats user-driven registered-source `move source` flow as a
first-class lifecycle command, not only as an implied consequence of
watcher-observed local movement.

The official user-facing move surfaces remain:

- CLI: `brain-sync move <source> --to <path>`
- MCP: `brain_sync_move(source, to_path)`

This revision does not broaden move targeting semantics beyond the current
compatibility surfaces. It does make the ownership rule exact:

- `sync/lifecycle.py` owns every registered-source move flow
- this includes explicit CLI/MCP move requests, watcher-observed folder moves
  that affect registered sources, and fileless path retargeting for still
  registered sources
- `sync/watcher_events.py` may classify and forward folder-move observations,
  but it must not perform registered-source manifest rewrites or source-owned
  file moves itself
- `application/sources.py`, CLI handlers, and MCP transport code may remain
  thin facades, but they must not own the repository move/path mutation
  sequence for registered sources

Registered-source move authority is closed as follows:

- `BrainRepository.move_knowledge_tree()`
- `BrainRepository.move_source_attachment_dir()`
- `BrainRepository.set_source_area_path()`
- `BrainRepository.sync_manifest_to_found_path()`
- `BrainRepository.apply_folder_move_to_manifests()`

For registered-source move flows, those methods are reserved to
`sync/lifecycle.py`. No other production module may call them for move
handling.

## Administrative Listing Contract

This revision distinguishes two source views:

1. **Active sync projection**
   - used by daemon polling and scheduling
   - contains only sources eligible for active polling/materialization work
   - excludes `knowledge_state = missing`
2. **Administrative source registry view**
   - used by CLI and MCP listing/admin surfaces
   - includes all registered sources, including `knowledge_state = missing`
   - includes lifecycle state explicitly so users can inspect and act on
     missing sources still in lifecycle purgatory

The implementation must update source listing APIs so that missing sources are
returned in administrative views rather than hidden.

Exact listing obligations:

- the administrative source registry view model must carry portable
  `knowledge_state` explicitly for every registered source
- MCP `brain_sync_list` must include `knowledge_state` on every returned
  source object, using the portable lifecycle vocabulary unchanged
- CLI `brain-sync list` must print `State: <knowledge_state>` for every
  returned source, including `State: missing` for missing registered sources
- CLI `--status` output may add polling and scheduler detail, but lifecycle
  state must remain visible even without `--status`
- CLI and MCP administrative listings must agree on lifecycle-state
  vocabulary for the same source

## Target Package And Module Map

This revision intentionally makes the target module map concrete so that `sync`
does not become a new monolith.

### `sync/` target ownership

- `sync/lifecycle_policy.py`
  - pure transition rules only
  - no repository access
  - no direct filesystem access
  - no runtime DB access
- `sync/lifecycle.py`
  - authoritative lifecycle orchestrator
  - official mutation entrypoints for source lifecycle
  - fresh-read revalidation and commit ordering
  - owns registered-source move flow for explicit CLI/MCP moves and
    watcher-observed folder moves
- `sync/state.py`
  - source lifecycle views and composition helpers
  - active sync projection versus administrative registry view
- `sync/reconcile.py`
  - source-specific reconcile scan and observation generation
  - non-destructive only
- `sync/finalization.py`
  - explicit destructive finalization flow
  - source-level serialization and revalidation
- `sync/watcher_events.py`
  - watcher observations reduced into lifecycle/orchestration calls
- `sync/child_discovery.py`
  - child-source registration through lifecycle APIs
- `sync/pipeline.py`
  - fetch and assemble source content
  - no independent lifecycle mutation authority
  - returns fetch/materialization inputs to lifecycle orchestration instead of
    calling `BrainRepository.materialize_markdown()` directly for registered
    sources
- `sync/daemon.py`
  - driver only: scheduler loop, watcher hookup, shutdown, invoking lifecycle
    APIs

### What remains in `application/`

- thin transport-neutral facades for CLI/MCP-facing source admin calls that
  delegate registered-source lifecycle work, including `move`, to official
  sync lifecycle APIs
- non-source application workflows such as browse, local files, placement,
  status, regen entrypoints, and init
- knowledge-tree reconcile orchestration only if it remains distinct from
  source reconcile
- doctor diagnostics and non-destructive repair entrypoints that call official
  lifecycle APIs

### Architecture boundary obligations

This revision requires intentional updates to:

- `docs/architecture/ARCHITECTURE.md`
- `docs/RULES.md`
- `tests/unit/test_architecture_boundaries.py`

Specifically:

- remove the current `sync/daemon.py -> application.*` exception surface
- update architecture text that currently places watcher policy and child
  discovery under `application/`
- add boundary tests that enforce:
  - zero production `sync -> application` imports after the refactor lands
  - no IO-layer imports inside `sync/lifecycle_policy.py`
  - `src/brain_sync/sync/lifecycle.py` and
    `src/brain_sync/sync/finalization.py` are the only production modules
    allowed to call the reserved `BrainRepository` source lifecycle mutation
    methods:
    - `save_source_manifest`
    - `update_source_sync_settings`
    - `mark_source_missing`
    - `clear_source_missing`
    - `mark_source_stale`
    - `set_source_area_path`
    - `sync_manifest_to_found_path`
    - `materialize_markdown`
    - `move_knowledge_tree`
    - `move_source_attachment_dir`
    - `apply_folder_move_to_manifests`
    - `delete_source_registration`
    - `remove_source_owned_files`
    - `remove_source_managed_artifacts`
  - within that reserved set, registered-source move methods
    `move_knowledge_tree()`, `move_source_attachment_dir()`,
    `set_source_area_path()`, `sync_manifest_to_found_path()`, and
    `apply_folder_move_to_manifests()` are reserved to
    `src/brain_sync/sync/lifecycle.py` only
  - `src/brain_sync/sync/pipeline.py` may compute content, filenames,
    fingerprints, and other materialization inputs, but it must not call
    `BrainRepository.materialize_markdown()` directly for registered-source
    lifecycle work
  - registered-source materialization must be invoked only through
    `sync/lifecycle.py` after fresh state revalidation, even if
    `sync/pipeline.py` remains the fetch/assembly worker
  - `sync/watcher_events.py` and watcher-reduction helpers must not call
    `apply_folder_move_to_manifests()` directly; folder-move observations must
    route through `sync/lifecycle.py`
  - CLI/MCP move entrypoints and any remaining `application/` facades must not
    call registered-source move methods directly; they must delegate to
    `sync/lifecycle.py`
  - doctor may continue to use non-lifecycle `BrainRepository` reads and
    diagnostics such as orphan inspection, but it must not call any reserved
    source lifecycle mutation method, including `save_source_manifest()`
  - `sources/confluence/attachments.py` may continue to use attachment and
    directory helpers, but it must not call any reserved source lifecycle
    mutation method
  - no production module outside `brain.repository` may import manifest-level
    mutation primitives directly for source lifecycle writes
  - the architecture test harness should enforce the reserved-method contract
    by AST call-site inspection of `BrainRepository` method calls, not by
    import-graph checks alone

## Lifecycle Invariants

The implementation must preserve at least the following invariants:

1. Only official sync lifecycle APIs may mutate portable source lifecycle
   truth.
2. Watcher, reconcile, daemon loop, CLI, MCP, and doctor must not mutate
   source manifests directly.
3. `sync/lifecycle_policy.py` remains pure and contains no portable or runtime
   IO.
4. Runtime timing, grace windows, and observation history are machine-local and
   must not re-enter the portable schema.
5. A missing source remains registered until explicit finalization.
6. A missing source remains in runtime lifecycle coordination until explicit
   finalization or successful rediscovery/materialization.
7. `stale` is strictly non-trustable for fast paths.
8. Destructive finalization requires fresh revalidation against latest portable
   and runtime state.
9. Every lifecycle step must be safe to retry after interruption without
   corruption or double-deletion.
10. `sync/lifecycle.py` and `sync/finalization.py` are the only production
    sync modules allowed to call reserved `BrainRepository` source lifecycle
    mutation methods for source registration, source settings updates, missing
    transitions, path repair, registered-source materialization,
    folder-move manifest rewrites, explicit remove, and explicit finalization.
11. Registered-source `move source` is a first-class lifecycle command owned
    by `sync/lifecycle.py`; explicit CLI/MCP move and watcher-observed move
    flows must not remain parallel application-owned mutation paths.
12. After process start or brain re-attachment, persisted runtime lifecycle
    rows are non-authoritative local history and must be reconciled against
    the current portable brain before they influence lifecycle actions.

## Transition Table Requirements

The implementation revision derived from this artifact must include a full
transition table. At minimum it must cover:

- register source
- update settings
- first successful materialization
- unchanged-source poll while `materialized`
- explicit move source
- local move observed
- local delete / local missing observed
- upstream missing observed
- rediscovery while `missing`
- successful re-materialization from `stale`
- explicit finalization preflight
- explicit finalization commit
- explicit remove source
- child discovery registration

For each transition it must specify:

- allowed prior states
- resulting portable state
- runtime coordination changes
- whether the source remains in active polling projection
- whether the source remains in administrative listing
- whether materialized files remain, move, or delete
- required revalidation

## Commit Ordering Rules

This revision elevates commit ordering to first-class contract status.

### Registration

1. Write the portable manifest first.
2. Create the `sync_polling` row second for the newly registered source.
3. Do not create a `source_lifecycle_runtime` row for ordinary registration.
4. Only then expose the source to active polling.

### Explicit move source

1. Acquire the per-source lifecycle lease and reload the latest manifest.
2. Revalidate that the source is still registered and that no conflicting
   lifecycle operation currently owns the source.
3. If a materialized tree exists at the old location, move the knowledge tree
   first.
4. Move any remaining source-owned attachment directory only if it still needs
   relocation after the primary tree move.
5. Rewrite portable source path truth through
   `sync_manifest_to_found_path()` when a relocated file is found, or through
   `set_source_area_path()` when the source remains registered but no
   materialized file is currently present.
6. Refresh runtime/source views only after the portable move state is
   coherent, and keep the source visible in administrative listing
   throughout.

This preserves the repository rule that disk movement precedes durable state
updates while keeping retry after interruption safe: a repeated invocation may
observe files already at the destination and complete only the portable path
repair.

### First-stage missing observation

1. Write portable `knowledge_state = missing` first.
2. Create or update `source_lifecycle_runtime`.
3. Remove the source from `sync_polling`.
4. Keep the source visible in administrative listing.

### Rediscovery or path repair

1. Write updated portable path / lifecycle state first.
2. Clear runtime missing coordination second.
3. Restore active polling eligibility after the portable state is consistent.

### Materialization

1. Fetch and assemble content.
2. Write materialized files.
3. Commit portable materialized lifecycle state.
4. Clear missing runtime coordination if present.
5. Restore or update active polling state.

The implementation must prove that a crash after file write but before later
state updates is safe to retry and cannot silently bypass `stale`/`missing`
trust rules.

### Explicit finalization

1. Acquire source-level lifecycle lease.
2. Reload latest portable manifest and runtime lifecycle record.
3. Revalidate:
   - manifest still exists
   - manifest is still `knowledge_state = missing`
   - local runtime coordination still exists
   - source is still locally eligible
   - no rediscovery or move invalidated the action
4. Remove source-owned files and managed artifacts idempotently.
5. Remove runtime coordination rows.
6. Delete the source manifest last.

Deleting the manifest last is required so interrupted finalization remains
retry-safe rather than orphaning an undeclared managed source file.

After manifest deletion, no authoritative lifecycle cleanup remains. Only
non-authoritative best-effort telemetry or log emission may still occur, and
those tails must be safe to skip or replay without changing source truth.

## Concurrency Model

This revision adopts the following concurrency rules:

1. Source lifecycle mutation is serialized per `canonical_id`.
2. Destructive finalization must use the source-level lifecycle lease in
   runtime state.
3. Daemon and explicit commands may race, but correctness comes from fresh-read
   revalidation before commit rather than from trusting stale in-memory views.
4. Watcher and reconcile may report observations concurrently, but they must
   route through official lifecycle APIs rather than writing state privately.
5. Multi-runtime / shared-brain correctness is guaranteed by:
   - portable lifecycle truth in the manifest
   - local runtime coordination per machine
   - fresh revalidation at destructive commit time
6. A restarted process must treat carried-forward runtime lifecycle rows as
   suspect local history until startup or preflight revalidation confirms they
   still match the currently attached portable brain.

## Failure Model

The implementation must preserve restart safety for at least these failure
points:

- crash after portable missing write but before runtime lifecycle row write
- crash after runtime lifecycle row write but before `sync_polling` removal
- crash after file materialization but before portable materialized update
- crash during explicit finalization before manifest deletion
- crash after runtime coordination cleanup but before manifest deletion
- crash after manifest deletion but before non-authoritative telemetry/log tail

The required guarantee is:

- any partial lifecycle step is safe to retry
- no partial step may corrupt source truth
- no partial step may produce double-deletion as a normal retry consequence

## Workstreams

### Workstream 1: Contract And Documentation Alignment

Goals:

- define Brain Format `1.2` and runtime schema `v27`
- update schemas, glossary, rules, architecture, versioning, and compatibility
  docs to match the revised lifecycle contract
- remove all claims that `missing_since_utc` is still part of the supported
  portable contract

### Workstream 2: Runtime Lifecycle Coordination

Goals:

- add `source_lifecycle_runtime`
- keep missing sources in runtime coordination until explicit finalization or
  rediscovery
- separate active polling state from lifecycle coordination state

### Workstream 3: Sync-Owned Lifecycle Surface

Goals:

- introduce the `sync` module split described above
- move lifecycle authority out of `application/`
- move registered-source explicit move ownership into `sync/lifecycle.py`
- preserve a pure policy layer and a separate IO-owning orchestrator

### Workstream 4: Explicit Finalization And Admin Surfaces

Goals:

- add dedicated CLI and MCP finalization entrypoints
- make `reconcile` non-destructive
- make doctor non-destructive by default
- return missing sources in administrative listing surfaces
- expose lifecycle state explicitly in CLI and MCP administrative listings

### Workstream 5: Fortress Testing And Boundary Enforcement

Goals:

- harden lifecycle invariants against regression
- close package-boundary seams intentionally
- prove restart safety and contention handling under realistic daemon/CLI/MCP
  competition

## Acceptance Criteria

The implementation should not be considered complete unless it demonstrates at
least the following:

1. Brain Format `1.2` source manifests no longer contain `missing_since_utc`.
2. Runtime DB schema `v27` exists and carries missing/finalization
   coordination in `source_lifecycle_runtime`.
3. Startup and re-attachment treat persisted lifecycle runtime rows as
   non-authoritative local history; reused rows are reconciled against the
   currently attached portable brain before they influence lifecycle actions.
4. The compatibility row is updated to `0.7.0 / Brain Format 1.2 / runtime
   schema v27`, with the `0.6.0 / 1.1 / v26` row retained as an upgrade source.
5. Startup reconcile is non-destructive with respect to missing-source
   finalization.
6. Explicit `reconcile` is non-destructive with respect to missing-source
   finalization.
7. Explicit finalization requires an existing local runtime row plus
   `missing_confirmation_count >= 2`; the first local observation and the
   destructive finalization commit may not occur in the same invocation.
8. `brain-sync finalize-missing` is a per-source command with exact target
   `canonical-id` input only; bulk finalization is out of scope for `0.7.0`.
9. `brain_sync_finalize_missing` is a per-source MCP tool with exact input
   `canonical_id: str`; bulk finalization is out of scope for `0.7.0`.
10. CLI and MCP finalization surfaces share the same terminal result states:
   `finalized`, `pending_confirmation`, `lease_conflict`, `not_missing`, and
   `not_found`.
11. MCP finalization responses include the documented minimum fields for each
    terminal result state, including `lease_conflict`, `not_missing`, and
    `not_found`.
12. CLI finalization surfaces the terminal result label and uses exact exit
    semantics: exit `0` for `finalized`, `pending_confirmation`, and
    `not_missing`; exit `1` for `lease_conflict` and `not_found`.
13. Doctor is non-destructive by default and does not bypass lifecycle APIs.
14. The old doctor destructive entrypoints are removed or rejected with a
   directed migration hint; they do not survive as independent destructive
   surfaces.
15. Registered-source `move source` is a first-class lifecycle command owned
    by `sync/lifecycle.py`; CLI `move`, MCP `brain_sync_move`, and watcher
    move reduction do not remain parallel application-owned repository
    mutation paths.
16. Administrative listing surfaces expose lifecycle state explicitly for
    every registered source, and missing sources remain visible in those
    listings.
17. CLI `list` prints `State: <knowledge_state>` for every returned source,
    including `State: missing` for missing registered sources; MCP
    `brain_sync_list` returns the matching `knowledge_state` field.
18. Missing sources retain runtime lifecycle coordination until explicit
    finalization or rediscovery/materialization.
19. `stale` still forbids unchanged-source fast paths until successful full
    re-materialization.
20. `sync/daemon.py` no longer depends on `application.*` lifecycle helpers.
21. Architecture-boundary tests enforce zero production `sync -> application`
    imports and name the approved lifecycle orchestrator modules explicitly.
22. Architecture-boundary tests reserve the named `BrainRepository` lifecycle
    mutation methods for source registration, settings updates, missing
    transitions, path repair, registered-source materialization,
    registered-source move file relocation, folder-move manifest rewrites,
    explicit remove, and explicit finalization to `sync/lifecycle.py` and
    `sync/finalization.py`, with registered-source move methods reserved to
    `sync/lifecycle.py`.
23. `sync/lifecycle_policy.py` remains IO-free and is guarded by tests.
24. Brain, runtime, architecture, glossary, schema, versioning,
    compatibility, and README entry-point docs are all updated consistently
    with the implementation.

## Test Fortress Expectations

The implementation and review must plan and land coverage at these levels.

### Unit

- transition tests for each lifecycle command and observation
- explicit tests for the `move source` lifecycle command distinct from
  watcher-observed local move handling
- exact reducer tests for local explicit-finalization eligibility
- exact tests proving a reused runtime lifecycle row from a prior process is
  only local history until current-process revalidation refreshes it
- exact terminal-state tests for per-source finalization results
- exact CLI exit-semantics tests for per-source finalization results
- revalidation tests for explicit finalization
- administrative-listing view tests proving `knowledge_state` is exposed for
  every registered source, including missing ones
- pure-policy tests proving no IO in `sync/lifecycle_policy.py`
- stale-rule tests proving `stale` cannot hit unchanged fast paths
- architecture-boundary tests removing the current `sync -> application`
  exception list rather than relocating it
- architecture-boundary tests naming `sync/lifecycle.py` and
  `sync/finalization.py` as the approved lifecycle orchestrators
- architecture-boundary tests reserving the named `BrainRepository` lifecycle
  mutation methods to those orchestrators by AST call-site inspection
- architecture-boundary tests reserving `materialize_markdown()` for
  registered-source lifecycle work to the approved orchestrator path
- architecture-boundary tests reserving `move_knowledge_tree()`,
  `move_source_attachment_dir()`, `set_source_area_path()`,
  `sync_manifest_to_found_path()`, and `apply_folder_move_to_manifests()` to
  `sync/lifecycle.py` for registered-source move flows
- architecture-boundary tests reserving `apply_folder_move_to_manifests()` to
  the approved orchestrator path

### Integration

- Brain Format `1.1 -> 1.2` migration for source manifests
- runtime `v26 -> v27` migration
- missing-source runtime coordination persistence
- missing sources leave `sync_polling` and retain only
  `source_lifecycle_runtime` coordination
- reused `source_lifecycle_runtime` rows are reconciled against current
  manifest/filesystem state on process start rather than trusted blindly
- first local missing observation does not finalize
- second local confirmation makes the source locally eligible
- a persisted row with `missing_confirmation_count >= 2` does not by itself
  preserve finalization eligibility across process restart
- rediscovery clearing missing coordination
- registered-source explicit move commit ordering and retry safety
- registered-source explicit move runs through lifecycle orchestration rather
  than direct application-owned repository mutation
- explicit finalization commit ordering and retry safety
- no authoritative lifecycle cleanup remains after manifest deletion
- registered-source materialization runs through lifecycle orchestration rather
  than direct pipeline-owned repository mutation
- doctor invoking official lifecycle APIs only

### MCP

- `brain_sync_list` returns `knowledge_state` for every registered source and
  returns missing registered sources with `knowledge_state = "missing"`
- `brain_sync_move` routes through official lifecycle APIs rather than a
  parallel application-owned move path
- `brain_sync_finalize_missing` exists and remains explicit/destructive only
- `brain_sync_finalize_missing` requires `canonical_id`
- `brain_sync_finalize_missing` rejects URL-targeting and bulk-targeting
- `brain_sync_finalize_missing` returns the exact documented terminal states
- `brain_sync_finalize_missing` returns the documented minimum payload fields
  for `pending_confirmation`, `lease_conflict`, `not_missing`, and `not_found`
- MCP source admin paths do not bypass lifecycle APIs
- `brain_sync_doctor(mode="deregister_missing")` is rejected or removed with
  directed migration guidance
- user-facing MCP docs include `brain_sync_finalize_missing`

### System

- CLI `list` returns missing registered sources and prints
  `State: <knowledge_state>` for each result
- CLI `list` prints `State: missing` for missing registered sources without
  requiring `--status`
- daemon startup revalidates reused lifecycle runtime rows against the current
  portable brain before they influence lifecycle behavior
- CLI `reconcile` is non-destructive
- CLI `move` remains a registered-source lifecycle command while daemon and
  other lifecycle flows are active
- CLI `finalize-missing` performs revalidation-safe destructive cleanup
- CLI `finalize-missing <canonical-id>` is per-source only
- CLI `finalize-missing` rejects URL-targeting and bulk-targeting
- CLI `finalize-missing` returns the exact documented terminal states
- CLI `finalize-missing` uses the documented exit semantics for all terminal
  states
- daemon startup does not destructively finalize missing sources
- `brain-sync doctor --deregister-missing` is rejected or removed with directed
  migration guidance

### Compatibility

- fresh Brain Format `1.2` init
- guided Brain Format `1.1 -> 1.2` migration
- runtime `v26 -> v27` in-place migration
- runtime rebuild without durable source-truth loss
- cross-machine continuation from shared manifest truth with local missing
  eligibility rebuilt per machine
- process restart with a reused runtime lifecycle row proving eligibility is
  rebuilt from current portable truth rather than inherited blindly
- `stale` forcing full re-materialization even when `remote_fingerprint`
  matches
- administrative listing still returns missing registered sources after
  migration and exposes `knowledge_state`
- brain/runtime README entry points match the supported `1.2 / v27` row

### E2E

- daemon on, CLI move of a registered source during polling through the
  official lifecycle owner
- daemon on, CLI remove of a registered source during polling
- daemon on, watcher-observed local delete entering portable `missing` without
  destructive finalization
- process restart after offline portable-brain mutation with reused runtime
  lifecycle rows revalidating before lifecycle action
- daemon off, offline delete, restart, non-destructive reconcile, explicit
  finalization
- source reappears while in portable `missing`
- shared brain with isolated runtime dirs proving local missing eligibility is
  rebuilt per machine
- child discovery and manual registration contention
- attachment-enabled unchanged source still respecting `stale` trust rules

## Review Focus

The next review pass should focus especially on:

- whether Brain Format `1.2` / runtime `v27` versioning and migration are
  stated tightly enough
- whether the cross-machine rule for portable `missing` is deterministic enough
- whether the process-boundary rule for reused runtime lifecycle rows is now
  explicit enough that startup cannot assume the brain is unchanged since the
  prior process
- whether the explicit finalization entrypoints fully replace current
  destructive reconcile paths and are exact enough as user-facing contracts
- whether the sync module map is concrete enough to avoid a new monolith
- whether the explicit move-source authority seam is now fully closed against
  current code reality, including file-move primitives and CLI/MCP ownership
- whether the reserved `BrainRepository` lifecycle-mutation set is now broad
  enough to close the authority surface against current code reality
- whether the CLI and MCP administrative listing contract is now exact enough
  to require lifecycle state visibility for missing registered sources
- whether the test fortress is strong enough to make this lifecycle layer hard
  to break accidentally

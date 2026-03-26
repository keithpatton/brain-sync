# plan_sync-source-command_2_2026-03-26: Direct Per-Source Forced Sync Command

## Status

Planning artifact only. This document is revision 2 of the `sync-source`
command plan and supersedes the canonical root plan for further review under
the `docs/plans/` workflow.

This revision resolves the review findings from
`docs/plans/plan_sync-source-command_review_1_2026-03-26.md` by fixing the
command contract, CLI outcome behavior, daemon-parity boundaries, and
verification expectations explicitly.

This file does not approve implementation by itself.

## Objective

Add a first-class forced-sync command for one active registered source that:

- performs one immediate sync attempt now
- works whether the daemon is running or not
- reuses the existing per-source lease and shared source-processing path
- persists normal post-attempt runtime state through existing owners
- does not depend on mutating `sync_polling` just to wake the daemon

The command is for one source only. This revision keeps the scope narrow:

- no inline regen in this phase
- no lease override
- no daemon restart or shutdown dependency
- no recursive or bulk child sync
- no scheduler-hack implementation via pre-emptive `sync_polling` mutation

## Authoritative Inputs

Implementation must treat these as the controlling inputs:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`

Implementation must also align with the current owning seams for the command:

- `src/brain_sync/interfaces/cli/parser.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sync/scheduler.py`
- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/runtime/repository.py`

## Fixed Design Decisions

### 1. Surface Scope And Transport Contract

This phase implements a new CLI command only:

- `brain-sync sync-source <source>`

This phase does not add a new MCP tool. That deferral is intentional to keep
the change narrowly focused on the CLI workflow.

However, the transport-neutral application contract is fixed now, and any
future MCP tool must use the same selector and result contract as the CLI.
There is no planned CLI/MCP semantic split for source selection or outcome
states.

### 2. Source Selector Contract

The command accepts exactly one source selector string named `source`.

Accepted selector forms:

- exact canonical ID
- exact registered source URL

Rejected as unsupported selector forms:

- knowledge paths
- filesystem paths
- partial URLs
- partial canonical IDs
- bulk targets

Resolution rules:

1. If the value is an exact canonical ID, resolve by canonical ID.
2. Otherwise, attempt exact registered source-URL match.
3. If neither resolves to an active registered source, return `not_found`.

Eligibility rule:

- `sync-source` targets the active polling set only.
- A manifest that exists only in durable `missing` state is not eligible for
  this command and returns `not_found` with a message that the source is not
  currently syncable through the active poll path.

Rationale:

- This matches the existing user-facing selector pattern already used by
  `remove` and `update`.
- It preserves one transport-neutral application function for CLI now and MCP
  later.
- It avoids inventing a special canonical-ID-only rule for a command that is
  otherwise a normal single-source management surface.

### 3. Application Contract

Add one transport-neutral application entrypoint in
`src/brain_sync/application/sources.py` for immediate single-source sync.

Required call shape:

- root-backed application function
- accepts `source: str`
- returns a stable result object rather than CLI-formatted text

Required result fields:

- `result_state`: one of `changed`, `unchanged`, `lease_conflict`,
  `not_found`, `remote_missing`, `error`
- `source`: original selector string
- `canonical_id`: resolved canonical ID when known
- `source_url`: resolved source URL when known
- `target_path`: resolved target path when known
- `changed`: `True` only for `changed`, `False` only for `unchanged`,
  otherwise `None`
- `knowledge_state`: populated when the command changes durable knowledge
  lifecycle state, including `missing` for `remote_missing`
- `lease_owner`: populated for `lease_conflict` when known
- `child_request_consumed`: whether a pending child-discovery request was
  cleared by this invocation
- `children_registered`: count of child sources registered in this invocation
- `message`: stable operator-facing summary text

The application layer owns selector resolution, lifecycle coordination, child
request handling, missing-source handling, post-attempt sync-progress
persistence, and result translation.

### 4. CLI Outcome Contract

The CLI handler must be a thin adapter:

- parse args
- resolve root
- call the application function once
- render the returned result in a fixed logging shape
- exit according to the fixed mapping below

Required output shape for all handled outcomes:

- first line: `Result: <result_state>`
- when available:
  - `Canonical ID: <canonical_id>`
  - `URL: <source_url>`
  - `Path: knowledge/<target_path>`
  - `Lease owner: <lease_owner>`
- final stable summary line from `result.message`

Exit-code mapping:

- `changed`: exit `0`
- `unchanged`: exit `0`
- `lease_conflict`: exit `1`
- `not_found`: exit `1`
- `remote_missing`: exit `1`
- `error`: exit `1`

Required summary semantics:

- `changed`: report that the source was synced immediately and remote content
  changed
- `unchanged`: report that the immediate sync completed and no remote changes
  were detected
- `lease_conflict`: report that another lifecycle owner already holds the
  source lease and identify the lease owner when available
- `not_found`: report that the selector did not resolve to an active
  registered source, including the "registered but currently missing" case
- `remote_missing`: report that the upstream source is unavailable and the
  source was marked `missing`
- `error`: report that the immediate sync failed unexpectedly; the stable
  summary line is part of the contract, while traceback detail remains
  implementation-level logging rather than approval-level output text

CLI acceptance is not "best effort":

- system tests must assert both exit code and stable output lines for every
  listed result state
- `lease_conflict` must be treated as a handled command outcome, not as an
  uncaught exception

### 5. What "Same Source-Processing Path As Daemon Polling" Means

The phrase "same source-processing path as daemon polling" is fixed to mean
the following exact behavior.

Reused behavior:

- resolve one active source into the same `SourceState` projection the daemon
  polls
- load any pending child-discovery request for that canonical ID before the
  attempt
- call `process_source(...)` once with the same `fetch_children` boolean that
  the daemon would supply from the pending child-discovery request
- reuse the same per-source lifecycle lease via `process_source(...)`
- use the same `observe_missing_source(...)` path for upstream
  `remote_missing`
- use the same interval computation helpers from `sync/scheduler.py` for
  post-attempt polling progress

Intentionally reused follow-on behavior:

- child registration for discovered children in the same invocation through
  the existing sync-owned child-registration logic
- post-success sync-progress persistence through
  `sync/source_state.py` and `runtime/repository.py`
- handled lease-conflict semantics rather than lease override

Intentionally excluded daemon behavior:

- watcher event draining
- reconcile passes
- regen enqueueing and regen queue processing
- daemon-status ownership
- in-memory daemon scheduler mutation or wake-up signaling
- recursive syncing of discovered child sources

### 6. Child-Discovery Contract

Pending child-discovery requests are one-shot operational inputs and must not
turn into latent durable settings. `sync-source` therefore has an explicit
consumption contract.

Loading rule:

- if a pending child-discovery request exists for the target source,
  `sync-source` must load it before calling `process_source(...)`

Consumption rules:

- `changed`: consume the pending request in this invocation
- `unchanged`: consume the pending request in this invocation
- `remote_missing`: consume the pending request in this invocation
- `lease_conflict`: do not consume the pending request
- `not_found`: do not consume the pending request
- `error`: do not consume the pending request

Discovered-child rules:

- discovered children are registered during the same invocation
- registered children are not fetched recursively during that invocation
- no bulk sync expansion is allowed through child discovery
- child registration must use the existing source-registration seam so each
  child gets normal persisted polling state
- the command must not set child `next_check_utc` to "now" as a surrogate
  scheduler trigger

Daemon-running implication:

- if the daemon is already running, newly registered children are picked up by
  the daemon through its normal reload behavior
- this command does not try to mutate the daemon's in-memory scheduler to make
  child polling happen immediately

Explicit unchanged fast-path choice:

- if the shared pipeline returns `unchanged` without producing discovered
  children, the pending child-discovery request is still consumed
- this revision does not expand scope into "force full fetch even when the
  version check says unchanged" just to preserve child discovery

### 7. Remote-Missing Contract Outside The Daemon Loop

If the immediate sync attempt encounters upstream remote-missing behavior:

- the command must route that case through `observe_missing_source(...)`
- the source must move to durable `missing` state
- the active polling row for that source must be removed through the existing
  runtime owner path
- the command must return handled `remote_missing`
- no inline finalization occurs
- no daemon loop is required for the state transition to happen
- any pending child-discovery request for that source is cleared in the same
  invocation so the one-shot request does not linger on a missing source

### 8. Post-Attempt Polling-State Contract

`sync-source` is not implemented by editing `sync_polling` before the attempt.
It does, however, persist normal post-attempt sync progress after a real
attempt has occurred.

For `changed` and `unchanged`:

- persist `last_checked_utc`
- recompute the interval from `last_changed_utc` using
  `compute_interval(...)`
- persist `current_interval_secs`
- persist `interval_seconds`
- persist `next_check_utc` using `compute_next_check_utc(...)`

For unexpected `error` after the attempt has entered the shared processing
path:

- persist the same error-backoff semantics the daemon uses for a single-source
  failure
- do not invent a separate CLI-only retry policy

For `remote_missing`:

- remove the source from the active polling projection through the existing
  missing-source path rather than persisting a next poll time

For `lease_conflict` and `not_found`:

- do not mutate polling progress for that source

Live-daemon rule:

- a successful forced sync updates persisted runtime sync progress
- it does not attempt to rewrite or poke a live daemon's in-memory scheduler
- if the daemon races on stale in-memory timing, the source lease remains the
  correctness boundary

### 9. Architecture And Ownership Rules

This revision must stay inside current architecture seams.

Required dependency direction:

- `interfaces -> application`
- `application -> sync/runtime/...`

Required ownership boundaries:

- CLI handlers must not duplicate source-sync business logic
- CLI handlers must not import lower-level sync helpers directly to assemble
  their own workflow
- application code may orchestrate existing sync helpers, but portable-brain
  writes still cross through `brain/repository.py`
- runtime DB and lease writes still cross through `runtime/repository.py`

Implementation shape required by this plan:

- extract or add one shared single-source poll orchestration helper below the
  CLI layer so the daemon and `sync-source` can reuse the same post-attempt
  semantics where this plan says they should match
- do not implement the command by directly mutating `sync_polling` in the CLI
  handler or by waiting for the daemon to notice a due row later
- any persisted polling updates after the attempt must happen as normal
  post-sync bookkeeping, not as the triggering mechanism for the sync itself

## Workstreams

### Phase 0: Fix The Shared Contract

Required plan-to-code decisions:

- add the transport-neutral application result type for `sync-source`
- implement the exact selector contract from this plan
- explicitly encode the handled result states from this plan
- explicitly encode child-request consumption behavior from this plan

Primary modules:

- `src/brain_sync/application/sources.py`
- `src/brain_sync/sync/lifecycle.py`

### Phase 1: Shared Single-Source Sync Orchestration

Required behavior:

- create or extract one sync-owned helper that performs the same single-source
  attempt semantics the daemon uses where this plan says parity is required
- make that helper own:
  - pending child-request loading
  - the `process_source(...)` call
  - `remote_missing` translation through `observe_missing_source(...)`
  - child registration and request clearing
  - post-attempt polling-state persistence

Required exclusions:

- no regen enqueueing in this helper for this phase
- no watcher/reconcile behavior in this helper
- no daemon-specific in-memory scheduling behavior in this helper

Primary modules:

- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/runtime/repository.py`

### Phase 2: CLI Surface

Required behavior:

- add `sync-source` to the CLI parser
- accept one positional `source`
- route the command through the application layer only
- render the fixed output contract from this plan
- implement the exact exit-code mapping from this plan

Primary modules:

- `src/brain_sync/interfaces/cli/parser.py`
- `src/brain_sync/interfaces/cli/handlers.py`

### Phase 3: Documentation

If implementation lands, update user-facing and lifecycle docs for the new
command contract.

Required doc coverage:

- `docs/sync/README.md` for command behavior in the lifecycle matrix
- `README.md` for operator-facing usage if the command is exposed publicly

Required doc points:

- selector forms
- handled outcome states
- no inline regen in this phase
- remote-missing behavior
- daemon-independent operation

Explicit scope hold:

- do not add a new MCP tool in this phase
- do not update MCP docs as if the tool already exists

### Phase 4: Verification

Verification is required, not optional.

Unit and integration coverage must prove:

- exact canonical-ID selector resolution
- exact URL selector resolution
- `missing` manifest-only source returns handled `not_found`
- `changed` result persists post-attempt polling progress
- `unchanged` result persists post-attempt polling progress
- `lease_conflict` leaves child requests and polling progress untouched
- `remote_missing` marks the source missing and removes active polling state
- discovered children are registered but not recursively synced
- child requests are consumed or preserved exactly as specified in this plan
- unexpected `error` follows the explicit error-path contract from this plan

System coverage must prove:

- CLI by canonical ID returns the expected result text and exit code
- CLI by URL returns the same semantic result text and exit code
- CLI `changed` exits `0`
- CLI `unchanged` exits `0`
- CLI `lease_conflict` exits `1`
- CLI `not_found` exits `1`
- CLI `remote_missing` exits `1`
- CLI `error` exits `1`

Daemon-coexistence proof must prove:

- `sync-source` works with the daemon not running
- with a conflicting active source lease, `sync-source` returns handled
  `lease_conflict` without breaking daemon operation

The daemon-coexistence proof may be integration plus focused e2e, but approval
for implementation should assume at least one real daemon-running proof, not
just a mocked lease-holder assertion.

## Acceptance Criteria

The implementation is complete only when all of the following are true.

1. `brain-sync sync-source <source>` exists and accepts exactly one selector
   that is either an exact canonical ID or an exact registered source URL.
2. The CLI surface is the only new transport in this phase; no MCP tool is
   added, and the application contract is transport-neutral for future reuse.
3. Selector resolution is identical for current CLI behavior and any future
   MCP reuse: exact canonical ID first, then exact URL, with no path or bulk
   aliases.
4. The command operates only on the active polling set; a source that exists
   only in durable `missing` state returns handled `not_found`.
5. The command performs one direct source-processing attempt through the
   shared processing path and is not implemented by pre-emptive
   `sync_polling` mutation.
6. The command reuses the existing per-source lifecycle lease and never
   overrides an active lease.
7. `lease_conflict` is a handled command result with exit code `1`, stable
   output text, and no source mutation.
8. `changed` and `unchanged` are handled command results with exit code `0`,
   stable output text, and persisted post-attempt sync progress.
9. `remote_missing` is a handled command result with exit code `1`, stable
   output text, durable transition to `missing`, and removal from active
   polling state.
10. `error` is a handled command result with exit code `1`, stable output
    text, and the explicit error-path polling contract from this plan.
11. Pending child-discovery requests are loaded before the attempt and are
    consumed or preserved exactly as specified in this plan.
12. Discovered children are registered in the same invocation but are not
    recursively fetched or otherwise expanded into a bulk sync.
13. A successful forced sync updates persisted runtime sync progress, but the
    command does not try to mutate a live daemon's in-memory scheduler.
14. CLI handlers contain no duplicated source-sync business logic and call the
    application layer only.
15. Verification proves daemon-off behavior, daemon-on lease safety, and the
    full CLI outcome and exit-code contract without "where practical"
    exceptions.

## Reviewer / Approver Focus

Review should challenge the following points directly:

1. Does the plan now make the selector contract fully explicit for current CLI
   scope and future MCP reuse?
2. Is the CLI result and exit-code mapping specific enough to reject
   incompatible implementations?
3. Does the plan define exactly which daemon follow-on behaviors are reused
   and which are intentionally excluded?
4. Are child-discovery request loading, consumption, and child registration
   now explicit enough to avoid implementation guesswork?
5. Does the plan preserve current architecture seams and owner boundaries
   without pushing business logic into CLI handlers?
6. Does the plan stay narrow on scope by excluding inline regen, lease
   override, daemon lifecycle dependency, and hidden bulk-sync expansion?

## Next Step After Review

If review feedback finds remaining issues, the planner should create another
append-only plan revision.

If the plan is acceptable, the next required step is a separate approval
artifact under `docs/plans/README.md`. This file is not approval and does not
authorize implementation by itself.

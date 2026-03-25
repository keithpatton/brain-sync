# PLAN_sync-source-command: Direct Per-Source Forced Sync Command

## Status

Planning artifact only. This document defines the implementation plan for
adding a direct command that performs an immediate sync attempt for one
registered source without depending on the daemon's normal polling schedule.

This stage does **not** authorize implementation by itself. Work should follow
the normal `docs/plans/` review and approval trail before code changes begin.

## Objective

Add a first-class forced-sync command for one registered source that behaves
consistently whether the daemon is running or not.

The command should mean:

- attempt one immediate sync for the specified source now
- use the same source-processing path as daemon polling
- respect the existing per-source lifecycle lease
- update normal runtime and portable state through existing owners
- avoid mutating `sync_polling` merely to wait for the daemon to notice

This change should improve operator control for hot content without:

- requiring the daemon to be running
- stopping the daemon first
- introducing duplicate source-processing logic
- forcing mid-batch regen behavior

## Authoritative Inputs

Implementation must treat these documents as the primary constraints:

- `docs/RULES.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/README.md`
- `AGENTS.md`

Implementation must also align with the current owning seams for source
lifecycle, polling state, and explicit CLI workflows:

- `src/brain_sync/application/sources.py`
- `src/brain_sync/interfaces/cli/parser.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sync/source_state.py`
- `src/brain_sync/runtime/repository.py`

## Context

Today, brain-sync has:

- normal daemon polling through `brain-sync run`
- manual insight regeneration through `brain-sync regen <knowledge_path>`
- source registration, update, move, remove, reconcile, and finalize-missing
  commands

It does not currently expose a first-class command that means:

- "sync this one registered source now"

Operationally, an approximate workaround exists:

- alter runtime polling state so the daemon sees the source as immediately due

That workaround is inferior because:

- it behaves differently depending on whether the daemon is running
- it depends on daemon rescan timing and in-memory scheduler state
- it uses `sync_polling` as an indirect trigger rather than a direct source
  operation
- it does not present a clear CLI or MCP result contract

The existing codebase already contains most of the needed machinery:

- `process_source(...)` is the shared source-processing path
- source lifecycle leases already prevent double-processing of one source
- the daemon already treats lease conflict as a handled skip-and-retry outcome
- changed sources already enqueue regen after fetch when running inside the
  daemon loop

That means the missing piece is primarily command exposure and explicit
application-level orchestration, not a new sync engine.

## Scope

In scope for the implementation stage:

- add a direct application command for one immediate source sync
- add a CLI command such as `brain-sync sync-source <canonical_id-or-source>`
- make the command work whether the daemon is running or not
- return handled outcomes for:
  - changed
  - unchanged
  - lease conflict / already in progress
  - not found
  - remote missing
- update docs if the new command changes user-visible operation guidance

## Non-goals

- no daemon shutdown or restart requirement
- no direct mutation of `sync_polling` as the primary command mechanism
- no change to the normal polling scheduler or backoff policy
- no source-batch processing command in this phase
- no automatic mid-command regen execution in this phase
- no attempt to override an active source lifecycle lease
- no change to missing-source finalization semantics

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material issue.

### 1. The command is a direct source operation, not a scheduler hack

The implementation should not treat forced sync as:

- deleting a row from `sync_polling`
- setting `next_check_utc` to "now"
- waiting for the daemon to pick the source up later

Instead, the command should call the shared source-processing path directly and
let normal state persistence happen as part of that work.

### 2. Behavior should be daemon-independent

The command should be operationally meaningful in both cases:

- daemon not running
- daemon already running

The command should not require the daemon to be present to do useful work.

### 3. Per-source lifecycle lease remains the concurrency boundary

The implementation must reuse the existing source lifecycle lease.

That means:

- if the daemon is already syncing the same source, the command must return a
  handled `lease_conflict`-style result rather than overriding the daemon
- if the command already owns the source, the daemon should hit the existing
  skip-and-retry path if it reaches that same source
- contention should affect only that source, not fail the whole polling batch

### 4. Forced sync does not imply forced regen in this phase

This plan intentionally keeps source sync and insight regen separate.

The command may report the target knowledge path and whether content changed,
but it should not automatically run regen inline in this phase. That avoids a
larger design problem around churn, debounce, and partial waves of related
content.

### 5. Result semantics must be explicit and operator-friendly

The command should return one clear result state per invocation, such as:

- `changed`
- `unchanged`
- `lease_conflict`
- `not_found`
- `remote_missing`
- `error`

CLI and MCP surfaces should treat lease conflict as a handled operational
result, not a crash.

## Workstreams

### Phase 0: Command Contract And Outcome Shape

Goals:

- define the exact meaning of forced sync before wiring the CLI

Implementation requirements:

- choose the authoritative application-layer function signature
- define accepted source selectors:
  - canonical ID only
  - canonical ID or URL
- define the result payload fields, including:
  - canonical ID
  - source URL
  - target path if known
  - outcome state
  - changed / unchanged flag where meaningful
  - lease owner where available on conflict

Primary modules:

- `src/brain_sync/application/sources.py`
- `src/brain_sync/interfaces/cli/handlers.py`

### Phase 1: Application-Layer Forced Sync Facade

Goals:

- add one transport-neutral source-sync operation

Implementation requirements:

- add an application function that:
  - resolves the requested source
  - loads active source state
  - invokes the shared source-processing workflow once
  - converts lifecycle and fetch outcomes into a stable command result
- reuse the existing source lifecycle lease through `process_source(...)`
- ensure normal polling/runtime state updates still happen through existing
  owners rather than special-case direct DB edits

Primary modules:

- `src/brain_sync/application/sources.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sync/source_state.py`

### Phase 2: CLI Surface

Goals:

- expose the operation as a first-class user command

Implementation requirements:

- add a CLI command such as `brain-sync sync-source`
- define input rules and error messages
- log a clear operator-facing summary for each result state
- treat lease conflict as a non-crashing handled state unless the CLI contract
  intentionally wants non-zero exit for contention

Primary modules:

- `src/brain_sync/interfaces/cli/parser.py`
- `src/brain_sync/interfaces/cli/handlers.py`

### Phase 3: MCP And Interface Parity Review

Goals:

- decide whether the same operation should be exposed through MCP now or in a
  follow-up

Implementation requirements:

- review whether `brain_sync_sync_source` should be added in the same change
  set or explicitly deferred
- if deferred, document that choice rather than leaving it ambiguous

Primary modules:

- `src/brain_sync/interfaces/mcp/server.py`
- `docs/architecture/ARCHITECTURE.md`

### Phase 4: Verification Coverage

Goals:

- prove the command is safe under both daemon-off and daemon-on conditions

Implementation requirements:

- add tests covering:
  - successful unchanged forced sync
  - successful changed forced sync
  - source not found
  - remote missing
  - lease conflict when another owner already holds the source
  - daemon-safe behavior where lease conflict is handled rather than causing
    broader polling failure
- add CLI-level proof for result messaging and exit behavior where practical

Primary test areas:

- `tests/unit/`
- `tests/integration/`
- `tests/system/` only if needed for CLI proof

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. `brain-sync sync-source <source>` performs one immediate source sync attempt
   without requiring the daemon to be running.
2. The command uses the shared source-processing path rather than mutating
   `sync_polling` as an indirect trigger.
3. If the daemon or another caller already owns the same source lease, the
   command returns a handled lease-conflict result rather than overriding that
   work.
4. If the command owns the source first and the daemon reaches the same source
   during polling, the daemon continues to use its existing skip-and-retry
   behavior for that source only.
5. Normal runtime and portable state updates after forced sync remain owned by
   the existing source-processing workflow.
6. The command does not automatically run regen inline in this phase.
7. Tests prove consistent behavior with the daemon both running and not
   running.

## Risks And Mitigations

### Risk: The implementation duplicates daemon source-processing logic

Mitigation:

- require the application command to call the existing shared workflow
- keep fetch/materialization logic out of CLI handlers

### Risk: Forced sync is implemented by mutating scheduler state instead of syncing

Mitigation:

- make direct source processing a fixed design decision
- review for any write path that edits `sync_polling` merely to induce daemon
  action

### Risk: Lease conflict is treated as a hard failure with poor UX

Mitigation:

- define `lease_conflict` as a handled outcome in the command contract
- include current lease owner where available for diagnostics

### Risk: The team expects forced sync to also solve immediate summary freshness

Mitigation:

- keep regen explicitly out of scope for this phase
- make the command report changed state and target path clearly so operators
  can choose follow-up regen intentionally

## Reviewer / Approver Focus

Review should challenge these questions carefully:

1. Does the plan clearly require direct source processing rather than runtime
   scheduler mutation?
2. Is the daemon-on versus daemon-off behavior explicit enough to avoid
   implementer guesswork?
3. Does the concurrency model remain anchored on the existing per-source lease?
4. Is lease conflict defined as a handled operational result rather than an
   override or crash?
5. Is the decision to keep regen out of scope explicit and justified?

## Next Step After Review

If review feedback identifies issues, the planner should create a revised plan
artifact rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

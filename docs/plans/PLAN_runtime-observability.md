# PLAN_runtime-observability: Runtime Event Ledger and Support Visibility

## Status

Planning artifact only. This document defines the implementation plan for
adding machine-local operational observability to brain-sync so support agents
and maintainers can reconstruct what happened on a user's machine without
relying on application logs alone.

This stage does **not** change product behavior. It records the intended
architecture, workstreams, and acceptance gates for a later implementation
stage.

## Objective

Add a durable, machine-local runtime event ledger that answers the operational
questions users and support tooling actually need:

- was the daemon running
- what state did brain-sync believe it was in
- what meaningful observation or decision happened next
- what action did the system take
- what failed, if anything

The implementation must preserve brain-sync's existing architectural direction:

- filesystem remains the source of truth
- runtime state remains machine-local and rebuildable
- logs remain useful for humans but are no longer the only historical trail

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/architecture/ARCHITECTURE.md`
- `docs/brain-format/README.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/brain-format/VERSIONING.md`
- `docs/brain-format/COMPATIBILITY.md`
- `AGENTS.md`

Implementation must also align with the current code seams that already own
runtime state and support surfaces:

- `src/brain_sync/state.py`
- `src/brain_sync/token_tracking.py`
- `src/brain_sync/__main__.py`
- `src/brain_sync/cli/handlers.py`
- `src/brain_sync/mcp.py`

## Context

The current system already has the beginnings of an operational control plane:

- `~/.brain-sync/daemon.json` is the current daemon snapshot
- `~/.brain-sync/db/brain-sync.sqlite` stores rebuildable machine-local state
- `token_events` already records one class of telemetry in the runtime DB
- `brain-sync status` and `brain_sync_usage` provide limited support insight

What is missing is a structured history of semantic runtime events. Today,
operators can often see that something is wrong, but not the causal trail that
led there, especially across:

- daemon stopped vs running transitions
- offline filesystem changes later discovered by reconcile
- watcher batching and jitter windows
- queued vs started vs completed vs skipped regen behavior
- support diagnosis of "nothing happened" or "it happened much later"

## Scope

In scope for the implementation stage:

- a machine-local runtime event ledger stored in the runtime DB
- a small abstraction for recording and querying runtime events
- retention and pruning for event history
- richer daemon snapshot fields in `daemon.json`
- CLI surfaces for status/timeline/export
- MCP surfaces so agent tooling can inspect recent events cleanly
- targeted instrumentation in daemon, reconcile, watcher-adjacent decision
  points, regen, and key CLI entrypoints
- runtime-schema, documentation, and test updates required by the new table

## Non-goals

- no cloud telemetry backend in this change
- no external paid observability dependency
- no attempt to record every raw filesystem mutation
- no replacement of normal logging for developer debugging
- no portable Brain Format change; the event ledger remains runtime-only
- no general-purpose analytics or user-behavior product instrumentation

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material architectural problem.

### 1. Runtime-local storage

Operational history belongs in the machine-local runtime plane under
`~/.brain-sync/`, not in the portable brain root.

Rationale:

- support history is machine-specific
- users may choose to send it manually
- it must not become part of the portable brain contract
- it aligns with the current runtime DB and daemon status split

### 2. DB table is the source of truth for events

The event ledger should live in a new runtime DB table, tentatively
`runtime_events`, next to `token_events`.

JSONL export is still useful, but as an export format for support handoff, not
as the primary persistence model.

### 3. `daemon.json` remains the fast snapshot

`daemon.json` should continue to answer current-state questions quickly without
needing a DB query. It should be extended rather than replaced.

Expected additional fields:

- `session_id`
- `status`
- `started_at`
- `heartbeat_at`
- `mode`
- `last_event_type`
- `last_event_at`
- optional `last_error_type`
- optional `last_error_at`

### 4. Events represent semantic observations and decisions

The event stream should capture meaningful system observations, decisions,
actions, and failures, not raw low-level churn.

Good examples:

- `daemon.started`
- `daemon.crash_detected`
- `command.invoked`
- `knowledge.dirty_detected`
- `regen.queued`
- `regen.started`
- `regen.completed`
- `regen.skipped`
- `regen.failed`

Bad examples:

- `file_opened`
- `loop_iteration`
- `raw_fs_event_received`

### 5. Observability should usually be one client call

Call sites should not normally make separate "record event" and "write log"
calls for the same semantic transition.

Instead, implementation should provide one observability call that:

- persists the semantic event
- optionally renders a human log line
- keeps storage details behind a small abstraction boundary

Normal developer-oriented debug logging still remains available separately.

### 6. Configurable retention, default 7 days

Event retention should default to the last `7` days and be configurable in
`~/.brain-sync/config.json`.

Tentative config shape:

```json
{
  "observability": {
    "events": {
      "enabled": true,
      "retention_days": 7
    }
  }
}
```

### 7. Future export, not future redesign

The event API must be designed so a future exporter can ship the same event
objects to a cloud backend later without changing most call sites.

The implementation should therefore separate:

- event model
- storage backend
- query/export surfaces
- optional log rendering

## Planned Runtime Schema

The implementation should add a table with the following logical shape:

```text
runtime_events
  id INTEGER PRIMARY KEY AUTOINCREMENT
  created_utc TEXT NOT NULL
  event_type TEXT NOT NULL
  level TEXT NOT NULL
  origin TEXT NOT NULL
  component TEXT NOT NULL
  session_id TEXT NULL
  operation_id TEXT NULL
  command_id TEXT NULL
  resource_type TEXT NULL
  resource_id TEXT NULL
  reason_type TEXT NULL
  reason_id TEXT NULL
  success INTEGER NULL
  payload_json TEXT NULL
```

Required indexes:

- `created_utc`
- `(event_type, created_utc)`
- `(session_id, created_utc)`
- `(component, created_utc)`

Optional later index if query pressure warrants it:

- `(resource_type, resource_id, created_utc)`

Schema details may evolve during implementation, but the shape must preserve:

- stable core columns for common support queries
- flexible payload storage for incremental event growth
- append-only semantics at the event level

## Planned Client Interface

Implementation should add a small runtime observability module, for example:

- `src/brain_sync/observability.py`

The public interface should stay intentionally small. A concrete shape may vary,
but it should remain equivalent to:

```python
@dataclass(frozen=True)
class RuntimeEvent:
    event_type: str
    origin: str
    component: str
    level: str = "info"
    session_id: str | None = None
    operation_id: str | None = None
    command_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    reason_type: str | None = None
    reason_id: str | None = None
    success: bool | None = None
    payload: dict[str, object] | None = None


def emit_event(root: Path, event: RuntimeEvent, *, message: str | None = None) -> int | None: ...
def iter_events(root: Path, *, days: int = 7, limit: int = 100, **filters: object) -> list[dict]: ...
def prune_events(root: Path, retention_days: int) -> int: ...
def export_events_jsonl(root: Path, destination: Path, *, days: int = 7, **filters: object) -> int: ...
```

Design requirements for the interface:

- callers should not write SQL directly
- storage should be swappable later behind the module boundary
- event emission must never be allowed to break primary product behavior
- failures to write events should degrade to warning logs, similar to
  `token_tracking.py`

## Workstreams

The implementation should be organized into six phases.

### Phase 0: Schema and Versioning Baseline

Goals:

- define the runtime event table and config contract
- align schema/version docs before broad instrumentation

Implementation requirements:

- add `runtime_events` DDL and indexes
- bump runtime DB schema version because the DB shape changes
- update the version and compatibility docs to reflect the new runtime schema
- document event retention config and runtime ownership

Expected documentation updates:

- `docs/brain-format/VERSIONING.md`
- `docs/brain-format/COMPATIBILITY.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`

Primary modules:

- `src/brain_sync/state.py`
- `src/brain_sync/config.py`
- `src/brain_sync/layout.py`

### Phase 1: Observability Abstraction

Goals:

- create the shared runtime event API
- keep event storage concerns out of daemon/CLI business logic

Implementation requirements:

- add the `RuntimeEvent` model and event-writer/query helpers
- make event recording non-fatal
- add retention loading and pruning helpers similar to token telemetry
- support optional log rendering from the same semantic event call

Primary modules:

- `src/brain_sync/observability.py`
- `src/brain_sync/state.py`
- `src/brain_sync/logging_config.py` if needed

### Phase 2: Snapshot and Daemon Lifecycle Instrumentation

Goals:

- make daemon state externally inspectable
- produce a reliable session-scoped lifecycle trail

Implementation requirements:

- extend `daemon.json` fields
- generate a daemon `session_id` at startup
- detect stale prior daemon status on startup and emit crash/stale-session
  events when appropriate
- update daemon heartbeat and last-event metadata during runtime
- emit lifecycle events for:
  - startup
  - ready
  - stop
  - crash detection
  - reconcile begin/end

Primary modules:

- `src/brain_sync/__main__.py`
- `src/brain_sync/state.py`
- `src/brain_sync/observability.py`

### Phase 3: Semantic Instrumentation of Workflows

Goals:

- capture the decision/action trail users need for support
- keep event volume low and meaning high

Implementation requirements:

- instrument CLI command entrypoints with `command.invoked` and completion or
  failure events
- instrument reconcile and watcher-driven change handling at the semantic
  boundary:
  - offline change detected
  - dirty area detected
  - regen queued
  - regen skipped unchanged
- instrument regen lifecycle:
  - start
  - complete
  - fail
- instrument source sync lifecycle only at meaningful boundaries

Special rule:

Watcher-related events must describe observed state or decisions, not claim a
precise user mutation sequence that the system did not directly witness.

Primary modules:

- `src/brain_sync/__main__.py`
- `src/brain_sync/reconcile.py`
- `src/brain_sync/regen.py`
- `src/brain_sync/regen_queue.py`
- `src/brain_sync/cli/handlers.py`

### Phase 4: Support Surfaces

Goals:

- expose the event history cleanly to users and agents
- keep current support actions local and cheap

Implementation requirements:

- extend `brain-sync status` to show richer daemon snapshot data
- add `brain-sync timeline`
- add JSON output mode for agent-friendly parsing
- add a support export command or subcommand that writes filtered JSONL for
  manual sharing
- add corresponding MCP tool(s) for recent runtime events

Primary modules:

- `src/brain_sync/cli/__init__.py`
- `src/brain_sync/cli/handlers.py`
- `src/brain_sync/mcp.py`

### Phase 5: Tests and Closeout

Goals:

- prove the runtime event ledger is reliable enough for support usage
- keep the feature aligned with current repository conventions

Implementation requirements:

- unit tests for event insertion, querying, pruning, and non-fatal failure
  behavior
- unit tests for `daemon.json` snapshot enrichment
- integration tests for daemon lifecycle and offline-reconcile event capture
- system tests for `status`, `timeline`, and export CLI behavior
- MCP tests for agent-facing event access

Primary test areas:

- `tests/unit/`
- `tests/integration/`
- `tests/system/`
- `tests/mcp/`

## Documentation and Versioning Obligations

This work changes the runtime DB shape but not the portable brain contract.

Therefore:

- Brain Format remains `1.0`
- the runtime DB schema version must be bumped from `v23` to the next version
  unless concurrent approved work supersedes that numbering
- the compatibility row must be updated in lockstep with that runtime schema
  change

If implementation lands in a release that also changes the app version, the
compatibility statement must be updated consistently across docs and code.

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. A support agent can determine from local artifacts whether the daemon was
   running, stale, or stopped at the time of a reported issue.
2. A recent semantic trail can be queried without reading raw application logs.
3. Offline changes later discovered by reconcile produce understandable events.
4. Watcher jitter does not inflate the ledger with low-value raw filesystem
   churn events.
5. Event recording failures do not break core sync, regen, or CLI behavior.
6. Event retention is configurable and defaults to `7` days.
7. A user can export recent events to a shareable JSONL artifact.
8. MCP/agent tooling can retrieve recent events in structured form.
9. The runtime schema/version/docs/tests are aligned with the implemented
   storage shape.

## Risks and Mitigations

### Risk: Event spam reduces usefulness

Mitigation:

- record semantic events only
- prefer area-level decisions over raw file-level churn
- batch watcher consequences rather than individual low-level notifications

### Risk: Instrumentation pollutes business logic

Mitigation:

- centralize event recording behind one module boundary
- prefer helper functions/context managers for start-complete-fail flows

### Risk: Event writing creates hot-path contention

Mitigation:

- keep rows compact
- use the existing local SQLite runtime model
- treat asynchronous/background draining as a later optimization only if needed

### Risk: Sensitive data leaks into support bundles

Mitigation:

- keep payloads minimal
- avoid raw prompt text, credentials, and unnecessary absolute paths
- prefer knowledge-relative identifiers and canonical IDs

## Reviewer Focus

The reviewer should concentrate on these questions:

1. Is DB-backed runtime history the right source of truth, or is JSONL-first
   materially better for this repo?
2. Is the proposed event schema too wide, too narrow, or incorrectly split
   between fixed columns and `payload_json`?
3. Does the planned client API keep future storage/export changes isolated
   enough?
4. Are the proposed CLI and MCP surfaces the right minimum for support and
   agent workflows?
5. Are the versioning and documentation obligations complete, especially around
   the runtime schema bump?

## Next Step After Review

If review feedback identifies issues, the planner should create a revised plan
artifact rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

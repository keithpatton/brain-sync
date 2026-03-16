# Approval

Approved: 2026-03-16T15-57-33
Approved by: codex-gpt-5

Notes:
- Revision 3 supersedes the earlier approval of revision 2 as the latest approved implementation basis.
- The added reconciliation clarification correctly preserves the current support-meaningful outputs from `src/brain_sync/reconcile.py`.
- During execution, keep the docs explicit that Brain Format versions the portable brain contract under the brain root, while runtime DB and `daemon.json` changes are runtime-only schema changes.

---

# plan_runtime-observability_3 - Runtime Event Ledger and Support Visibility (Final Revised)

Revision incorporating the advisory note from
`docs/plans/plan_runtime-observability_2_review_1_2026-03-16.md`.

This revision carries forward the approved direction from
`docs/plans/plan_runtime-observability_2_2026-03-16.md` and makes one final
planner-level clarification: reconciliation events must preserve the three
current semantic outputs already present in `src/brain_sync/reconcile.py`.

---

## Status

Planning artifact only. This document is the current plan revision for runtime
observability. It preserves the revision 2 event-contract work and adds one
explicit rule for reconciliation semantics so implementation does not collapse
distinct offline-recovery outcomes into a generic summary event.

This stage does **not** change product behavior. It records the implementation
requirements and acceptance gates for a later execution stage.

## Objective

Add a durable, machine-local runtime event ledger that lets support agents,
users, and future AI tooling reconstruct the important trail of events on a
user's machine without relying on application logs alone.

The implementation must produce:

- a runtime-local event history stored in the machine-local SQLite DB
- an explicit event contract using brain-sync vocabulary
- a richer daemon snapshot for current-state inspection
- CLI and MCP visibility surfaces for recent activity and export
- reconciliation events that preserve the current semantic distinctions already
  returned by the codebase

The implementation must preserve the current architectural direction:

- filesystem remains the source of truth
- runtime DB remains machine-local and rebuildable
- the event ledger is runtime history, not portable brain state
- logs remain developer-oriented narrative, not the sole support artifact

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/brain-format/README.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/brain-format/GLOSSARY.md`
- `docs/brain-format/VERSIONING.md`
- `docs/brain-format/COMPATIBILITY.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`

It must also align with the current runtime/state seams:

- `src/brain_sync/state.py`
- `src/brain_sync/token_tracking.py`
- `src/brain_sync/__main__.py`
- `src/brain_sync/reconcile.py`
- `src/brain_sync/regen.py`
- `src/brain_sync/regen_queue.py`
- `src/brain_sync/cli/handlers.py`
- `src/brain_sync/mcp.py`

## Scope

In scope for the implementation stage:

- a runtime-local event ledger in the runtime DB
- a dedicated event contract document before broad instrumentation
- a small abstraction for emitting, querying, pruning, and exporting events
- richer `daemon.json` fields and explicit stale-daemon semantics
- CLI and MCP surfaces for current status, timeline, and support export
- semantic instrumentation across daemon, CLI, MCP, reconcile, sync, and
  regeneration flows
- runtime schema, glossary, architecture, compatibility, and test updates

## Non-goals

- no cloud telemetry backend in this change
- no external paid observability dependency
- no replacement of ordinary debug logging
- no raw watcher-event exhaust stream
- no portable Brain Format change
- no attempt to capture every user filesystem mutation in exact sequence

## Documentation Authority Split

### `docs/architecture/OBSERVABILITY.md` (new)

Authoritative home for:

- event families and approved event names
- event placement rules
- allowed nouns for resources and reasons
- stale-daemon semantics
- guidance for future event additions

### `docs/brain-format/SCHEMAS.md`

Authoritative home for normative runtime schema shape:

- `runtime_events` DB table
- indexes that are part of the supported runtime schema
- `daemon.json` snapshot shape if the project chooses to standardize it

### `docs/brain-format/GLOSSARY.md`

Authoritative home for the shared vocabulary reused by the event contract.

### `docs/brain-format/VERSIONING.md` and `COMPATIBILITY.md`

Must be updated because the runtime DB schema shape changes.

### `README.md`

Should expose only user-facing operational capabilities such as richer
`status`, `timeline`, and support export.

## Fixed Design Decisions

### 1. Runtime-local storage

Operational history belongs in the machine-local runtime plane under
`~/.brain-sync/`, not in the portable brain root.

### 2. DB-backed event ledger

The event ledger source of truth is a new runtime DB table, tentatively
`runtime_events`, next to `token_events`.

JSONL is an export format for support handoff, not the primary persistence
model.

### 3. `daemon.json` remains the fast snapshot

`daemon.json` remains the current-state snapshot that can be read without a DB
query.

### 4. Events are semantic, not raw mechanics

Events must represent semantic observations, decisions, state transitions,
externally visible actions, and failures. They must not represent raw watcher
churn, loop ticks, or low-level IO noise.

### 5. One observability call at semantic points

Call sites should not usually have to issue both a log call and an event call
for the same semantic transition. The observability API should support one call
that persists the event and may optionally render a log line.

### 6. Configurable retention, default 7 days

Runtime event retention defaults to `7` days and is configurable in
`~/.brain-sync/config.json`.

### 7. MCP is first-class

MCP tool invocations are first-class interface actions and must be represented
in the event model alongside CLI and daemon-originated actions.

### 8. Reconciliation distinctions must be preserved

The current reconciliation code already returns three support-meaningful
semantic outputs:

- orphan state cleaned
- tracked knowledge-area content changed
- previously untracked knowledge area enqueued

Implementation must preserve these distinctions explicitly in the event
contract and emitted data. They must not be collapsed into a single generic
`reconciliation.completed` summary without a way to tell them apart.

## Required Event Contract

Before broad instrumentation starts, implementation must add an authoritative
event contract document at:

- `docs/architecture/OBSERVABILITY.md`

Broad instrumentation must not proceed until that document exists and defines:

1. event families
2. approved event names within each family
3. required and optional fields per family
4. approved `origin` values
5. approved `resource_type` and `reason_type` vocabulary
6. canonical identifier rules
7. event placement rules
8. examples of good and bad event additions

### Approved initial event families

- `daemon`
- `interface`
- `reconciliation`
- `regeneration`
- `sync`

### Approved initial event names

`daemon`

- `daemon.started`
- `daemon.ready`
- `daemon.stopped`
- `daemon.crash_detected`
- `daemon.stale_detected`

`interface`

- `interface.invoked`
- `interface.completed`
- `interface.failed`

`reconciliation`

- `reconciliation.started`
- `reconciliation.completed`
- `reconciliation.orphan_state_cleaned`
- `reconciliation.knowledge_area_change_detected`
- `reconciliation.knowledge_area_enqueued`

`regeneration`

- `regeneration.queued`
- `regeneration.started`
- `regeneration.completed`
- `regeneration.skipped_unchanged`
- `regeneration.skipped_rename_only`
- `regeneration.skipped_similarity`
- `regeneration.failed`

`sync`

- `sync.started`
- `sync.completed`
- `sync.failed`

These names must not be replaced ad hoc by synonyms in code.

### Event placement rules

Emit when:

- the system makes a semantic observation
- the system makes a semantic decision
- runtime state changes in a support-meaningful way
- an external interface action starts, completes, or fails
- a long-running operation starts, completes, skips, or fails

Do not emit when:

- the system only receives raw watcher churn
- the system is in internal polling or sleep mechanics
- the event would duplicate a previous event without a new semantic fact
- the information is better represented as snapshot state

### Canonical identity mapping

| Resource kind | `resource_type` | Identifier |
|---|---|---|
| Knowledge area | `knowledge_area` | `knowledge_path` relative to `knowledge/`; `""` for root area |
| Synced source | `synced_source` | `canonical_id` |
| Daemon session | `daemon_session` | daemon `session_id` |

The contract must also define:

- daemon session identifier -> `session_id`
- long-running operation identifier -> `operation_id`
- interface invocation identifier -> `command_id`

`owner_id` remains an internal regen coordination identifier and should not be
the primary support-facing event identity unless a later revision explicitly
promotes it.

### Approved initial `origin` vocabulary

- `daemon`
- `cli`
- `mcp`

### Approved initial `reason_type` vocabulary

- `watcher_batch`
- `reconciliation`
- `cli_command`
- `mcp_tool`
- `source_sync`

### Payload discipline

The contract must require:

- stable identifiers go in fixed columns, not only in payload
- payloads carry bounded metadata such as counts, durations, booleans, and
  enum-like details
- payloads do not carry credentials, prompt bodies, or unnecessary absolute
  machine paths

### Reconciliation-specific contract rule

The reconciliation family must preserve the current semantic outputs from
`TreeReconcileResult` in `src/brain_sync/reconcile.py`.

At minimum, support tooling must be able to distinguish:

- orphan state cleaned
- tracked knowledge-area change detected
- previously untracked knowledge area enqueued

This may be represented by dedicated events, by documented payload fields on
approved reconciliation events, or both. The implementation must not lose this
distinction.

If `reconciliation.completed` carries aggregate payload, it should include
documented counts such as:

- `orphans_cleaned_count`
- `knowledge_areas_changed_count`
- `knowledge_areas_enqueued_count`

## Planned Runtime Schema

The implementation should add a `runtime_events` table with this logical shape:

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

Optional later index if needed:

- `(resource_type, resource_id, created_utc)`

The implementation must update `docs/brain-format/SCHEMAS.md` with the final
normative shape and keep the code/schema docs aligned.

## Daemon Snapshot and Stale Model

`daemon.json` should include at least:

- `pid`
- `session_id`
- `status`
- `started_at`
- `heartbeat_at`
- `mode`
- `last_event_type`
- `last_event_at`
- optional `last_error_type`
- optional `last_error_at`

Heartbeat cadence:

- update `heartbeat_at` at least every `30` seconds while the main loop is
  healthy
- also update on startup, ready, and clean shutdown transitions

Stale threshold:

- treat heartbeat age greater than `90` seconds as stale in the initial
  implementation

Reader-facing model:

- `running`: snapshot says `starting` or `ready`, PID is live, heartbeat fresh
- `stale`: snapshot says `starting` or `ready`, but PID is missing or heartbeat
  is older than the stale threshold
- `stopped`: snapshot says `stopped`, or no active session is claimed

Startup recovery behavior:

1. read the previous snapshot if present
2. if it claims an active session and is stale, emit:
   - `daemon.stale_detected`
   - `daemon.crash_detected` when the prior PID is no longer live
3. create a new daemon `session_id`
4. write the new `starting` snapshot

The daemon should not emit periodic heartbeat events. Heartbeat is snapshot
state, not support-worthy event history on its own.

## Planned Client Interface

Implementation should add a dedicated runtime observability module, for example:

- `src/brain_sync/observability.py`

Equivalent public surface:

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

Design requirements:

- callers must not write SQL directly
- event emission must never break primary product behavior
- event-write failures degrade to warning logs
- future storage/export changes stay behind this module boundary
- the same module serves CLI, daemon, and MCP callers

## Workstreams

### Phase 0: Event Contract and Documentation Baseline

- create `docs/architecture/OBSERVABILITY.md`
- define event families, names, placement rules, and vocabulary there
- update `docs/brain-format/GLOSSARY.md` with any missing observability terms
- update `docs/brain-format/SCHEMAS.md` for:
  - `runtime_events`
  - `daemon.json` snapshot shape if standardized as runtime schema
- update `docs/brain-format/VERSIONING.md`
- update `docs/brain-format/COMPATIBILITY.md`
- update `docs/brain-format/README.md` if the spec index needs to mention the
  runtime-schema additions

### Phase 1: Runtime Schema and Observability Abstraction

- add `runtime_events` DDL and indexes
- bump the runtime DB schema version
- add the observability module and event model
- add retention config loading and pruning helpers
- make event recording non-fatal

Primary modules:

- `src/brain_sync/state.py`
- `src/brain_sync/config.py`
- `src/brain_sync/layout.py`
- `src/brain_sync/observability.py`

### Phase 2: Daemon Snapshot and Session Lifecycle

- extend `daemon.json`
- add daemon `session_id`
- implement heartbeat updates
- implement stale-session detection on startup
- emit the approved daemon lifecycle events

Primary modules:

- `src/brain_sync/__main__.py`
- `src/brain_sync/state.py`
- `src/brain_sync/observability.py`

### Phase 3: Interface-Origin Instrumentation

- instrument CLI entrypoints with `origin="cli"`
- instrument MCP tool entrypoints with `origin="mcp"`
- emit `interface.invoked`, `interface.completed`, and `interface.failed`
- include command or tool name in documented fields or payload
- include relevant knowledge-area or synced-source identifiers when applicable

Primary modules:

- `src/brain_sync/cli/handlers.py`
- `src/brain_sync/mcp.py`

### Phase 4: Reconciliation and Regeneration Instrumentation

- instrument reconciliation start and completion
- preserve the three current reconciliation outputs explicitly:
  - orphan state cleaned
  - tracked knowledge-area change detected
  - previously untracked knowledge area enqueued
- instrument regeneration queue decisions and outcomes using approved event
  names only
- ensure rename-only and unchanged cases are represented consistently

Special rule:

Watcher-related code must emit events only after semantic classification, not
for raw filesystem notifications.

Primary modules:

- `src/brain_sync/reconcile.py`
- `src/brain_sync/__main__.py`
- `src/brain_sync/regen_queue.py`
- `src/brain_sync/regen.py`

### Phase 5: Sync Instrumentation

- emit `sync.started`, `sync.completed`, and `sync.failed`
- map synced-source identity via `resource_type="synced_source"` and
  `resource_id=<canonical_id>`
- avoid event spam for internal retries unless they become a support-meaningful
  terminal outcome

Primary modules:

- `src/brain_sync/__main__.py`
- `src/brain_sync/pipeline.py`

### Phase 6: Support Surfaces and Tests

- extend `brain-sync status`
- add `brain-sync timeline`
- add JSON output mode for agent-safe parsing
- add support export to JSONL
- add MCP tool(s) for recent events
- add unit, integration, system, and MCP tests for:
  - event insertion/query/pruning
  - daemon stale detection
  - CLI and MCP interface coverage
  - reconciliation and regeneration event trails

## Versioning Obligations

This work changes runtime schema, not portable brain schema.

Therefore:

- Brain Format remains `1.0`
- the runtime DB schema version must be bumped from `v23` to the next version
  unless superseded by concurrent approved work
- compatibility docs and code constants must be updated in lockstep

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. The runtime DB contains a documented, queryable `runtime_events` table.
2. An authoritative event contract exists at
   `docs/architecture/OBSERVABILITY.md`.
3. The runtime schema and terminology updates are reflected in
   `SCHEMAS.md`, `GLOSSARY.md`, `VERSIONING.md`, and `COMPATIBILITY.md`.
4. A support agent can determine whether the daemon is running, stale, or
   stopped using the documented stale-daemon model.
5. CLI-origin and MCP-origin interface actions both appear in the event
   history with consistent origin semantics.
6. Knowledge-area and synced-source events use documented canonical
   identifiers, not ad hoc payload conventions.
7. Reconciliation events preserve the distinction between orphan cleanup,
   tracked-area change detection, and newly enqueued untracked areas.
8. Watcher jitter does not flood the ledger with raw filesystem-noise events.
9. Event recording failures do not break primary product behavior.
10. A user can export recent events to JSONL for manual sharing.

## Reviewer / Approver Focus

The reviewer or approver should mainly confirm that the reconciliation
clarification now makes the plan safe to execute without losing one of the
current support-relevant reconcile outcomes.

## Next Step

If no further changes are needed, the next required action is a separate
approval artifact under the `docs/plans/` workflow. This file is not approval
and does not authorize implementation by itself.

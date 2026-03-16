# plan_runtime-observability Review 1 - Strong Direction, Needs an Event Contract

**Reviewer:** Codex GPT-5
**Date:** 2026-03-16
**Reviewed document:** `docs/plans/PLAN_runtime-observability.md`
**Reviewed against:**
- `docs/plans/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/brain-format/README.md`
- `docs/brain-format/GLOSSARY.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/brain-format/VERSIONING.md`
- `docs/brain-format/COMPATIBILITY.md`
- current runtime/state code in `src/brain_sync/`

**Purpose:** Review the runtime observability plan against the current
brain-sync implementation and the repository planning workflow, with added
focus on whether future agents will have a durable, brain-sync-native way to
decide how and when to add new events as the codebase grows.

---

## Verdict

The plan is headed in the right direction and the core architectural choice is
sound: runtime-local, DB-backed semantic events fit the current split between
portable brain state and machine-local runtime state.

It is **not ready for approval as written**.

The main gap is not the storage model. The main gap is that the plan treats
event naming and placement as implementation detail when this repo now needs an
authoritative event contract:

- what event families exist
- which brain-sync terms they must use
- what identifiers are valid for areas, sources, and runtime sessions
- when a semantic boundary deserves an event and when it does not

Without that, the first implementation may work, but future agents will still
add events inconsistently and gradually turn the ledger into another log sink.

---

## Critical Issues

### C1. The plan does not define an authoritative event taxonomy or event-placement rulebook

`PLAN_runtime-observability.md` correctly says events should be semantic rather
than low-level, but it stops at examples such as `daemon.started`,
`knowledge.dirty_detected`, and `regen.failed`. That is not enough guidance for
future agents.

This is especially risky in the current codebase because there are already
several distinct semantic boundaries with different vocabulary:

- daemon lifecycle in `src/brain_sync/__main__.py`
- knowledge-tree reconciliation outputs in `src/brain_sync/reconcile.py`
  (`orphans_cleaned`, `content_changed`, `enqueued_paths`)
- regen queue decisions in `src/brain_sync/regen_queue.py`
  (debounce, cooldown, rate limit, retries exhausted)
- regen outcomes in `src/brain_sync/regen.py`
  (`regenerated`, `skipped_unchanged`, `skipped_rename`, `skipped_similarity`,
  failure)

The glossary already gives the repo a shared language: `knowledge area`,
`reconciliation`, `regeneration`, `daemon`, `watcher`, `synced source`,
`canonical ID`, `generated meaning`, and `runtime state`. The plan should use
that language to define events, not rely on ad hoc dotted names alone.

If this is left implicit, one agent will emit `knowledge.dirty_detected`,
another will choose `area.changed`, another will record a `path`, another a
`knowledge_path`, and support queries will stop being reliable.

**Recommendation:** Revise the plan to require one authoritative event contract
document before broad instrumentation starts. That contract should define at
least:

- the event families and approved event names
- required and optional fields per family
- the allowed brain-sync nouns for `resource_type`, `reason_type`, and payload
  keys
- the canonical identifiers to use:
  `knowledge_path`, `canonical_id`, `session_id`, and command/tool identifiers
- explicit placement rules:
  emit at semantic observations, decisions, state transitions, and externally
  visible actions; do not emit raw watcher churn or loop mechanics

This can live in a dedicated architecture doc or a supporting input, but the
plan should make it a required artifact, not an implementation afterthought.

### C2. The documentation obligations are incomplete for a runtime schema change

Phase 0 lists documentation updates for:

- `docs/brain-format/VERSIONING.md`
- `docs/brain-format/COMPATIBILITY.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`

That is incomplete for this repository's own authority model.

The plan itself names `docs/brain-format/SCHEMAS.md` as an authoritative input.
The Brain Format spec index says `SCHEMAS.md` is where schema-defined runtime DB
shape belongs. Adding a new `runtime_events` table is therefore not just a
versioning change; it is a normative runtime-schema change.

There is also a terminology gap. If events are going to be "well defined using
the language of brain-sync", the glossary needs to carry the event-plane terms
that other documents and future agents will reuse.

As written, the plan risks producing code plus version bumps without a single
authoritative home for:

- the runtime event table shape
- any documented `daemon.json` schema expansion
- the core event terminology

**Recommendation:** Expand the required documentation updates to include:

- `docs/brain-format/SCHEMAS.md` for the `runtime_events` table and any
  normative runtime snapshot shape that the repo wants to standardize
- `docs/brain-format/GLOSSARY.md` for observability/event terms that future
  agents should reuse
- `docs/brain-format/README.md` if needed, to keep the spec index honest about
  where runtime schema is defined

If the project does **not** want runtime snapshot shape in `SCHEMAS.md`, the
plan should say so explicitly and update the spec/docs split accordingly.

---

## Significant Issues

### S1. The plan instruments CLI entrypoints but leaves MCP and agent-originated actions as a blind spot

Phase 3 explicitly calls for `command.invoked` plus completion/failure events
for CLI entrypoints, but it does not say the same for MCP tool invocations.

That is a problem in this repo because MCP is not ancillary. It is a first-class
interface in `src/brain_sync/mcp.py`, and it can trigger many of the same
meaningful actions that support will care about:

- add / remove / move / update source
- reconcile
- regen
- doctor
- usage queries

If the event ledger records CLI actions but not MCP actions, a support agent
will still miss a large class of "what action did the system take next?" cases,
especially in agent-driven workflows.

The schema already anticipates `origin`, but the workstreams do not yet use that
to define coverage.

**Recommendation:** Revise Phase 3 so interface-origin events cover at least:

- CLI command invocations with `origin="cli"`
- MCP tool invocations with `origin="mcp"`
- daemon and background workflow events with `origin="daemon"` or equivalent

The plan should also require consistent interface fields, for example command or
tool name, success/failure, and relevant resource identifiers.

### S2. "Stale daemon" detection is an acceptance criterion, but the plan does not define the stale model

The acceptance criteria require a support agent to determine whether the daemon
was running, stale, or stopped. The plan adds `heartbeat_at` and mentions crash
detection, but it does not define:

- how often heartbeat updates happen
- what stale threshold means
- whether staleness is inferred from heartbeat age, PID liveness, startup
  recovery, or some combination
- how this behaves across shutdown, crash, and startup repair

This matters because the current implementation only writes a minimal snapshot in
`write_daemon_status()` and does not have a periodic heartbeat path. Without an
explicit stale model, different implementers may choose different semantics and
the resulting support behavior will drift.

**Recommendation:** Add a plan requirement that defines:

- heartbeat write cadence
- stale threshold and where it is configured, if configurable
- startup reconciliation logic for stale prior sessions
- the exact conditions under which `daemon.json` and the event ledger should say
  `ready`, `stale`, `stopped`, or crash-related states

---

## Moderate Issues

### M1. The plan should explicitly map event resources to existing brain-sync identities

The proposed schema uses generic fields like `resource_type`, `resource_id`,
`reason_type`, and `reason_id`, which is a good shape. What is missing is the
mapping to existing repo identities.

The codebase already has stable identifiers and durable nouns:

- `knowledge_path` for knowledge areas
- `canonical_id` for synced sources
- `session_id` for regen/token telemetry sessions
- `owner_id` for regen ownership

Without a mapping rule, payloads will drift toward mixed path and identifier
conventions.

**Recommendation:** The revised plan should define the expected mapping for the
first event families, for example:

- knowledge-area events -> `resource_type="knowledge_area"`, `resource_id=<knowledge_path>`
- synced-source events -> `resource_type="synced_source"`, `resource_id=<canonical_id>`
- daemon session events -> `session_id=<daemon session id>`

---

## What The Plan Gets Right

1. Keeping the event ledger in the machine-local runtime plane matches the
   current state-authority model and should not become part of the portable
   brain contract.
2. A DB-backed append-only ledger is a better fit than JSONL-first for the
   current repo because support queries, retention, and MCP access all want
   structured local reads.
3. The insistence on semantic events rather than raw watcher churn is exactly
   right for the daemon + reconcile + regen architecture.
4. Treating event emission as non-fatal, similar to `token_tracking.py`, fits
   the existing runtime telemetry philosophy.
5. Extending `daemon.json` as a fast snapshot rather than replacing it is a good
   match for the current `write_daemon_status()` / `read_daemon_status()` seam.

---

## Recommended Plan Revision

Before approval, revise `PLAN_runtime-observability.md` so it:

1. Adds an explicit event contract work item that defines event names, fields,
   vocabulary, and placement rules in brain-sync terms.
2. Expands documentation obligations to include the authoritative schema and
   glossary homes for runtime events.
3. Treats MCP tool invocations as first-class event origins alongside CLI and
   daemon actions.
4. Defines the stale-daemon model concretely enough that `status`, timeline,
   export, and support tooling will all agree.
5. Maps generic resource fields onto existing brain-sync identifiers such as
   `knowledge_path` and `canonical_id`.

---

## Approval Criteria For The Next Revision

I would approve the next revision if it:

- makes future event additions governable rather than ad hoc
- gives events a clear brain-sync vocabulary and identity model
- updates the doc/spec obligations so the runtime event schema has an
  authoritative home
- closes the MCP-origin observability gap
- defines stale-daemon semantics concretely

---

## Conclusion

The storage direction is strong. The missing piece is the contract around the
events themselves.

brain-sync now needs more than "add a runtime_events table." It needs a
documented event language for the daemon, reconciliation, watcher decisions,
regeneration, synced sources, and interface actions so future agents can extend
the ledger without degrading it.

Approval is **not** recommended for the current plan revision. The planner
should create a revised plan artifact rather than editing
`PLAN_runtime-observability.md` in place.

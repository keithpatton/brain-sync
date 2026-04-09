# Approval

Approved: 2026-04-09T08-38-41
Approved by: codex-gpt-5

Notes:

- the shared bootstrap-capable MCP launcher is a credible no-root solution for this repo because current MCP lifespan startup hard-resolves the active root and the wrappers must stay thin
- `attach-root` now matches the current single-brain runtime model by making the chosen root active at `config.json["brains"][0]` while preserving other registered roots only as compatibility baggage
- the coexistence and daemon-adoption contract is now concrete enough for terminal foreground use plus Claude Code, Claude Desktop, and Codex wrappers sharing one runtime config directory
- the v1 product boundary is acceptably tight: healthy terminal foreground daemons may be adopted for status and normal use, but remote stop/restart remains out of scope until a real cross-process control channel exists
- the first approved slice now clearly forbids portable-brain contract changes, runtime DB migration, and provider-config MCP parity
- documentation and proof obligations now correctly include `docs/sync/README.md` and explicit `tests/e2e/` coverage for cross-process daemon control and adoption

---

# plan_plugin-delivery_2_2026-04-09: Plugin Delivery And Daemon-Aware Productization

## Status

Approved plan artifact. This file copies
`docs/plans/plan_plugin-delivery_2_2026-04-09.md` as the authoritative
implementation handoff.

This revision resolves the first review's main concerns by making the
bootstrap path, attach-root behavior, daemon adoption rules, and first-slice
boundaries explicit.

Implementation may proceed from this approved artifact under the `docs/plans/`
workflow.

## Objective

Deliver a local-first, plugin-friendly `brain-sync` product that:

- does not require users to keep a checked-out source repository
- does not require users to expose a visible `python -m ...` MCP command
- allows plugin-driven use without a manually managed terminal daemon
- preserves the current portable brain contract and the existing
  `brain-sync run` daemon semantics as much as possible

The first approved slice should prove one shared installed runtime and one
shared daemon per runtime config directory before taking on broader
configuration parity.

## Authoritative Inputs

Implementation must treat these documents as the primary constraints:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`

Implementation must also align with the current code seams that already own
active-root resolution, initialization, runtime config, daemon status, and
daemon execution:

- `src/brain_sync/application/config.py`
- `src/brain_sync/application/init.py`
- `src/brain_sync/application/roots.py`
- `src/brain_sync/application/status.py`
- `src/brain_sync/interfaces/cli/parser.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sources/googledocs/auth.py`

## Context

The current repository shape creates two hard constraints that the revised plan
must respect:

1. the runtime is currently single-brain per config directory, with
   `config.json["brains"][0]` treated as the active root
2. the current MCP server resolves `resolve_active_root()` during lifespan
   startup, so the existing MCP entrypoint cannot serve a no-root bootstrap
   workflow as-is

The current daemon model also matters:

- `brain-sync run` is the actual long-running daemon engine
- the daemon already owns reconcile-on-start, watcher, polling, and regen
- runtime exclusion is enforced by `daemon.lock`
- current daemon snapshots are written to `daemon.json`
- no cross-process graceful control channel exists today for a second process
  to request stop or restart of a foreground daemon

Those realities mean the product must be explicit about what is and is not
supported in v1 rather than assuming a richer daemon-control contract than the
codebase currently provides.

## Scope

In scope for the first approved slice:

- one shared installed local runtime independent of plugin cache paths
- one shared launcher/bootstrap seam used by Claude Code, Claude Desktop, and
  Codex wrappers
- a bootstrap-capable MCP startup mode that works even when no active root is
  configured
- explicit `attach-root` behavior for the current single-brain runtime model
- application-owned daemon admin workflows for status, start, stop, restart,
  and daemon adoption
- `daemon.json` status additions only, if required
- CLI parity for daemon admin and root attachment/init behavior
- packaged runtime with Google capability included by default
- thin wrapper artifacts for Claude Code, Claude Desktop, and Codex
- required doc and test updates, including `docs/sync/README.md` and `e2e`
  coverage

Deferred from the first approved slice:

- provider-config MCP parity for Confluence and Google
- `brain_sync_logs_tail`
- richer historical controller/adoption analytics
- any runtime DB schema change

## Non-goals

- no portable brain contract change in `docs/brain/`
- no synced-source lifecycle redesign
- no multi-daemon support per runtime config directory
- no remote Claude connector path in v1
- no desktop shell or tray product in this plan
- no host-session refcounting or "stop when the last client exits" behavior in
  v1
- no runtime DB migration in the first approved slice
- no separate config directory per wrapper
- no duplicated bootstrap or supervision logic across Claude/Codex/Desktop
  wrappers

## Fixed Design Decisions

### 1. Preserve the portable brain contract

This work must not change the portable brain layout or portable schema.

If implementation discovers a real portable contract dependency, execution must
stop and return for replanning with explicit versioning and compatibility
updates.

### 2. Keep one daemon per runtime config directory

The current exclusivity rule remains authoritative.

Implication:

- terminal, Claude Code, Claude Desktop, and Codex all coordinate through the
  same runtime config directory
- a second daemon start against the same runtime config directory must still be
  denied

### 3. Keep `brain-sync run` as the real daemon engine

The product should supervise the existing daemon process rather than embedding
watcher, polling, or regen behavior into each MCP server process.

This keeps `sync/daemon.py` as the authoritative engine and makes this change
primarily about launcher/control behavior rather than daemon-behavior
redesign.

### 4. Use one shared bootstrap/launcher seam for all wrappers

Claude Code, Claude Desktop, and Codex wrappers must all call one shared
installed-runtime launcher/control surface.

That shared seam owns:

- no-root bootstrap behavior
- runtime install/update checks
- active-root readiness checks
- daemon ensure-running behavior
- daemon status/start/stop/restart/adoption logic

Wrappers own only:

- manifest format
- host-specific invocation glue
- host-specific packaging metadata

### 5. First approved slice uses a bootstrap-capable MCP entrypoint

The first approved slice should not rely on wrapper-specific preflight logic
outside MCP for no-root setup.

Instead, the shared installed runtime should expose a bootstrap-capable MCP
entrypoint that:

- starts even when no active root exists
- exposes only setup/admin tools when no active usable root exists
- transitions to full-tool behavior once a usable active root is established

This is the cleanest way to keep wrappers thin across all three hosts.

### 6. `attach-root` rewrites active-root priority explicitly

The current runtime is single-brain per config directory. Therefore
`attach-root` must be explicit about how it changes `config.json`.

Authoritative v1 behavior:

- the supplied path must already be an initialized brain root
- the chosen root becomes the active root by being written to index `0` of
  `config["brains"]`
- any other previously registered roots are preserved after it in deduplicated
  order for compatibility only
- v1 does not add a richer multi-root switching UI; switching is still an
  explicit attach operation against one path at a time

This keeps the current single-active-root contract intact while making the
mutation semantics concrete.

### 7. Prefer no runtime DB migration in the first approved slice

The first approved slice must treat "no runtime DB migration" as a real
boundary, not just as a preference.

Allowed runtime-state changes in the first slice:

- `daemon.json` additions for current daemon-admin status
- use of existing runtime tables such as `operational_events`, `token_events`,
  and existing status helpers for recent history

Not allowed in the first slice:

- new runtime DB tables
- changed runtime table schemas
- controller/adoption history persisted beyond existing event surfaces

### 8. Background daemon lifetime is explicit in v1

To avoid inventing cross-host client registration or host refcounting in the
first slice, a background daemon started through the new launcher remains
running until:

- the user explicitly stops it, or
- it exits on its own

Foreground terminal `brain-sync run` keeps its normal terminal-bound lifetime.

This is a deliberate product simplification to minimize runtime and sync
regression risk.

### 9. Provider-config MCP parity is deferred

Confluence and Google MCP config parity should not be in the first approved
slice.

The first slice should prove:

- one shared installed runtime
- no-root bootstrap and attach/init
- daemon status/start/stop/restart/adoption
- thin host wrappers

Provider configuration can follow as a bounded second slice.

## Bootstrap Architecture

### Problem

The existing MCP server resolves `resolve_active_root()` during lifespan
startup. That makes the current entrypoint unusable for no-root first-run
bootstrap.

### Chosen v1 architecture

Add a new shared installed-runtime launcher entrypoint for plugin use, with a
bootstrap-capable MCP mode. The launcher should:

1. start without requiring an active root
2. inspect runtime readiness
3. expose one of two modes over MCP:

Bootstrap mode:

- `brain_sync_setup_status`
- `brain_sync_init`
- `brain_sync_attach_root`
- `brain_sync_status`
- `brain_sync_start`
- `brain_sync_stop`
- `brain_sync_restart`

Full mode:

- all existing brain-sync MCP tools
- the daemon-admin tools above

The launcher may internally delegate to the existing full MCP server after a
usable active root exists, but that delegation must stay inside the shared
installed runtime rather than in the wrappers.

### First-run setup behavior

If no active usable root exists:

- query and source-management tools are unavailable
- setup/admin tools remain available
- daemon start is refused with a setup-required result

The intended user flow is:

1. `brain_sync_setup_status`
2. if no active root:
   - choose create-new or attach-existing
3. `brain_sync_init(root=...)` for a new root, or
   `brain_sync_attach_root(root=...)` for an existing root
4. after success, normal tools and daemon start become available

## Coexistence And Daemon-Admin Contract

### Adoptable daemon criteria

An existing daemon is considered healthy and adoptable only when all of the
following are true:

- `daemon.json` is readable
- `daemon.json.status` is `starting` or `ready`
- the recorded PID is live
- the recorded `brain_root` matches the currently active root for this runtime
  config directory
- startup exclusion still indicates that a competing daemon start should be
  refused for this runtime

If those signals disagree, the daemon is treated as stale or unhealthy and is
not adopted automatically.

### Controller kinds in v1

The first slice should distinguish at least:

- `terminal-foreground`
- `launcher-background`
- `unknown`

The controller kind should live in `daemon.json`, not in a new DB table.

### Start/stop/restart/adoption table

| Existing state | Command origin | `status` | `start` | `stop` | `restart` |
|---|---|---|---|---|---|
| No daemon | terminal CLI admin or plugin host | reports not running | starts background daemon through launcher admin flow | returns not running | starts background daemon through launcher admin flow |
| Healthy `launcher-background` daemon | terminal CLI admin or plugin host | reports running and controller kind | idempotent success with `already_running` and adoption metadata | allowed; stop shared background daemon | allowed; stop then start shared background daemon |
| Healthy `terminal-foreground` daemon | terminal CLI admin or plugin host | reports running and controller kind | idempotent success with `already_running`; daemon is adopted for read/use | returns `unsupported_for_controller_kind` in v1 | returns `unsupported_for_controller_kind` in v1 |
| Stale/unhealthy snapshot | terminal CLI admin or plugin host | reports unhealthy/stale status | launcher may recover by starting a fresh background daemon after stale-state handling | returns stale/not running | same as `start` after stale-state handling |

This table is the authoritative coexistence contract for the first approved
slice.

### Why stop/restart is bounded in v1

The current repository has no external graceful stop channel for a second
process to control a foreground terminal daemon safely across hosts,
especially on Windows.

Therefore the first slice should:

- allow full stop/restart only for `launcher-background` daemons
- treat `terminal-foreground` daemons as adoptable for status and normal use
  but not remotely stoppable in v1

This keeps the plan in launcher/control territory instead of inventing a new
daemon control plane during implementation.

### Ensure-running behavior for plugin use

The plugin-facing MCP launcher may ensure that a background daemon is running
when:

- setup is complete, and
- a normal non-bootstrap tool call arrives, and
- no healthy daemon is already running

This is a deliberate process-model change relative to the current `docs/sync`
statement that CLI/MCP commands do not start the daemon implicitly, so the
approved implementation must update `docs/sync/README.md` accordingly.

Direct CLI behavior remains unchanged unless the user explicitly invokes the
new daemon-admin CLI commands.

## Seam Impact Summary

### Portable Brain

Expected impact:

- none

Guardrail:

- any portable contract change is out of scope for this plan revision

### Interfaces

Expected impact:

- high

Work:

- add bootstrap-capable MCP launcher surface
- add daemon-admin MCP tools
- add CLI parity commands
- keep host wrappers thin around the shared launcher seam

### Application

Expected impact:

- medium

Work:

- add shared bootstrap/readiness workflow
- add explicit attach-root workflow
- add shared daemon admin/supervision workflow
- assemble daemon-admin status payloads from `daemon.json` and existing runtime
  surfaces

### Sync

Expected impact:

- medium

This revision is more explicit than the root plan: `sync/` impact is not just
"low to medium by preference." The process model does change because plugin
MCP use may now ensure a daemon is running.

Guardrail:

- do not change watcher, polling, reconcile, or regen semantics
- changes in `sync/` should be limited to what is needed to preserve the
  existing daemon engine under the new launcher/control model

### Runtime

Expected impact:

- medium

Allowed first-slice work:

- `daemon.json` additions for controller kind and daemon-admin status
- helper logic for stale vs healthy status interpretation

Not allowed in the first slice:

- runtime DB schema change

### Sources / Provider Auth

Expected impact in first slice:

- none or minimal

Provider-config MCP parity is intentionally deferred.

## First Approved Slice

The first approved slice ends at:

- shared installed runtime
- shared bootstrap/launcher seam
- bootstrap-capable MCP mode
- explicit root setup/attachment
- daemon status/start/stop/restart/adoption
- thin wrapper packaging

The first approved slice does **not** include:

- provider-config MCP parity
- log tailing
- richer historical daemon analytics

## Workstreams

### Workstream 1: Shared Bootstrap And Launcher Seam

Goals:

- create one shared installed-runtime control surface for all wrappers
- avoid wrapper-specific preflight and install logic drift

Primary modules:

- new installed-runtime launcher module and entrypoint
- `src/brain_sync/interfaces/mcp/`
- `src/brain_sync/application/`

Acceptance criteria:

- Claude Code, Claude Desktop, and Codex wrappers all invoke the same launcher
- no-root bootstrap works without wrapper-specific logic outside that launcher

### Workstream 2: Explicit Setup And Attach-Root Workflow

Goals:

- make first-run bootstrap concrete in the current single-brain runtime model

Primary modules:

- `src/brain_sync/application/init.py`
- `src/brain_sync/application/roots.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/interfaces/mcp/`
- `src/brain_sync/interfaces/cli/`

Acceptance criteria:

- `attach-root` behavior rewrites active-root priority exactly as specified
- daemon start is refused until a usable active root exists
- `doctor` remains separate from readiness/bootstrap

### Workstream 3: Daemon Supervision And Coexistence

Goals:

- supervise `brain-sync run` without redesigning it
- make start/stop/restart/adoption semantics explicit and testable

Primary modules:

- `src/brain_sync/application/`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/interfaces/cli/`
- `src/brain_sync/interfaces/mcp/`

Acceptance criteria:

- adoptable-daemon health rules match this plan
- `launcher-background` stop/restart works
- `terminal-foreground` stop/restart returns bounded unsupported results in v1
- idempotent `start` works across process boundaries

### Workstream 4: Minimal Runtime Snapshot Extension

Goals:

- expose enough daemon-admin metadata without changing runtime DB schema

Primary modules:

- `src/brain_sync/runtime/repository.py`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`

Acceptance criteria:

- status answers controller kind, PID, timestamps, root, and daemon state
- no runtime DB migration is introduced in the first slice

### Workstream 5: Wrapper Packaging

Goals:

- create thin wrappers for all three host surfaces

Deliverables:

- Claude Code plugin wrapper
- Claude Desktop local extension wrapper
- Codex plugin wrapper

Acceptance criteria:

- all wrappers share one installed runtime
- no wrapper depends on another wrapper's install path
- no wrapper duplicates bootstrap or supervision logic

## Validation Strategy

### Unit

Add unit coverage for:

- readiness classification
- attach-root config rewrite semantics
- daemon health/adoptability classification
- controller-kind specific stop/restart decisions

### MCP

Add MCP coverage for:

- bootstrap-mode tool availability
- transition from bootstrap mode to full mode after init/attach
- daemon status/start/stop/restart semantics

### System

Add subprocess CLI coverage for:

- `brain-sync start`
- `brain-sync stop`
- `brain-sync restart`
- `brain-sync attach-root`
- richer `brain-sync status`

### E2E

Add explicit `tests/e2e/` coverage for cross-process daemon control and
adoption:

- one process starts a `launcher-background` daemon and another process adopts
  it
- `start` is idempotent under an existing healthy daemon
- `status` is correct for a daemon the current process did not start
- `stop` and `restart` work for a `launcher-background` daemon across process
  boundaries
- a healthy `terminal-foreground` daemon is adoptable for status/use but not
  remotely stoppable in v1
- a second daemon start against the same runtime config dir is refused

### Manual packaging smoke

At minimum on Windows:

- first-run bootstrap with no active root
- init or attach then start
- wrapper status against a shared daemon
- Claude/Codex coexistence against one runtime

## Documentation Updates

The approved implementation must update:

- `README.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md` if `daemon.json` changes
- `docs/sync/README.md` for the new process model and ensure-running behavior
- `docs/architecture/ARCHITECTURE.md` if launcher/bootstrap responsibilities
  change package explanation
- `docs/COMPATIBILITY.md` and `docs/VERSIONING.md` only if a runtime schema
  version change is actually introduced

The implementation should not update `docs/brain/` unless a real portable
contract change is discovered, which this plan forbids in the first slice.

## Risks And Review Focus

### 1. Bootstrap-capable MCP mode may be more invasive than it looks

Review should challenge whether the launcher can stay thin enough while still
supporting no-root bootstrap without turning into a second MCP server with
duplicated tool logic.

### 2. Daemon supervision could still drift into behavior redesign

Review should reject plans that quietly add a broader daemon control plane or
host-session ownership model instead of supervising the existing engine.

### 3. The bounded stop/restart rule for terminal foreground daemons is a
product tradeoff

This revision intentionally trades some admin power for lower regression risk.
Review should decide whether that product call is acceptable for v1.

### 4. Ensure-running changes `docs/sync/` process-model guidance

Review should verify that the plan now treats this as an explicit sync-doc
change, not as an interface-only detail.

### 5. Wrapper thinness depends on enforcing one launcher seam

Review should challenge any implementation path that would let Claude Code,
Claude Desktop, and Codex build separate bootstrap/install logic.

## Review Questions

The reviewer should explicitly answer:

1. Is the bootstrap-capable MCP launcher the right no-root solution for this
   repository, or would it duplicate too much of the existing MCP server?
2. Is the explicit `attach-root` rewrite behavior correct for the current
   single-brain runtime contract?
3. Is the bounded v1 rule of "adopt foreground terminal daemon for use/status,
   but do not remotely stop or restart it" the right regression-minimizing
   product choice?
4. Is the "no runtime DB migration in first slice" boundary now concrete
   enough?
5. Does the revised proof plan require enough `e2e` coverage for cross-process
   daemon adoption and control?

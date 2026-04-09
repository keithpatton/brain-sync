# PLAN_plugin-delivery: Plugin Delivery And Daemon-Aware Productization

## Status

Planning artifact only. This document defines the implementation plan for
shipping `brain-sync` as a professionally delivered local product through:

- Claude Code plugin distribution
- Claude Desktop local extension packaging
- Codex plugin packaging

This stage does **not** authorize implementation by itself. Work should follow
the normal `docs/plans/` review and approval trail before code changes begin.

## Objective

Deliver a local-first, plugin-friendly `brain-sync` product that feels
professional to install and operate without requiring users to manage:

- a checked-out source repository
- a visible `python -m ...` MCP command
- a manually started terminal daemon

The product must preserve the current engine model:

- portable brain state remains authoritative on disk under the brain root
- runtime state remains machine-local under `~/.brain-sync/`
- only one daemon may run per runtime config directory
- normal terminal CLI commands remain supported
- plugin use must not create a second sync engine or a competing runtime

The intended user experience for v1 is:

- first-time plugin use detects whether a brain is attached and initialized
- if needed, the user is guided to create or attach a brain root
- the plugin can report daemon status and recent operational state
- the plugin can start, stop, and restart the shared daemon
- once started, the daemon keeps running in the background for that local
  runtime until it is explicitly stopped or the owning host process exits
- a second host such as Codex or Claude should adopt a healthy existing daemon
  for the same runtime config directory instead of trying to start another

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

Implementation must also align with the current owning seams that already
cover initialization, configuration, root attachment, MCP transport, daemon
lifecycle, and runtime status:

- `src/brain_sync/application/config.py`
- `src/brain_sync/application/init.py`
- `src/brain_sync/application/roots.py`
- `src/brain_sync/application/status.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/interfaces/cli/parser.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/runtime/paths.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sources/googledocs/auth.py`

Implementation should also treat the following current external distribution
shapes as packaging context rather than as authority over core engine design:

- Serko Claude marketplace structure in
  `C:\Users\keith\source\serko\serko-products\internal-tool-agent-hub`
- Codex local plugin manifest conventions available in the local Codex skill
  references

## Context

The current repository already has the essential engine pieces:

- `brain-sync run` is the real long-running daemon entrypoint
- the daemon already owns watcher, polling, reconcile-on-start, and regen work
- the CLI and MCP layers are mostly short-lived commands over durable state
- runtime exclusivity already exists through the config-dir daemon guard
- `daemon.json` already exposes a current daemon lifecycle snapshot
- runtime DB tables already hold source polling, lifecycle coordination, regen
  state, token usage, and operational events

What is missing is not a new sync engine. What is missing is a product control
plane that:

- packages the engine as a local installable runtime
- gives MCP clients first-run setup and daemon administration
- hides the current Python-and-source oriented invocation model
- lets multiple local hosts share one runtime and one daemon safely

The main regression risk is accidental redesign of daemon semantics. The
current `brain-sync run` loop is already the product's source of truth for:

- startup reconcile
- active polling
- filesystem watching
- regen queue behavior

This plan therefore prefers a conservative shape:

- keep `brain-sync run` as the actual daemon engine
- add a shared application-owned service supervision layer around it
- use a detached subprocess model rather than embedding the sync loop inside
  each MCP server process
- adopt a healthy existing daemon instead of replacing it when another local
  host is already using the same runtime

## Scope

In scope for the implementation stage:

- a shared local product runtime install shape independent of plugin cache
  paths
- a daemon-aware application service layer for status, start, stop, restart,
  log discovery, and adoption of an already running daemon
- first-run setup readiness checks for active brain attachment and
  initialization
- MCP tools for setup and daemon administration
- CLI parity for the new daemon administration surface
- a packaged production runtime that includes Google support by default
- Claude Code plugin packaging
- Claude Desktop local extension packaging
- Codex plugin packaging
- user-facing status metadata that exposes the important current daemon facts
- documentation and tests required by the chosen runtime and interface changes

## Non-goals

- no portable brain contract change in `docs/brain/`
- no change to the synced-source lifecycle model unless a later review proves
  it is required
- no multi-daemon support for one runtime config directory
- no remote Claude connector path in v1
- no desktop shell, tray app, or separate GUI installer in this plan
- no requirement that the daemon survive after all local host applications are
  gone
- no broad redesign of the runtime DB unless the review concludes a minimal
  file-level status extension is insufficient
- no plugin-specific second config directory or second daemon lock model
- no continued user-visible requirement to run `pip install -e .` or
  `pip install -e ".[google]"` for normal plugin use

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material architectural problem.

### 1. Preserve the portable brain contract

This work should not change the portable brain layout or schema.

Implication:

- `docs/brain/` should remain unchanged unless implementation reveals a
  previously hidden portable contract dependency

### 2. Preserve one daemon per runtime config directory

The current runtime exclusivity rule remains in force.

Implication:

- Claude, Claude Desktop, Codex, and terminal usage all coordinate through the
  same runtime guard and the same daemon status
- a second daemon start against the same runtime config directory must still be
  denied

### 3. Adopt a healthy existing daemon by default

If a plugin or CLI admin command sees a healthy daemon for the same runtime
 config directory, it should treat that daemon as the current shared service
rather than as a conflict.

Implication:

- `start` should be idempotent and may return success with `already_running`
- `status` must expose enough metadata for the user to understand what is
  currently attached
- a daemon started from terminal, Claude, or Codex is still the same shared
  daemon from the user's point of view

### 4. Keep `brain-sync run` as the real engine

The v1 product should supervise the existing daemon process rather than
re-implementing watcher, polling, and regen logic inside an MCP server.

Rationale:

- this best preserves current behavior
- it minimizes changes in `sync/`
- it makes terminal mode and plugin mode converge on the same engine path

### 5. Prefer no runtime DB migration in v1

The first implementation should prefer:

- application-layer daemon supervision
- `daemon.json` shape extension if needed
- richer status assembly from existing runtime state

before introducing a runtime DB migration.

If more metadata is required, the first choice should be extending
`daemon.json`, not adding or altering DB tables.

### 6. Production runtime includes Google support by default

The plugin-facing runtime should not require the user to choose a Python extra
to get Google Docs support.

Implication:

- production packaging should bundle the current `.[google]` capability
- developer install guidance may continue to use editable extras locally, but
  user-facing plugin docs should not

### 7. First-run readiness is distinct from `doctor`

The new setup/readiness surface should answer:

- is there an active brain root?
- does it exist?
- is it initialized?
- is a daemon running?
- where are logs and runtime files?

It should not replace `doctor`, which remains the brain-health and repair
surface once a brain is already attached.

### 8. Claude Code plugin, Claude Desktop extension, and Codex plugin are
different wrappers around one shared local runtime

The wrapper artifacts may differ by manifest and packaging format, but they
must converge on one stable user-level product install and one shared runtime
config model.

Implication:

- wrappers must not depend on another wrapper's install path
- wrappers must not treat plugin cache locations as durable runtime state

## Seam Impact Summary

### Portable Brain

Expected impact:

- none

Required guardrail:

- any discovered portable contract change must stop execution and trigger
  explicit versioning and compatibility review

### Interfaces

Expected impact:

- high

Primary work:

- add new MCP setup and daemon admin tools
- add CLI parity commands and richer status output
- wire wrappers to the stable installed runtime entrypoints

### Application

Expected impact:

- medium

Primary work:

- centralize daemon supervision workflows outside CLI and MCP handlers
- centralize setup readiness and brain attach/init decisions
- centralize status payload assembly for daemon-aware metadata

### Sync

Expected impact:

- low to medium if the conservative subprocess-supervision design holds
- high only if implementation drifts into refactoring the sync loop itself

Preferred constraint:

- do not change polling, watcher, reconcile, or regen semantics unless a
  review shows they are impossible to preserve under the new supervision layer

### Runtime

Expected impact:

- medium

Preferred constraint:

- keep the current DB schema unchanged if a richer `daemon.json` snapshot and
  existing runtime loaders are enough

Likely work:

- extend daemon status metadata
- improve status readers and possibly stop/start verification helpers
- document any `daemon.json` additions in `docs/runtime/`

### Sources / Provider Auth

Expected impact:

- low to medium

Likely work:

- reuse existing Confluence config persistence
- reuse existing Google OAuth browser flow
- expose those workflows through MCP and CLI parity if included in v1

## User-Facing Surface Plan

### MCP tools

The preferred v1 MCP additions are:

- `brain_sync_setup_status`
- `brain_sync_init`
- `brain_sync_attach_root`
- `brain_sync_status`
- `brain_sync_start`
- `brain_sync_stop`
- `brain_sync_restart`
- `brain_sync_logs_tail`

Strongly recommended for no-terminal parity, but review may choose to phase
them after daemon admin if needed:

- `brain_sync_config_confluence`
- `brain_sync_config_google`

### CLI parity

CLI should gain parity for daemon admin and setup:

- `brain-sync start`
- `brain-sync stop`
- `brain-sync restart`
- richer `brain-sync status`
- `brain-sync attach-root` if that is the selected setup shape

The existing `brain-sync run` command remains as the direct foreground daemon
entrypoint and should continue to be supported.

### Status metadata

The minimal daemon-aware status payload should expose:

- runtime config directory
- active brain root
- daemon status
- PID
- daemon ID
- started timestamp
- controller kind such as `terminal`, `claude-code`, `claude-desktop`,
  `codex`, or `unknown`
- log path
- enough source and regen summary to answer "what state is my brain-sync in?"

It may also include:

- whether the daemon was newly started or adopted
- current activity summary if that can be added without broad runtime changes

## Preferred Implementation Shape

The preferred implementation shape is a conservative service-supervision layer.

### Shared product runtime

Create a stable user-level install target for the packaged runtime, for
example:

- `%LOCALAPPDATA%\\brain-sync\\...` on Windows

This install target is the durable local product location used by all wrapper
artifacts.

Wrappers may:

- install or update the packaged runtime into that location
- execute stable entrypoints from that location

Wrappers must not:

- depend on another plugin's cache path
- use the plugin install directory as the durable runtime location

### Service supervision

Add an application-owned supervision layer that:

- launches `brain-sync run` as a detached subprocess
- inspects the existing daemon guard and status snapshot
- adopts a healthy existing daemon
- stops the shared daemon by verified process identity and daemon metadata
- restarts by stop-then-start with the same runtime config directory

This supervision layer should be reusable by:

- CLI
- MCP server
- packaging smoke tests

### First-run readiness

Add a small setup/readiness workflow that:

- detects whether an active brain root exists
- checks whether that root exists on disk
- checks whether it is initialized as a brain
- avoids starting the daemon before a usable brain is attached

The intended first-run sequence is:

1. `brain_sync_setup_status`
2. if no active usable brain exists, ask the user whether they want to:
   - create a new brain
   - attach an existing initialized brain
3. perform `init` or `attach-root`
4. only then allow `start` or automatic ensure-running behavior

## Workstreams

### Workstream 1: Application-Owned Daemon Supervision

Goals:

- create one reusable daemon admin layer used by CLI and MCP
- preserve current daemon behavior
- support adoption of an already running daemon

Primary modules:

- `src/brain_sync/application/`
- `src/brain_sync/runtime/`
- `src/brain_sync/interfaces/cli/`
- `src/brain_sync/interfaces/mcp/`

Preferred implementation direction:

- add a new application service module rather than growing daemon control logic
  directly inside CLI handlers or MCP tools
- keep `src/brain_sync/sync/daemon.py` focused on foreground daemon execution

Acceptance criteria:

- `start` is idempotent for the same runtime config directory
- `status` can distinguish running vs not running without scraping CLI text
- `stop` and `restart` act on the shared daemon cleanly
- a terminal-started daemon can be adopted by plugin status/control flows

### Workstream 2: Minimal Runtime Status Extension

Goals:

- expose the daemon metadata a plugin user actually needs
- avoid a DB migration if possible

Primary modules:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/runtime/config.py`
- `docs/runtime/SCHEMAS.md`
- `docs/runtime/README.md`

Preferred implementation direction:

- extend `daemon.json` first
- only introduce DB changes if a review concludes that file-level status is
  insufficient for safe supervision

Acceptance criteria:

- status payload includes the agreed daemon metadata
- daemon start and adoption flows can verify they are looking at the correct
  runtime and daemon instance

### Workstream 3: Setup And Attachment Readiness

Goals:

- make first use sane without replacing `doctor`
- support no-terminal initialization and attachment

Primary modules:

- `src/brain_sync/application/init.py`
- `src/brain_sync/application/roots.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/interfaces/cli/`

Preferred implementation direction:

- add a readiness/status workflow separate from health repair
- add an explicit attach-root workflow if current config mutation logic is not
  already reusable in a safe way

Acceptance criteria:

- first-run setup can create or attach a brain root without terminal use
- daemon start is refused when there is no usable active brain
- `doctor` remains the later health and repair surface, not bootstrap

### Workstream 4: Optional Provider Configuration MCP Parity

Goals:

- remove the last forced terminal dependency for normal plugin users

Primary modules:

- `src/brain_sync/application/config.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/interfaces/cli/`
- `src/brain_sync/sources/googledocs/auth.py`

Preferred implementation direction:

- expose existing Confluence config persistence through MCP
- expose the existing Google OAuth browser flow through MCP-triggered
  application logic

Acceptance criteria:

- a normal plugin user can configure Confluence without terminal use
- a normal plugin user can initiate Google OAuth without terminal use
- no product docs tell users to install a different build just to get Google
  support

### Workstream 5: Product Packaging And Wrapper Artifacts

Goals:

- package one shared local runtime
- create thin wrapper artifacts for each host surface

Primary deliverables:

- packaged local runtime with stable entrypoints
- Claude Code plugin wrapper
- Claude Desktop local extension wrapper
- Codex plugin wrapper

Preferred implementation direction:

- keep core runtime and wrapper logic in or alongside this repository
- treat downstream marketplace publication, such as Serko's internal Claude
  marketplace, as a release lane rather than the authoritative home of the
  engine logic

Acceptance criteria:

- all three wrappers can point at one shared installed runtime
- no wrapper depends on the install path of another wrapper
- wrappers work without a checked-out source tree

## Sequencing

The preferred sequencing is:

1. application-owned daemon supervision
2. minimal runtime status extension
3. setup and attachment readiness
4. daemon admin MCP and CLI parity
5. provider config MCP parity
6. packaging runtime entrypoints
7. wrapper artifacts for Claude Code, Claude Desktop, and Codex

Review should reject implementations that reverse this order by building
wrapper artifacts first and leaving daemon supervision semantics implicit.

## Validation Strategy

### Unit

Add unit coverage for:

- daemon status interpretation
- adoption vs new-start decisions
- start/stop/restart no-op and idempotent cases
- first-run readiness classification

### MCP

Add MCP tier coverage for:

- setup status
- init and attach-root admin flows
- daemon status/start/stop/restart
- logs-tail contract shape
- config tool behavior if included

### System

Add subprocess CLI coverage for:

- `brain-sync start`
- `brain-sync stop`
- `brain-sync restart`
- richer `brain-sync status`
- interaction with an already running daemon

### Integration

Add focused integration coverage for:

- daemon adoption when a daemon already exists for the runtime
- refusal to start when no active brain is configured
- attach/init then start flow

### Manual packaging smoke

At minimum, validate on Windows:

- packaged runtime install
- first-run init flow
- plugin start/status/logs flow
- plugin adoption of a daemon started elsewhere
- terminal `brain-sync run` refusing a second daemon for the same runtime dir

## Documentation Updates

Implementation must update the authoritative docs that match the chosen change
scope:

- `README.md` for user-facing install and operation changes
- `docs/runtime/README.md` and `docs/runtime/SCHEMAS.md` if daemon snapshot
  shape changes
- `docs/architecture/ARCHITECTURE.md` if responsibilities or process model
  explanation change
- `docs/COMPATIBILITY.md` and `docs/VERSIONING.md` if a runtime schema version
  change is introduced

The implementation should not update `docs/brain/` unless the portable brain
contract actually changes.

## Risks And Review Focus

### 1. Hidden runtime coupling could force more than a file-level status change

The preferred plan is to avoid a runtime DB migration. Review should challenge
whether that remains true once stop/restart verification and daemon adoption
are implemented.

### 2. Service supervision could accidentally redefine daemon semantics

The biggest regression risk is changing how the daemon actually behaves rather
than how it is launched and observed. Review should prefer designs that keep
the existing sync loop intact.

### 3. Wrapper packaging could leak product logic into host-specific shims

Claude Code, Claude Desktop, and Codex wrappers should stay thin. Review
should reject duplication of engine logic across wrapper implementations.

### 4. First-run setup could become an accidental onboarding product

The first-use flow should stay small and practical. Review should reject
scope creep that turns readiness into a large wizard or a replacement for
existing CLI and doctor behavior.

### 5. Cross-host sharing could become confusing without enough status detail

If daemon adoption is allowed, status must explain enough metadata for an
interested engineer to understand what is already running and why.

### 6. Provider configuration may become the critical path for plugin polish

If config flows are left terminal-only, the plugin experience will still feel
unfinished. Review should explicitly decide whether config parity is part of
the first approved slice or a bounded follow-up.

## Review Questions

The reviewer should explicitly answer:

1. Is the conservative subprocess-supervision shape sufficient, or does the
   plan still hide a deeper sync/runtime redesign?
2. Is the no-portable-contract-change constraint credible from the current
   code shape?
3. Can v1 realistically avoid a runtime DB migration, or should the plan
   acknowledge one up front?
4. Are the proposed daemon admin semantics clear enough for terminal, Claude,
   Claude Desktop, and Codex to coexist on one machine?
5. Should provider configuration MCP parity be included in the first approval,
   or deferred as a bounded second slice?

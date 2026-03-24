# PLAN_desktop-shell: Windows-First Desktop Shell And Tray UX

## Status

Planning artifact only. This document defines the implementation plan for
adding a Windows-first desktop shell around the existing `brain-sync` engine
so installation, daemon management, and day-to-day visibility feel like a
real desktop product without duplicating the engine's business logic.

This stage does **not** authorize implementation by itself. Work should follow
the normal `docs/plans/` review and approval trail before code changes begin.

## Objective

Ship a minimal, maintainable desktop experience that:

- installs cleanly for a normal Windows user
- starts a per-user tray app at login
- keeps the existing daemon running in the background
- shows current status, current activity, recent structured events, and token
  usage without scraping CLI text
- reuses existing `brain-sync` business logic, runtime state, and daemon
  behavior rather than creating a second control plane

The implementation must preserve the repository's current architecture
direction:

- portable brain state remains authoritative on disk
- runtime state remains machine-local under `~/.brain-sync/`
- the tray app is an interface shell, not a second sync engine
- logs remain secondary diagnostics, not the primary status contract
- Windows is the first supported desktop target, but the shape must minimize
  duplication for a later macOS shell

## Authoritative Inputs

Implementation must treat these documents as the primary constraints:

- `docs/RULES.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `README.md`
- `docs/plans/README.md`
- `AGENTS.md`

Implementation must also align with the current owning seams that already
cover initialization, root selection, runtime state, daemon lifecycle, and
observability:

- `src/brain_sync/application/init.py`
- `src/brain_sync/application/roots.py`
- `src/brain_sync/application/status.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/regen/diagnostics.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/util/logging.py`

## Context

The current codebase already has most of the engine behavior the desktop shell
needs:

- `brain-sync run` is the long-running daemon entrypoint
- `daemon.json` already provides a fast lifecycle snapshot
- `operational_events` already records semantic runtime events
- `token_events` already records LLM invocation cost and duration
- `regen_locks` already exposes in-flight REGEN coordination state
- `application/init.py` and `application/roots.py` already own setup and root
  validation flows
- `application/status.py` and `regen/diagnostics.py` already aggregate much of
  the user-visible status data

What is missing is not core engine logic. What is missing is a product shell
that gives normal users:

- installation and startup convenience
- a small tray surface they can trust
- a compact status view with consistent design
- onboarding that asks for only the minimum needed information

The main maintenance risk is accidental duplication. A desktop shell that
reimplements daemon supervision, runtime queries, onboarding rules, or human
status parsing would create a second product to maintain. This plan therefore
focuses on a thin interface layer and one shared desktop-oriented application
projection.

## Scope

In scope for the implementation stage:

- a Windows-first desktop entrypoint and tray app
- a per-user login-started desktop shell, not a Windows Service
- a minimal onboarding flow for choosing an existing brain root or creating a
  new one
- a shared application-owned desktop status snapshot for UI consumption
- a small extension of `daemon.json` if required for fast current-activity
  rendering
- monochrome product and tray icon assets
- a compact status window with `Overview`, `Activity`, and `Diagnostics`
- a Windows installer/bootstrap script that installs the desktop shell and
  configures login startup
- documentation and architecture-boundary updates required by the new surface
- tests for the shared application workflows and new runtime snapshot behavior

## Non-goals

- no Windows Service in the first release
- no macOS implementation in this plan
- no provider-auth onboarding for Confluence or Google in the desktop UI
- no new portable brain schema or format change
- no new runtime analytics table for desktop UX
- no CLI-output scraping as a UI data source
- no embedded rich log console or full live log-tail experience in v1
- no broad settings UI for every existing CLI option
- no web stack, Electron, or separate backend process that duplicates the
  daemon's responsibilities

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material architectural problem.

### 1. Windows v1 is a per-user tray app, not a Windows Service

The first desktop release should run as a normal user process launched at
login. It should manage the existing daemon subprocess for that same user
session.

Rationale:

- the user explicitly wants a taskbar-visible experience
- Windows Services and interactive desktop UI are an awkward fit
- `brain-sync` already models the daemon as a user-scoped runtime under
  `~/.brain-sync/`
- a per-user tray process maps better to the existing config-dir ownership
  model and is easier to port later to macOS menu-bar behavior

### 2. The desktop shell must reuse structured state, not parse CLI output

The desktop UI must read structured status from shared application and runtime
surfaces. It must not scrape `brain-sync status`, `brain-sync list --status`,
or log output intended for humans.

Primary data sources:

- `daemon.json` for fast lifecycle and current-activity snapshot
- `application/status.py` for source counts and insight-state summaries
- `regen/diagnostics.py` for REGEN cost and semantic diagnostics
- `runtime/repository.py` loaders for recent events and current REGEN locks
- `util/logging.py` only for log file location and optional diagnostics links

### 3. Desktop-specific business logic belongs in `application/`, not in UI modules

If the tray app needs a workflow that should behave identically for Windows and
later macOS, it belongs in `application/`.

The desktop interface layer should be responsible for:

- rendering
- user interaction
- tray/menu behavior
- daemon process launching and local supervision glue

It should not be responsible for:

- root validation rules
- initialization policy
- status aggregation logic
- direct interpretation of raw runtime rows beyond a shared application model

### 4. One cross-platform desktop toolkit should own tray and window surfaces

The implementation should use `PySide6` as an optional desktop dependency and
use Qt Widgets plus `QSystemTrayIcon` for the Windows shell.

Rationale:

- one toolkit can cover Windows now and macOS later
- tray support and a small native-feeling window are available in one stack
- it avoids a web stack and keeps the code in Python next to the existing
  engine
- it is easier to maintain one UI toolkit than separate tray and window
  libraries plus custom interop

Implementation shape:

- add a `desktop` optional dependency group in `pyproject.toml`
- add a separate script entrypoint such as `brain-sync-desktop`

### 5. The runtime contract should grow only by a small activity snapshot

If the tray needs a faster answer to "what is brain-sync doing right now," the
implementation may extend `daemon.json`, but it must not add a new runtime
table just for the desktop shell.

Tentative additional fields:

- `activity_kind`
- `activity_summary`
- `activity_updated_at`
- optional `active_source`
- optional `active_knowledge_path`

Deeper history and cost data must continue to come from:

- `operational_events`
- `token_events`
- `regen_locks`

### 6. v1 diagnostics prioritize recent structured events over live log streaming

The first shell should show recent semantic events and basic diagnostics links,
not a full live log stream.

This keeps the UI aligned with the existing observability contract:

- semantic status and history come from runtime tables
- logs remain useful but non-authoritative

### 7. Desktop design should be intentionally minimal and monotone

The UI contract for the first release should be:

- light background
- black / gray / white palette
- one consistent heading style
- one consistent body style
- one muted metadata style
- 8px spacing grid
- 16px panel padding baseline
- restrained rounded corners
- monochrome brain-plus-sync iconography

Windows-first typography should use the platform system font rather than
shipping a custom type stack.

## Proposed Package And Dependency Shape

The implementation should add the following package shape:

```text
src/brain_sync/
  application/
    desktop_status.py
    onboarding.py
  interfaces/
    desktop/
      __init__.py
      app.py
      controller.py
      models.py
      process.py
      tray.py
      window.py
      resources/
        brain_sync/
          icon.svg
          icon.ico
          tray-idle.png
          tray-sync.png
          tray-regen.png
          tray-attention.png
      windows/
        __init__.py
        autostart.py
        shortcuts.py
packaging/
  windows/
    install.ps1
    uninstall.ps1
    README.md
```

Expected responsibility split:

- `application/desktop_status.py`
  - one desktop-oriented snapshot API over existing runtime and application
    owners
- `application/onboarding.py`
  - detect config state, validate or register active root, initialize a new
    brain, and expose UI-friendly setup outcomes
- `interfaces/desktop/app.py`
  - desktop entrypoint and orchestration surface
- `interfaces/desktop/controller.py`
  - periodic refresh and action wiring for the UI
- `interfaces/desktop/process.py`
  - launch, stop, and monitor the daemon subprocess
- `interfaces/desktop/tray.py`
  - tray icon state and context menu
- `interfaces/desktop/window.py`
  - compact status window only
- `interfaces/desktop/windows/`
  - Windows-specific startup and shortcut helpers only
- `packaging/windows/`
  - install/uninstall bootstrap only, with no business logic

The allowed dependency direction should remain:

- `interfaces.desktop.* -> application.*`
- `application.desktop_status -> application.status / regen.diagnostics / runtime.repository / runtime.config / util.logging`
- `application.onboarding -> application.init / application.roots / runtime.config`

The desktop shell must not become a new direct caller of `sync/daemon.py`
internals beyond launching the existing command-line entrypoint as a subprocess.

## Planned Workstreams

### Workstream 1: Shared Desktop Status Projection

Goal:
Create one shared, typed application projection for desktop UI rendering.

Required outcomes:

- add `application/desktop_status.py`
- expose a compact UI-ready snapshot rather than raw runtime rows
- reuse current `application/status.py`, `regen/diagnostics.py`, and
  `runtime/repository.py` data loaders

The snapshot should answer:

- is a brain configured
- what brain root is active
- is the daemon starting, ready, stopped, or in attention state
- what current activity should the tray represent
- how many sources and insight states exist
- what recent semantic events matter
- what recent REGEN usage or token usage should be shown
- where the runtime logs live

Acceptance criteria:

- no UI module needs to query the runtime DB directly
- no UI module needs to interpret raw event payloads ad hoc
- the snapshot remains valid for later macOS reuse

### Workstream 2: Minimal Runtime Activity Snapshot

Goal:
Make current activity cheap and stable to render without adding a second
runtime data store.

Required outcomes:

- extend `daemon.json` only if current fields are insufficient
- update `sync/daemon.py` to write activity snapshots at meaningful
  transitions
- update `docs/runtime/SCHEMAS.md` if `daemon.json` grows

Candidate activity states:

- `idle`
- `syncing`
- `regenerating`
- `attention`

Acceptance criteria:

- the tray can decide icon state without reconstructing activity from logs
- the activity snapshot remains descriptive, not authoritative
- no new runtime table is introduced

### Workstream 3: Shared Onboarding Workflows

Goal:
Provide a minimal desktop onboarding flow by reusing existing init and root
logic.

Required outcomes:

- add `application/onboarding.py`
- detect no-config, no-brain, invalid-root, and ready states
- allow:
  - choose existing brain root
  - initialize a new brain root
  - register or repair the active root

Explicitly out of scope here:

- Confluence auth setup
- Google auth setup
- advanced REGEN tuning

Acceptance criteria:

- desktop setup rules match CLI setup rules
- desktop onboarding does not duplicate `application/init.py` behavior
- the minimum questions asked are only those required to create or choose a
  brain

### Workstream 4: Desktop Interface Layer

Goal:
Add a Windows tray app that remains a thin interface shell.

Required outcomes:

- add `interfaces/desktop/` package
- add `brain-sync-desktop` entrypoint
- use `PySide6` tray + widget surfaces
- launch the existing daemon command under the current Python environment
- expose quick actions:
  - open status window
  - open brain folder
  - open logs folder
  - restart daemon
  - quit desktop shell

Window sections:

- `Overview`
- `Activity`
- `Diagnostics`

The first desktop window should show:

- daemon status
- current activity summary
- active brain root
- source count
- insight-state summary
- 7-day token usage summary
- recent semantic events

Acceptance criteria:

- tray icon state maps to structured activity state
- the desktop app can recover from daemon exit by relaunching it in-session
- UI code remains thin and does not own engine rules

### Workstream 5: Visual Design Contract And Assets

Goal:
Create a durable minimal design language for the new shell.

Required outcomes:

- monochrome product icon with brain + sync motif
- tray variants for:
  - idle
  - syncing
  - regenerating
  - attention
- a small widget style contract for typography, spacing, and section layout

Acceptance criteria:

- all first-release views use the same spacing and typography rules
- iconography remains legible at tray sizes
- no custom font dependency is added

### Workstream 6: Windows Install And Login Startup

Goal:
Make first-run installation practical for normal users without introducing a
heavy installer platform in the first pass.

Required outcomes:

- add `packaging/windows/install.ps1`
- add `packaging/windows/uninstall.ps1`
- install the desktop extra and create a Startup shortcut for
  `brain-sync-desktop`
- document the install path and rollback steps

The installer/bootstrap should:

- install or upgrade the package
- install the desktop optional dependency set
- register per-user login startup
- avoid managing provider auth

Acceptance criteria:

- a Windows user can install and get the tray app at next login
- uninstall removes the startup hook cleanly
- install scripts do not contain engine business logic

### Workstream 7: Architecture Rules, Docs, And Tests

Goal:
Bring the new desktop shell fully into the repository's documented boundaries.

Required outcomes:

- update `docs/RULES.md` for the new named orchestration surface
- update `docs/architecture/ARCHITECTURE.md` for the new interface layer
- update `docs/runtime/SCHEMAS.md` if daemon snapshot fields change
- update `README.md` with desktop install and use once implementation ships
- update `tests/unit/test_architecture_boundaries.py`

Testing focus for the first implementation should be:

- unit tests for `application/desktop_status.py`
- unit tests for `application/onboarding.py`
- unit tests for daemon activity snapshot updates
- unit tests for controller and process wiring where practical
- architecture-boundary tests for the new package and orchestration surface

Explicitly acceptable in phase 1:

- no pixel-level UI automation if the business logic and controller layers are
  already covered

## Proposed Implementation Sequence

1. Add the desktop optional dependency and desktop entrypoint skeleton.
2. Implement `application/desktop_status.py` over current status and runtime
   surfaces.
3. Add the minimal `daemon.json` activity extension if the projection still
   lacks stable current-activity data.
4. Implement `application/onboarding.py`.
5. Add the Qt-based tray shell and compact status window.
6. Add Windows startup/bootstrap scripts.
7. Update architecture docs, runtime docs, and tests.

This sequence preserves the reuse-first rule by making the shared projection
and onboarding APIs land before the UI depends on them.

## Verification

The implementation is complete only when all of the following hold:

1. A Windows user can install the desktop shell and get a tray icon at login
   without manually running `brain-sync run`.
2. The desktop shell launches the existing daemon and does not duplicate sync
   or REGEN logic.
3. The desktop window can show current daemon state, current activity, source
   counts, insight-state summary, recent events, and recent token usage using
   structured shared APIs rather than CLI-output parsing.
4. First-run onboarding can initialize a new brain or select an existing brain
   root without reimplementing root validation or init policy.
5. The tray icon distinguishes at least `idle`, `syncing`, `regenerating`, and
   `attention`.
6. `docs/RULES.md`, `docs/architecture/ARCHITECTURE.md`, and
   `tests/unit/test_architecture_boundaries.py` all reflect the new desktop
   surface intentionally.
7. No new portable brain contract or runtime analytics table is introduced for
   the desktop shell.

## Risks And Review Focus

Review should challenge these areas carefully:

- whether `PySide6` is an acceptable optional dependency for the repository
- whether the proposed `daemon.json` activity fields are narrow enough to stay
  descriptive rather than becoming a second state authority
- whether `interfaces/desktop/` remains thin enough to satisfy the existing
  architecture direction
- whether the install script is sufficiently pragmatic without becoming a
  long-term packaging burden
- whether the first-release diagnostics scope is disciplined enough to avoid
  a half-built log console

## Implementation Notes For Later Approval Passes

The most important guardrail for implementation review is that any desktop
feature request should first ask:

1. can this be answered from an existing runtime or application surface
2. if not, can one shared application projection or one small runtime snapshot
   extension answer it
3. only then, should a new desktop-only mechanism be considered

If the implementation starts introducing duplicate lifecycle logic, direct raw
DB interpretation in UI code, or ad hoc status parsing, it has drifted from
this plan's core maintenance objective.

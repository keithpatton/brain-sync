# PLAN_desktop-shell Revision 2: Windows-First Desktop Shell And Tray UX

## Status

Planning artifact only. This document revises
`docs/plans/PLAN_desktop-shell.md` in response to
`docs/plans/plan_desktop-shell_review_1_2026-03-24.md`.

This revision narrows the architecture boundary, defines the application-owned
desktop status and onboarding contracts more tightly, and bounds the optional
desktop dependency so implementation does not drift into a second product or a
base-package dependency leak.

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
- `src/brain_sync/regen/diagnostics.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/util/logging.py`

## Review Deltas

This revision closes the four blockers called out in
`plan_desktop-shell_review_1_2026-03-24.md`:

1. It defines one exact new orchestration surface:
   `src/brain_sync/interfaces/desktop/app.py`.
2. It defines `application/desktop_status.py` as the sole owner of activity
   arbitration, recent-event translation, and UI-facing desktop snapshot
   shaping.
3. It defines exact single-brain active-root mutation rules for choose, init,
   and repair flows and requires those rules to become shared behavior, not
   desktop-local behavior.
4. It bounds the `PySide6` decision with import-isolation rules, clear failure
   behavior, and non-desktop proof requirements.

## Scope

In scope for the implementation stage:

- a Windows-first desktop entrypoint and tray app
- a per-user login-started desktop shell, not a Windows Service
- a minimal onboarding flow for choosing an existing brain root or creating a
  new one
- a shared application-owned desktop status snapshot for UI consumption
- a shared active-root mutation workflow for the current single-brain runtime
- a small extension of `daemon.json` if required for fast current-activity
  rendering
- monochrome product and tray icon assets
- a compact status window with `Overview`, `Activity`, and `Diagnostics`
- a Windows installer/bootstrap script that installs the desktop shell and
  configures login startup
- documentation and architecture-boundary updates required by the new surface
- tests for the shared application workflows, runtime snapshot behavior, and
  optional desktop dependency isolation

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
- no change to the current single-brain runtime model

## Fixed Design Decisions

### 1. Windows v1 is a per-user tray app, not a Windows Service

The first desktop release should run as a normal user process launched at
login. It should manage the existing daemon subprocess for that same user
session.

### 2. `src/brain_sync/interfaces/desktop/app.py` is the only new orchestration surface

This plan adds exactly one new named orchestration surface:

- `src/brain_sync/interfaces/desktop/app.py`

That status belongs only to `app.py`.

The rest of `src/brain_sync/interfaces/desktop/` remains ordinary
`interfaces -> application` code and must not gain new off-graph import
exceptions.

Explicit boundary decisions:

- `controller.py`, `models.py`, `process.py`, `tray.py`, `window.py`, and
  `windows/*` must not import `runtime`, `sync`, `regen`, `brain`, `sources`,
  or `util` directly
- those modules may import:
  - standard library modules
  - sibling desktop modules
  - `brain_sync.application.*`
  - desktop toolkit modules where explicitly allowed below

The only planned non-graph import exception required by this desktop surface is:

- `src/brain_sync/interfaces/desktop/app.py -> brain_sync.util.logging`

Rationale:

- `app.py` needs entrypoint-owned logging/bootstrap setup, matching the current
  role played by `src/brain_sync/__main__.py`
- other desktop modules should remain pure transport/presentation code or
  standard-library process glue

No other desktop-package off-graph exception is authorized by this plan.

### 3. `application/desktop_status.py` is the sole owner of activity arbitration and desktop status translation

The UI must not arbitrate between raw runtime signals.

`application/desktop_status.py` is the only owner for:

- current-activity arbitration
- recent-event filtering
- event payload translation into user-facing strings and categories
- desktop snapshot shaping for the UI

`daemon.json` may expose raw lifecycle and optional raw activity hints, but it
is not the final UI contract.

The stable application-facing output must be a typed snapshot equivalent to:

```python
@dataclass(frozen=True)
class DesktopEventView:
    occurred_utc: str
    category: Literal["daemon", "sync", "regen", "source", "attention"]
    title: str
    detail: str | None
    severity: Literal["info", "warning", "error"]

@dataclass(frozen=True)
class DesktopUsageView:
    days: int
    total_invocations: int
    total_input: int
    total_output: int
    total_tokens: int

@dataclass(frozen=True)
class DesktopSnapshot:
    configured: bool
    root_state: Literal["missing_config", "invalid_root", "ready"]
    tray_state: Literal["idle", "syncing", "regenerating", "attention"]
    daemon_lifecycle: Literal["missing", "starting", "ready", "stopped"]
    headline: str
    detail: str | None
    active_root: str | None
    source_count: int
    insight_states_by_status: dict[str, int]
    active_sync_source: str | None
    active_regen_paths: tuple[str, ...]
    recent_events: tuple[DesktopEventView, ...]
    usage_7d: DesktopUsageView | None
    log_path: str | None
```

The exact Python names may vary, but the output contract must remain
equivalent in meaning and responsibility.

Activity precedence is also fixed here. When multiple raw signals are present
for the same snapshot, `application/desktop_status.py` must decide in this
order:

1. `attention`
2. `regenerating`
3. `syncing`
4. `idle`

Precedence rules:

- `attention` wins when root configuration is invalid, the daemon should be
  running but is stopped unexpectedly, or a current daemon/session signal
  implies failure that needs user attention
- `regenerating` wins when any live `regen_locks` row is in `running` state
- `syncing` wins when the daemon is actively starting or when raw daemon
  activity hints indicate source-processing work and no higher-precedence
  state is active
- `idle` applies only when the root is ready, the daemon is healthy, and no
  higher-precedence signal is present

Recent-event translation is fully owned by `application/desktop_status.py`.
`controller.py` and `window.py` may render `DesktopEventView` items, but they
must not inspect raw `event_type` values or decode `details_json`.

### 4. Active-root mutation rules are shared business logic, not desktop-local behavior

This plan intentionally fixes active-root mutation semantics for the current
single-brain runtime.

The shared rule remains:

- `config.json.brains[0]` is the active root

The implementation must introduce one shared activation workflow used by
desktop onboarding and available for future CLI reuse. The workflow may live in
`application/roots.py`, `runtime/config.py`, or another shared owner chosen in
implementation review, but it must not live only in `application/onboarding.py`.

Required shared mutation rules:

- choosing an already-registered valid root promotes that root to index `0`
  and preserves the relative order of the remaining distinct entries
- choosing an unregistered valid root inserts it at index `0` and removes any
  duplicate of the same normalized path elsewhere in the list
- initializing a new root must register it and make it active immediately by
  placing it at index `0`
- repairing an invalid active root must:
  - promote the first later valid root to index `0` when one exists, or
  - return an explicit "user choice required" onboarding outcome when no valid
    configured root exists

`application/onboarding.py` must consume those shared rules and expose typed
results, but it must not be the only place where active-root ordering semantics
exist.

The onboarding outcome model must be equivalent to:

```python
@dataclass(frozen=True)
class OnboardingState:
    state: Literal[
        "missing_config",
        "no_registered_roots",
        "invalid_active_root_repairable",
        "invalid_active_root_unrepairable",
        "ready",
    ]
    active_root: str | None
    repair_candidate_roots: tuple[str, ...]
```

### 5. `PySide6` remains optional and must be import-isolated

The implementation should use `PySide6` as an optional `desktop` dependency,
but that choice is bounded by strict import isolation.

Import-isolation rule:

- `PySide6` imports may exist only in:
  - `src/brain_sync/interfaces/desktop/app.py`
  - `src/brain_sync/interfaces/desktop/tray.py`
  - `src/brain_sync/interfaces/desktop/window.py`
- `controller.py`, `models.py`, `process.py`, `windows/*`, and all
  `application/`, `interfaces/cli/`, `interfaces/mcp/`, `runtime/`, `sync/`,
  `regen/`, `brain/`, `sources/`, and `util/` modules must remain free of
  `PySide6` imports

Failure behavior when the desktop entrypoint is invoked without the extra:

- `brain-sync-desktop` must fail closed with a clear install hint
- the error message should direct the user to install the desktop extra, for
  example `pip install ".[desktop]"`
- failure to import `PySide6` must not break CLI or MCP entrypoints

Proof requirements:

- add an architecture/unit test that fails if `PySide6` appears outside the
  allowed desktop UI modules
- add a desktop-entrypoint test proving the missing-`PySide6` failure path is
  clear and isolated
- add proof that non-desktop import surfaces still load without touching
  desktop modules, at minimum:
  - `brain_sync.__main__`
  - `brain_sync.interfaces.cli.parser`
  - `brain_sync.interfaces.mcp.server`
  - `brain_sync.application.status`

### 6. The runtime contract should grow only by a small raw activity snapshot

If the tray needs a faster answer to "what is brain-sync doing right now," the
implementation may extend `daemon.json`, but only as a raw descriptive hint.

Tentative raw fields:

- `activity_kind`
- `activity_summary`
- `activity_updated_at`
- optional `active_source`
- optional `active_knowledge_path`

These fields are not the final UI contract. `application/desktop_status.py`
still owns the final arbitration and translation.

### 7. v1 diagnostics prioritize recent structured events over live log streaming

The first shell should show recent semantic events and basic diagnostics links,
not a full live log stream.

### 8. Desktop design should be intentionally minimal and monotone

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
  - typed desktop snapshot over existing runtime and application owners
  - all activity arbitration and event translation
- `application/onboarding.py`
  - typed onboarding-state projection and minimal setup orchestration
  - delegates active-root mutation to one shared root-activation workflow
- `interfaces/desktop/app.py`
  - only new orchestration surface
  - entrypoint bootstrap, logging setup, toolkit boot, controller wiring
- `interfaces/desktop/controller.py`
  - application-snapshot polling and action dispatch only
- `interfaces/desktop/process.py`
  - standard-library daemon subprocess launch/stop/check only
- `interfaces/desktop/tray.py`
  - tray rendering and menu wiring only
- `interfaces/desktop/window.py`
  - compact status window rendering only
- `interfaces/desktop/windows/`
  - Windows startup/shortcut helpers only

## Planned Workstreams

### Workstream 1: Shared Desktop Status Projection

Goal:
Create one shared, typed application projection for desktop UI rendering.

Required outcomes:

- add `application/desktop_status.py`
- define the stable snapshot contract described above
- fully own raw signal arbitration and event translation there
- reuse `application/status.py`, `regen/diagnostics.py`, and
  `runtime/repository.py` data loaders

Acceptance criteria:

- no UI module queries the runtime DB directly
- no UI module inspects raw event types or payload JSON
- precedence is tested explicitly as `attention > regenerating > syncing > idle`
- the snapshot contract is reusable by a later macOS shell without re-deciding
  business rules

### Workstream 2: Minimal Raw Activity Snapshot

Goal:
Make current activity cheap and stable to render without adding a second
runtime data store.

Required outcomes:

- extend `daemon.json` only if current fields are insufficient
- update `sync/daemon.py` to write raw activity hints at meaningful
  transitions
- document those fields in `docs/runtime/SCHEMAS.md`

Acceptance criteria:

- the raw daemon snapshot remains descriptive, not authoritative
- `application/desktop_status.py` remains the final owner of desktop state
- no new runtime table is introduced

### Workstream 3: Shared Active-Root Mutation And Onboarding

Goal:
Provide a minimal desktop onboarding flow without inventing desktop-local root
policy.

Required outcomes:

- add one shared active-root mutation workflow
- add `application/onboarding.py`
- define exact onboarding outcomes for:
  - missing config
  - no registered roots
  - invalid active root with repair candidate
  - invalid active root without repair candidate
  - ready

Acceptance criteria:

- choosing a root, initializing a root, and repairing a root all obey the
  shared active-root ordering rules above
- desktop onboarding and future CLI root-selection flows cannot drift on
  `brains[0]` semantics
- initializing a new root makes it active immediately

### Workstream 4: Desktop Interface Layer

Goal:
Add a Windows tray app that remains a thin interface shell.

Required outcomes:

- add `interfaces/desktop/` package
- add `brain-sync-desktop` entrypoint
- confine `PySide6` imports to the allowed UI modules
- launch the existing daemon command under the current Python environment
- expose quick actions:
  - open status window
  - open brain folder
  - open logs folder
  - restart daemon
  - quit desktop shell

Acceptance criteria:

- `app.py` is the only new orchestration surface
- no other desktop module gains off-graph imports
- tray icon state is driven only by the typed desktop snapshot
- the desktop app can recover from daemon exit by relaunching it in-session

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

Acceptance criteria:

- a Windows user can install and get the tray app at next login
- uninstall removes the startup hook cleanly
- install scripts do not contain engine business logic

### Workstream 7: Architecture Rules, Docs, And Tests

Goal:
Bring the new desktop shell fully into the repository's documented boundaries.

Required outcomes:

- update `docs/RULES.md` for the one new named orchestration surface and its
  exact allowed non-graph import exception
- update `docs/architecture/ARCHITECTURE.md` for the new interface layer
- update `docs/runtime/SCHEMAS.md` if daemon snapshot fields change
- update `README.md` with desktop install and use once implementation ships
- update `tests/unit/test_architecture_boundaries.py`
- add tests proving:
  - `PySide6` imports stay isolated
  - desktop entrypoint failure is clear when `PySide6` is absent
  - CLI/MCP/shared application surfaces still import without desktop extra

## Proposed Implementation Sequence

1. Add the shared active-root mutation helper and `application/onboarding.py`.
2. Add `application/desktop_status.py` with the typed snapshot contract and
   explicit precedence tests.
3. Add the minimal raw `daemon.json` activity extension if the snapshot still
   lacks stable current-activity data.
4. Add the `desktop` optional dependency and `brain-sync-desktop` entrypoint
   skeleton with missing-dependency failure handling.
5. Add the Qt-based tray shell and compact status window.
6. Add Windows startup/bootstrap scripts.
7. Update architecture docs, runtime docs, and tests.

This sequence intentionally lands shared business rules before the UI so the
desktop layer cannot silently become the place where those rules are invented.

## Verification

The implementation is complete only when all of the following hold:

1. A Windows user can install the desktop shell and get a tray icon at login
   without manually running `brain-sync run`.
2. The desktop shell launches the existing daemon and does not duplicate sync
   or REGEN logic.
3. `src/brain_sync/interfaces/desktop/app.py` is the only new orchestration
   surface added by this work, and no other desktop module gains off-graph
   imports.
4. The desktop window shows daemon state, current activity, source counts,
   insight-state summary, recent events, and recent token usage using the typed
   `application/desktop_status.py` contract rather than CLI-output parsing or
   raw runtime-row inspection in UI code.
5. Activity precedence is implemented and tested as
   `attention > regenerating > syncing > idle`.
6. Choosing an existing root, initializing a new root, and repairing an
   invalid configured root all obey one shared active-root mutation rule set
   centered on `brains[0]` as the active root.
7. Invoking `brain-sync-desktop` without `PySide6` installed fails with a
   clear install hint, while CLI, MCP, and shared application imports remain
   usable without the desktop extra.
8. `docs/RULES.md`, `docs/architecture/ARCHITECTURE.md`,
   `docs/runtime/SCHEMAS.md`, and
   `tests/unit/test_architecture_boundaries.py` all reflect the new desktop
   surface intentionally.
9. No new portable brain contract or runtime analytics table is introduced for
   the desktop shell.

## Risks And Review Focus

Review should challenge these areas carefully:

- whether the single new orchestration-surface exception is tight enough for
  the current boundary-test regime
- whether the typed desktop snapshot is specific enough to keep business rules
  out of UI code
- whether the shared active-root mutation workflow belongs in the chosen owner
  and is explicit enough to prevent CLI/desktop drift
- whether `PySide6` remains an acceptable optional dependency once the import
  isolation and proof burden are applied
- whether the install/bootstrap approach remains pragmatic without becoming a
  long-term packaging burden

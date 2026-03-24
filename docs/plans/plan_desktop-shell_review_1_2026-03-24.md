# Review

Reviewed artifact: `docs/plans/PLAN_desktop-shell.md`
Reviewed on: `2026-03-24`
Reviewer: `codex-gpt-5`

## Findings

### 1. The new desktop orchestration boundary is still not specified tightly enough

`docs/plans/PLAN_desktop-shell.md:242-307` introduces
`interfaces/desktop/app.py`, `controller.py`, `process.py`,
`tray.py`, `window.py`, and `windows/*`, and
`docs/plans/PLAN_desktop-shell.md:489-493` says the implementation should
update `docs/RULES.md` for a new named orchestration surface. But
`docs/RULES.md:215-229` requires orchestration surfaces to be exact and closed,
and `docs/architecture/ARCHITECTURE.md:122-137` keeps `interfaces/` as a
transport layer while entrypoints do the cross-subsystem wiring. The plan says
`app.py` is an orchestration surface, but it does not lock down whether that
status belongs only to `app.py` or whether nearby files such as
`process.py` or `windows/autostart.py` may also grow cross-subsystem imports.
That is a real boundary decision, not an implementation detail, because the
architecture tests require an exact allowlist.

Required fix:
- state explicitly that `src/brain_sync/interfaces/desktop/app.py` is the only
  new named orchestration surface added by this plan
- state explicitly that the rest of `interfaces/desktop/` remains ordinary
  `interfaces -> application` code with no new off-graph import exceptions
- name any exact exception the planner believes is required now, rather than
  leaving that choice to implementation-time guesswork

### 2. The desktop status seam still leaves activity arbitration and event translation to the implementer

`docs/plans/PLAN_desktop-shell.md:323-338` says
`application/desktop_status.py` should answer daemon state, current activity,
recent semantic events, token usage, and log location, while
`docs/plans/PLAN_desktop-shell.md:353-364` lists only candidate activity
states and `docs/plans/PLAN_desktop-shell.md:428-432` expects tray icon state
to map to that structured activity state. In current code,
`src/brain_sync/sync/daemon.py:220-303` processes source sync work and then
regen work inside the same loop, so more than one "what is it doing now"
signal can be true during one session. At the same time,
`docs/runtime/SCHEMAS.md:83-96` shows that `daemon.json` currently carries only
`starting` / `ready` / `stopped` lifecycle state.

The plan does not specify:
- whether `syncing` vs `regenerating` vs `attention` precedence is decided in
  `daemon.json` or in `application/desktop_status.py`
- whether recent-event filtering and payload translation are fully owned by
  `application/desktop_status.py`
- what stable typed output the UI receives after that translation

Without those decisions, `controller.py` or `window.py` will end up owning
business rules the plan is trying to keep out of the UI.

Required fix:
- define one exact owner for activity arbitration and status translation
- define precedence when multiple raw signals are present in the same daemon
  session
- specify the stable application-level snapshot shape tightly enough that UI
  code only renders fields instead of interpreting raw runtime state

### 3. The onboarding seam does not yet resolve active-root mutation semantics for the single-brain runtime

`docs/plans/PLAN_desktop-shell.md:374-392` says
`application/onboarding.py` should detect `no-config`, `no-brain`,
`invalid-root`, and `ready`, and allow the user to choose an existing brain,
initialize a new brain, or "register or repair the active root." That is not
yet specific enough for the current runtime model. `src/brain_sync/runtime/config.py:58-72`
treats only `config.json.brains[0]` as the active root, while
`src/brain_sync/application/init.py:67-96` currently registers a root by
appending it if missing rather than promoting it to active position.

The plan does not say:
- whether choosing an already-registered root must move it to index `0`
- whether initializing a new root must always make it active immediately
- how "repair active root" behaves when the first configured root is invalid
  but later entries exist
- which exact config mutations are considered the shared CLI-desktop rule set

Those choices materially affect whether desktop onboarding really matches the
CLI/runtime semantics or silently invents a different active-root policy.

Required fix:
- specify the exact active-root mutation rules for choose, init, and repair
- state the intended `application/onboarding.py` outcomes for each config
  state, including how `brains` ordering is rewritten when needed
- make the acceptance criteria strong enough that CLI and desktop cannot drift
  on active-root behavior

### 4. The `PySide6` optional-dependency decision is not yet bounded by import-isolation and proof requirements

`docs/plans/PLAN_desktop-shell.md:176-191` and
`docs/plans/PLAN_desktop-shell.md:401-403` choose `PySide6` as an optional
desktop dependency, but `docs/plans/PLAN_desktop-shell.md:495-505` and
`docs/plans/PLAN_desktop-shell.md:527-541` do not require proof that the base
package remains usable without that extra installed. In the current project,
`pyproject.toml:10-38` keeps desktop dependencies out of the base install
entirely. That is viable only if import boundaries remain strict enough that
CLI, MCP, and shared application modules do not import Qt transitively.

Right now the plan leaves two important things unresolved:
- what import-isolation rule prevents `PySide6` from becoming a de facto base
  dependency
- what validation proves non-desktop installs still work after the new surface
  lands

Required fix:
- state that desktop toolkit imports are isolated to desktop-entrypoint-owned
  modules and must not leak into base CLI/MCP/shared-application import paths
- add explicit acceptance criteria and test proof for running/importing the
  non-desktop product without the `desktop` extra installed
- state how packaging or entrypoint errors should fail when a user invokes the
  desktop shell without `PySide6` present

## Open Questions / Assumptions

- I assumed the plan is trying to preserve the current single-brain runtime
  semantics exactly, not create a new desktop-only notion of the active root.
- I assumed the intended reuse-first design means `application/desktop_status.py`
  and `application/onboarding.py` should be specific enough that a later macOS
  shell can reuse them without re-deciding UI-visible business rules.

## Verdict

Changes required.

Create a new plan revision that closes the orchestration-boundary ambiguity,
defines one exact application-owned status/onboarding contract, and adds a
strict optional-dependency proof story for `PySide6`. This review artifact
does not approve the plan and does not authorize implementation.

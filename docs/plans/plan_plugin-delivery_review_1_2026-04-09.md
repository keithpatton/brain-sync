# plan_plugin-delivery Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-04-09
**Reviewed document:** `docs/plans/PLAN_plugin-delivery.md`
**Reviewed against:**
- `docs/plans/README.md`
- `AGENTS.md`
- `docs/RULES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/sync/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- current code in `src/brain_sync/application/`, `src/brain_sync/interfaces/`,
  `src/brain_sync/runtime/`, and `src/brain_sync/sync/`

## Verdict

Changes required.

The plan has the right overall direction: keep `brain-sync run` as the real
engine, preserve the portable brain contract, keep wrappers thin, and prefer
`daemon.json` extension before a runtime DB migration.

It is not ready for approval as written because the current repository shape
exposes three unresolved design gaps that the implementer would otherwise have
to guess through:

1. first-run/bootstrap behavior is under-specified relative to the current MCP
   startup model and current single-brain runtime config rules
2. cross-host start/stop/restart/adoption semantics are not concrete enough to
   guarantee that this remains supervision of the existing daemon rather than a
   daemon-behavior redesign
3. the documentation and proof plan understate the `sync/` process-model
   impact and do not require the `e2e` coverage this change needs

This review does not approve the plan and does not authorize implementation.

## Critical Issues

### C1. The plan does not make first-run bootstrap and attach-root semantics concrete enough for the current codebase

The current repository does not have a reusable `attach-root` application
workflow today. `PLAN_plugin-delivery.md` correctly notices that one may need
to be added, but it leaves the key behavior underspecified.

That is a real gap in this repo, not a hypothetical one:

- `src/brain_sync/interfaces/mcp/server.py` resolves `resolve_active_root()`
  during lifespan startup, so the current MCP server cannot serve a no-root
  "setup status" flow without either:
  - a wrapper-managed preflight/bootstrap step outside MCP, or
  - a new bootstrap-capable MCP server startup mode
- `src/brain_sync/runtime/config.py` and `docs/runtime/README.md` make the
  current runtime explicitly single-brain per config directory, with only
  `brains[0]` treated as active runtime state
- `src/brain_sync/application/init.py` currently appends a root registration;
  that is not the same thing as an explicit "make this root active" contract

So "attach an existing initialized brain" is not yet a small transport-layer
addition. The plan must state the authoritative behavior for:

- how a no-root plugin session reaches setup tools at all
- whether `attach-root` replaces the active root, prepends it, or rewrites the
  full registered-root list
- whether the first approved slice supports switching between multiple already
  registered roots, or only establishing one active root for a fresh runtime

Without those choices, the implementer would be guessing inside the
`runtime/` and `application/roots.py` seam.

### C2. The daemon stop/restart/adoption contract is not clear enough to prove this is still supervision of the existing `brain-sync run`

The plan wants a detached subprocess supervisor around `brain-sync run`, which
is directionally right, but the current repo does not yet provide the stop and
restart contract that this plan assumes.

Current code reality:

- `src/brain_sync/sync/daemon.py` owns the foreground daemon loop
- `src/brain_sync/runtime/repository.py` owns startup exclusion via
  `daemon.lock` and status snapshots via `daemon.json`
- `write_daemon_status()` currently writes only `starting`, `ready`, and
  `stopped` snapshots
- there is no external control channel today for a second process to request a
  graceful stop from an already running daemon

That leaves critical v1 questions unanswered:

- if a user started `brain-sync run` in a terminal, may Claude/Codex/Desktop
  stop that foreground daemon from another host?
- if yes, what is the graceful mechanism, especially on Windows?
- if no, what should `brain_sync_stop` and `brain_sync_restart` return when
  the daemon is healthy but foreground-owned elsewhere?
- how does "detached subprocess" coexist with the stated rule that the daemon
  keeps running until explicitly stopped or the owning host process exits?
- what exact evidence makes a daemon "healthy" enough to adopt:
  lock ownership, PID liveness, matching `brain_root`, recent snapshot, or
  some combination?

Until those semantics are explicit per controller kind, the plan is still
leaving daemon behavior design to implementation.

## Significant Issues

### S1. The seam-impact and doc-update sections understate the `sync/` process-model change

The plan says `sync/` impact should stay low to medium, but the current docs
say more precisely what will change:

- `docs/sync/README.md` currently states that normal CLI and MCP source
  management commands do not start the daemon implicitly
- the plan introduces setup flows, daemon admin flows, and possible
  ensure-running behavior for plugin use
- the plan also changes the operational story for how terminal, Claude Code,
  Claude Desktop, and Codex coexist around one daemon

That is a real `docs/sync/` update trigger under `AGENTS.md`. The current
documentation section in the plan omits `docs/sync/README.md`, even though the
process model and daemon adoption semantics are part of its authoritative
scope.

The revised plan should require `docs/sync/README.md` updates whenever the
approved implementation changes:

- process-boundary explanation
- daemon adoption/start/stop/restart behavior
- whether plugin commands may ensure a daemon is running
- how those new flows still preserve the existing watcher/reconcile/poll model

### S2. The no-runtime-migration claim is credible only if the first approved slice is tightened

I do think v1 can likely avoid a runtime DB migration, but only if the slice is
made narrower and more explicit than the current plan text.

Grounded current surfaces already available:

- `daemon.lock` for startup exclusion
- `daemon.json` for current lifecycle snapshot
- existing `operational_events` and `token_events` for recent local history
- current runtime config for attached-root state

That supports a file-first v1 if the plan explicitly bounds the first slice to:

- `daemon.json` additions only for current daemon-admin status
- no new runtime tables
- no attempt to add historical adoption analytics or cross-process ownership
  history beyond the existing local event surfaces

As written, the status goals drift toward richer controller/adoption metadata
and "recent operational state" without clearly separating:

- what must live in `daemon.json`
- what may be assembled from existing runtime tables
- what would be out of scope for v1 if it would require a runtime migration

The revised plan should tighten those boundaries rather than leaving the
migration question open during implementation.

### S3. The proof plan is too light for cross-process daemon control; this needs explicit `e2e` coverage

The validation section calls for unit, MCP, system, integration, and manual
packaging smoke coverage. That is not enough for the specific risks this plan
introduces.

Per `AGENTS.md`, the repo already has an `e2e` tier for daemon plus CLI
subprocess lifecycle, concurrency, and watcher behavior. The new risks are
exactly in that class:

- one process starts the daemon, another adopts it
- one process reports status against a daemon it did not start
- start is idempotent under an existing healthy daemon
- stop/restart behavior is correct across process boundaries
- startup is refused for a second daemon against the same config dir

Those are not just unit/system concerns. The revised plan should require
targeted `tests/e2e/` coverage for cross-process daemon control and adoption.

## Moderate Issues

### M1. The thin-wrapper requirement should be enforced by a shared bootstrap/launcher seam, not just by convention

The plan says Claude Code, Claude Desktop, and Codex wrappers must stay thin
around one installed runtime. That direction is correct, but the current plan
does not require a single shared bootstrap/launcher seam strongly enough.

Given the bootstrap gap in C1, there is a real risk that each wrapper grows
its own:

- "is a brain attached?" preflight
- local install/update logic
- daemon ensure-running behavior
- log/runtime path discovery

The revised plan should require one shared installed-runtime launcher/control
surface that all wrappers call, with host-specific wrappers limited to manifest
format and host invocation glue.

### M2. The first-run flow is correctly kept separate from `doctor`, but the slice should be narrowed further

The plan is right that setup/readiness is distinct from `doctor`.

For the first approved slice, keep it to:

- detect whether an active root exists
- detect whether the configured root exists
- detect whether it is initialized
- initialize a new root or attach one existing root
- refuse daemon start until a usable root exists

`brain_sync_logs_tail` and provider-config parity should not be part of that
minimal bootstrap contract.

## Explicit Answers To The Review Questions

1. Is the conservative subprocess-supervision shape sufficient, or does the
   plan still hide a deeper sync/runtime redesign?

   Sufficient in principle, but not yet in this revision. It becomes
   sufficient only if the revised plan makes stop/restart/adoption semantics
   explicit enough that `sync/daemon.py` remains the engine and the new layer
   is clearly only launcher/control glue.

2. Is the no-portable-contract-change constraint credible from the current
   code shape?

   Yes. The required bootstrap, attach, packaging, and daemon-admin work can
   stay entirely in runtime/application/interface seams. Nothing in the
   current plan requires changing the portable brain contract unless a later
   revision explicitly chooses to.

3. Can v1 realistically avoid a runtime DB migration, or should the plan
   acknowledge one up front?

   V1 can realistically avoid a runtime DB migration if the first approved
   slice is narrowed to file-based daemon status plus existing runtime tables
   for recent events. The current plan should tighten that boundary, not
   assume a migration-free outcome while still leaving richer status/history
   requirements ambiguous.

4. Are the proposed daemon admin semantics clear enough for terminal, Claude,
   Claude Desktop, and Codex to coexist on one machine?

   No. The plan needs an explicit coexistence table or equivalent normative
   section covering foreground terminal runs, background plugin-started runs,
   adoption, stop, restart, and owner-host exit behavior.

5. Should provider-config MCP parity be included in the first approval, or
   deferred as a bounded second slice?

   Deferred.

   Reasoning:

   - the current repository already has application/CLI config flows for
     Confluence and Google
   - Google parity is not a trivial field write; it includes a browser OAuth
     path and user-supplied client credentials
   - provider config is not required to prove the core architectural promise
     of this plan: one installed runtime, one shared daemon, thin wrappers,
     and minimal setup/admin flows
   - deferring it keeps the first approved slice focused on the shared runtime
     and daemon-control contract instead of broadening bootstrap and MCP
     complexity before the daemon model is proven

   The revised plan should state that the first approved slice ends at shared
   runtime install, root setup/attachment, daemon status/start/stop/restart,
   and thin wrapper packaging. Provider-config MCP parity can then follow as a
   bounded second artifact or later plan revision.

## Required Revisions Before Approval

Revise the plan so it:

1. defines the bootstrap architecture for no-root plugin use and makes
   `attach-root` semantics explicit for the current single-brain runtime model
2. defines start/stop/restart/adoption behavior explicitly for:
   - terminal foreground `brain-sync run`
   - Claude Code
   - Claude Desktop
   - Codex
3. states what makes an existing daemon "healthy" and therefore adoptable
4. tightens the first approved slice so "no runtime DB migration" is a real
   enforced boundary, not just a preference
5. defers provider-config MCP parity from the first approved slice
6. adds `docs/sync/README.md` to required doc updates for any approved process
   model change
7. adds explicit `e2e` coverage requirements for cross-process daemon control
   and adoption

## Conclusion

The plan is close in intent but not yet executable as an approval handoff.

The biggest issue is not product ambition. It is that the current repo has
very specific runtime and process-boundary rules already, and the plan does
not yet pin down how first-run bootstrap and cross-host daemon control fit
inside those rules without forcing the implementer to improvise.

Create a revised plan artifact that resolves the issues above. This review
artifact does not approve the plan and does not authorize implementation.

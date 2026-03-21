# PLAN_test-isolation-hardening: Test Isolation And Operational Event Hardening

## Status

Planning artifact only. This document defines a hardening plan for the test
isolation model and the operational-event runtime routing gap that allowed test
activity to append rows into the machine-local runtime DB.

This stage does **not** approve implementation. It records the observed
failure, current-code investigation anchors, required product and test-harness
changes, sequencing, and acceptance criteria for later review and approval.

## Objective

Make it impossible for repository tests to read from or write to a user's live
brain or live machine-local runtime state, even when:

- a subprocess misses an isolation env var
- a caller omits session or owner metadata
- code resolves config or runtime paths through cached module globals
- a test uses config-discovered root resolution instead of passing an explicit
  root
- a new test or helper bypasses the existing isolation fixtures by accident

The implementation and review should leave the repository with:

- fail-closed product behavior for brain-scoped operational events
- one centralized and reusable way for tests to acquire isolated config,
  runtime, and brain fixtures
- stronger proof that no test path can touch a live user brain, runtime DB, or
  daemon state by default

## Problem Statement

Recent rows in the machine-local `operational_events` table showed test-shaped
canonical IDs and event types such as:

- `source.registered`
- `source.moved`
- `source.removed`
- `watcher.move_observed`
- `watcher.move_applied`
- `source.child_request.cleared`

The leaked rows had `session_id = NULL` and `owner_id = NULL`, which is
consistent with command-style or helper-driven operational-event writes rather
than daemon lifecycle ownership.

Current code investigation shows that this is not a test-only harness defect.
The product currently allows a brain-scoped operational-event write to route
through a config-dir-scoped runtime connection without carrying the active
brain root into the enforcement seam. That means a missed isolation env var can
still write into the machine-local runtime DB.

At the same time, the current test isolation model is only partially
centralized. It relies on a mix of:

- import-time environment setup
- per-test monkeypatches of module-level cached config paths
- separate subprocess env builders in system, E2E, and MCP tests

That layered approach usually works, but it is brittle and can drift as new
tests or helpers appear.

## Authoritative Inputs

The implementation and review must treat these documents as the primary
constraints:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`

The implementation and review must also align with the current runtime,
application, sync, regen, and test seams:

- `src/brain_sync/runtime/paths.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/application/roots.py`
- `src/brain_sync/application/query_index.py`
- `src/brain_sync/application/local_files.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/finalization.py`
- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `tests/conftest.py`
- `tests/system/conftest.py`
- `tests/e2e/conftest.py`
- `tests/e2e/harness/cli.py`
- `tests/e2e/harness/daemon.py`
- `tests/mcp/test_mcp_stdio.py`
- `tests/unit/test_runtime_safety.py`
- `tests/unit/test_runtime_operational_events.py`
- `tests/unit/test_sync_events.py`
- `tests/unit/test_token_tracking.py`
- `tests/system/test_cli_commands.py`

## Investigation Anchors

### Confirmed runtime-routing gap

Current code inspection shows:

- `src/brain_sync/runtime/repository.py` defines `_connect(root)` as the
  guarded runtime DB entrypoint and applies `ensure_safe_temp_root_runtime()`
- the same module defines `_connect_runtime()` as a rootless helper
- `record_operational_event()` currently writes through `_connect_runtime()`
  rather than requiring an explicit brain root
- many brain-scoped callers already have `root: Path` available but currently
  drop it before writing the event

### Confirmed test-isolation topology

Current test isolation already exists in several places:

- `tests/conftest.py` isolates env and monkeypatches cached config/runtime
  module globals for in-process tests
- `tests/system/conftest.py` and `tests/e2e/conftest.py` provide isolated
  config dirs
- `tests/e2e/harness/cli.py` and `tests/e2e/harness/daemon.py` build isolated
  subprocess envs
- `tests/mcp/test_mcp_stdio.py` builds its own subprocess env

These are useful building blocks, but they are distributed rather than fully
centralized.

## Findings Driving This Plan

The implementation round derived from this plan is required because the
investigation established the following material gaps.

### 1. Brain-scoped operational events can bypass root-aware safety

The product currently lets `record_operational_event()` connect through a
config-dir-scoped runtime path without carrying the active brain root. This is
the main root cause behind the observed machine-local `operational_events`
leak.

### 2. The blast radius is broader than one sync module

Brain-scoped operational-event calls exist in runtime helpers, application
helpers, sync lifecycle/finalization/reconcile flows, and regen code. This is
one shared routing defect expressed through multiple event families, not one
isolated caller bug.

### 3. Test isolation is partly convention-based and therefore drift-prone

The suite relies on multiple env builders and monkeypatch lists. That creates
future risk because a new subprocess helper, a newly imported cached path, or a
direct `subprocess.run()` can silently bypass the intended isolation model.

### 4. Module-level cached config/runtime paths increase patch surface

`runtime.config` exposes module-level path values such as `CONFIG_FILE`,
`RUNTIME_DB_FILE`, and `DAEMON_STATUS_FILE`, and several modules cache or
re-export those values. Tests compensate with broad monkeypatching, but the
design makes isolation enforcement harder than it should be.

### 5. The suite lacks a strong general guard against live-user state

Current tests prove some isolated paths and some fail-closed temp-root cases,
but there is not yet a fortress-style assertion layer that makes it obvious
when a test resolves to the machine-local config dir or a live user brain.

## Product Decisions Confirmed For This Plan

The following decisions are confirmed and should be treated as settled unless a
later review artifact finds a material conflict.

### 1. Product code must fail closed even when test harness isolation is missed

The runtime safety rule cannot depend only on tests setting `BRAIN_SYNC_CONFIG_DIR`
correctly. Brain-scoped product writes must carry enough context to reject
unsafe routing themselves.

### 2. Brain-scoped operational events are root-aware runtime writes

Operational events that describe one brain's source, watcher, reconcile,
query-index, or regen activity belong to the same root-aware runtime routing
discipline as other brain-scoped runtime tables.

### 3. Truly machine-local telemetry may remain config-dir scoped

This plan should not silently broaden into redesigning every config-dir-scoped
runtime table. If some telemetry is intentionally machine-local, that policy
should stay explicit and separate from brain-scoped operational events.

### 4. Test isolation must be centralized enough to resist drift

The repository should expose one shared test-isolation model for config dir,
runtime DB, daemon state, home directory, and active brain root setup.
Individual suites may extend it, but they should not re-invent it casually.

### 5. Tests must never use a user's live brain or runtime by default

Any test that intentionally simulates machine-local runtime behavior must do so
through explicit safety tests with temporary fake home/config locations. Normal
tests must not read or write a real user brain checkout, real `~/.brain-sync`,
or machine-local daemon/log/token state.

## Scope

In scope for the implementation stage:

- replace the current brain-scoped operational-event write path with explicit
  root-aware routing
- update all brain-scoped operational-event callers to pass `root`
- preserve or improve the current temp-root safety rules in
  `src/brain_sync/runtime/paths.py`
- audit config and root resolution paths for test-isolation brittleness
- centralize test fixture and subprocess isolation helpers
- add regression coverage proving that tests cannot touch live runtime or live
  brain state through the known leak paths
- tighten or add suite-level safety assertions where they materially reduce
  drift

## Non-goals

- no deletion or cleanup of an existing machine-local runtime DB as part of
  this plan
- no broad redesign of token telemetry unless later review decides that
  machine-local token tracking policy itself must change
- no portable brain contract/version change unless later review proves one is
  required
- no unrelated test-framework rewrite beyond the isolation and drift-reduction
  work needed here
- no reliance on review-time human memory of "the right env vars" as the main
  safety mechanism

## Workstreams

### Workstream 1: Root-Aware Operational Event Enforcement

Goals:

- make brain-scoped operational-event writes require the active brain root
- route those writes through `_connect(root)` rather than a rootless runtime
  helper
- fail closed when a temp/test brain would otherwise write into machine-local
  runtime

Implementation requirements:

- introduce an explicit root-aware operational-event API in
  `src/brain_sync/runtime/repository.py`
- decide the future role of the current rootless `record_operational_event()`
  path:
  - remove it
  - narrow it to explicitly machine-local telemetry only
  - or rename it so misuse is harder
- keep non-fatal event logging semantics only where they do not weaken the
  fail-closed safety rule
- ensure runtime helper functions that already accept `root` do not write
  events through a rootless path

Primary modules:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/runtime/paths.py`

### Workstream 2: Caller Sweep For Brain-Scoped Event Writes

Goals:

- eliminate every brain-scoped caller that currently relies on ambient config
  discovery for operational events
- make event routing consistent across application, sync, regen, and runtime
  helper seams

Implementation requirements:

- audit and update operational-event callers in:
  - application helpers
  - sync lifecycle/finalization/reconcile
  - regen engine and queue
  - runtime helper functions
- preserve current event semantics, fields, and event-type catalog unless a
  later review requires a bounded cleanup
- ensure no caller is forced back to config-discovered root resolution if it
  already has `root`

Primary modules:

- `src/brain_sync/application/query_index.py`
- `src/brain_sync/application/local_files.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/sync/lifecycle.py`
- `src/brain_sync/sync/finalization.py`
- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`

### Workstream 3: Centralized Test Isolation Substrate

Goals:

- provide one shared and discoverable test isolation mechanism
- reduce the number of duplicated env builders and monkeypatch lists
- make new tests harder to write unsafely by accident

Implementation requirements:

- add a shared test helper or fixture layer that owns:
  - isolated config dir creation
  - isolated home-directory environment
  - runtime DB and daemon-status path wiring
  - active brain-root registration when config-discovered root resolution is
    used
- migrate `tests/conftest.py`, system helpers, E2E helpers, and MCP stdio setup
  toward that shared substrate
- reduce ad hoc subprocess env construction where practical
- keep xdist safety and per-test isolation intact

Primary modules:

- `tests/conftest.py`
- `tests/system/conftest.py`
- `tests/e2e/conftest.py`
- `tests/e2e/harness/cli.py`
- `tests/e2e/harness/daemon.py`
- `tests/mcp/test_mcp_stdio.py`

### Workstream 4: Runtime/Config Path Hardening For Testability

Goals:

- shrink the monkeypatch surface needed for safe isolation
- reduce dependence on import-time cached config/runtime path values where that
  caching makes test safety brittle

Implementation requirements:

- audit `src/brain_sync/runtime/config.py` and downstream imports for places
  where module-level cached path values make tests patch too many seams
- prefer central dynamic accessors where that meaningfully improves isolation
  without destabilizing the product contract
- keep compatibility implications explicit if any public surface changes
- ensure root resolution through `application/roots.py` remains safe under test
  harness control

Primary modules:

- `src/brain_sync/runtime/config.py`
- `src/brain_sync/application/roots.py`
- any downstream modules that directly cache path constants in a way that
  materially weakens test isolation

### Workstream 5: Fortress Regression Coverage

Goals:

- prove the known operational-event leak cannot recur
- prove tests do not silently resolve to live config/runtime/brain paths
- catch future fixture drift early

Implementation requirements:

- extend runtime safety tests to cover:
  - temp brain root plus machine-local runtime env plus non-temp cwd
  - no-session and no-owner operational-event writes
  - subprocess command-style event emission
- update operational-event tests so they validate the root-aware API rather
  than implicitly relying on shared config-dir state
- add a suite-level or fixture-level assertion that normal tests are not using
  the machine-local config dir, with narrow opt-outs only for explicit safety
  simulations
- add at least one subprocess proof for system or MCP-style execution

Primary tests:

- `tests/unit/test_runtime_safety.py`
- `tests/unit/test_runtime_operational_events.py`
- `tests/unit/test_sync_events.py`
- relevant system/E2E/MCP tests that exercise subprocess routing

## Acceptance Criteria

The implementation derived from this plan should not be considered complete
unless it demonstrates at least the following:

1. Brain-scoped operational-event writes require an explicit brain root and do
   not route through a rootless runtime connection.
2. A temp or test brain root cannot append operational events into the
   machine-local runtime DB when the config dir is not isolated.
3. The known command-style leak pattern still fails closed when `session_id`
   and `owner_id` are both absent.
4. All current brain-scoped operational-event callers have been updated to use
   the root-aware routing seam.
5. The repository has one centralized test-isolation substrate that is reused
   by in-process tests and subprocess harnesses where practical.
6. Normal tests cannot resolve to a real machine-local config dir or a live
   user brain by default.
7. Tests that intentionally simulate machine-local runtime behavior do so only
   against temporary fake homes/config dirs and still never touch a user's real
   machine-local state.
8. Existing temp-root safety guarantees in `src/brain_sync/runtime/paths.py`
   are preserved or strengthened.
9. Regression tests prove the operational-event leak cannot recur through unit
   and subprocess-style paths.
10. The resulting fixture/test structure is less drift-prone than the current
    mix of duplicated env builders and ad hoc monkeypatch lists.

## Test Fortress Expectations

The implementation and review must land proof at these levels.

### Unit

- root-aware operational-event API tests
- temp-root fail-closed tests for event writes
- tests proving rootless operational-event usage is either forbidden or tightly
  bounded to explicitly machine-local telemetry
- fixture-guard tests that fail if the suite resolves to machine-local config
  unexpectedly

### Integration

- source lifecycle and query-index event tests proving the updated root-aware
  event seam still records expected events into the isolated runtime DB
- tests proving config-discovered root resolution under fixtures does not touch
  a live user brain

### System

- subprocess tests proving CLI commands run under isolated config/home wiring
- at least one regression proving command-style event emission cannot leak into
  machine-local runtime when isolation is missed

### MCP / E2E

- stdio or daemon subprocess coverage proving the shared isolation substrate is
  reused or faithfully mirrored
- overlap tests confirming daemon- or helper-launched subprocesses still stay
  within the isolated runtime/config directory

## Proposed Sequencing

1. Implement the product enforcement seam for operational events first.
2. Sweep all brain-scoped callers to pass `root` explicitly.
3. Harden runtime/config path lookup where cached globals make isolation
   brittle.
4. Introduce the centralized test-isolation substrate and migrate the existing
   harnesses and fixtures onto it.
5. Add the new regression and fortress tests.
6. Run targeted validation first, then expand to the broader affected suite
   slices.

## Risks And Review Focus

Reviewers should pay particular attention to:

- whether the new operational-event API truly closes the root-routing hole
  rather than only changing a subset of callers
- whether any remaining rootless runtime write path can still be misused by
  brain-scoped code
- whether dynamic config-path hardening accidentally changes intended
  machine-local telemetry behavior
- whether the centralized test substrate really reduces drift instead of merely
  moving duplicated logic into a new file
- whether the new safety assertions are precise enough to catch live-user state
  access without making legitimate safety tests impossible to write

## Exit Criteria

This plan should be considered ready for approval only when a reviewer can
confirm that it:

- treats the operational-event leak as a product-path safety bug rather than a
  tests-only harness mistake
- centralizes test isolation strongly enough to reduce future drift
- keeps the distinction between brain-scoped runtime writes and intentionally
  machine-local telemetry explicit
- defines acceptance criteria that prove tests cannot touch a user's live
  brain, runtime DB, or daemon state by default
- preserves the append-only planning workflow and leaves later implementation
  with clear sequencing and reviewable proof targets

If review feedback identifies issues, the planner should create a revised plan
artifact rather than editing this file in place.

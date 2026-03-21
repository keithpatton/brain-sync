# PLAN_test-isolation-hardening Revision 3: Phased Isolation Hardening With Early Leak Repro Closure

## Status

Planning artifact only. This revision supersedes revision 2 for execution
planning purposes and strengthens the plan where review found proof and
anti-drift gaps.

This stage does **not** approve implementation. It records the revised phased
execution model for later review and approval.

## Relationship To Prior Artifacts

This revision refines:

- `docs/plans/PLAN_test-isolation-hardening.md`
- `docs/plans/plan_test-isolation-hardening_2_2026-03-22.md`
- `docs/plans/plan_test-isolation-hardening_2_review_1_2026-03-22.md`

The root plan remains the canonical origin artifact. This revision exists to
resolve the review findings that:

1. proof of the actual no-session command-style leak still landed too late
2. the caller-sweep phase relied on a one-time grep rather than a durable
   anti-drift guard
3. subprocess/env centralization did not yet explicitly cover all current
   bespoke launch paths

## Objective

Keep the same overall objective while making the proof and drift-prevention
requirements stronger:

- tests must never use or write into a live user brain
- tests must never use or write into live machine-local runtime state
- the observed operational-event leak signature must be re-proved closed before
  later fixture phases begin
- test acquisition of config, runtime, and brain fixtures must be centralized
  enough to cover all current subprocess/env-construction paths
- the repository must gain a durable anti-drift guard so future brain-scoped
  code cannot silently reintroduce rootless operational-event writes

## Why This Revision Is Needed

Revision 2 improved phase shape, but it still allowed later phases to proceed
before the exact observed leak signature had been re-proved closed, and it left
two important drift surfaces too weakly controlled:

- caller reintroduction of rootless brain-scoped operational-event writes
- bespoke subprocess/env builders outside the shared fixture model

This revision tightens those weak points without abandoning the phased
structure.

## Authoritative Inputs

This revision inherits the authoritative inputs from the root plan and revision
2. Primary constraints remain:

- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/plans/PLAN_test-isolation-hardening.md`
- `docs/plans/plan_test-isolation-hardening_2_review_1_2026-03-22.md`

The implementation and review must also align with the current affected seams,
including the subprocess paths called out in review:

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
- `tests/system/test_cli_commands.py`
- `tests/e2e/test_db_contention.py`
- `tests/unit/test_runtime_safety.py`
- `tests/unit/test_runtime_operational_events.py`
- `tests/unit/test_sync_events.py`

## Confirmed Design Decisions

### 1. The known leak signature must be closed in Phase 1, not deferred

The exact observed failure shape is a product-path requirement, not a final
fortress-only regression. Phase 1 must prove that a brain-scoped
operational-event write fails closed even when:

- the root is temp or test-shaped
- runtime config resolves to a machine-local-style location
- `session_id` is absent
- `owner_id` is absent
- the call comes through a command-style or subprocess-shaped path

### 2. Manual caller audit is insufficient as the lasting guard

A one-time grep is useful during implementation, but it is not enough as the
repository's durable prevention mechanism. The final design must include a
stronger anti-drift guard.

### 3. Every current subprocess/env builder must be accounted for explicitly

The shared isolation substrate is not complete unless it covers all current
subprocess/env-construction paths, including test-local launchers. Any
exception must be deliberate, documented, and guarded.

### 4. Product enforcement still comes before fixture centralization

The operational-event leak remains the first thing to close. Fixture and helper
cleanup must not be allowed to mask whether the product enforcement seam itself
is correct.

## Phased Execution Plan

### Phase 1: Product Enforcement Seam And Direct Leak Reproducer Closure

Goals:

- introduce the root-aware operational-event write seam
- preserve or strengthen temp-root fail-closed enforcement
- close the exact observed no-session command-style leak before later phases
  begin
- keep machine-local telemetry policy explicit

Required changes:

- update `src/brain_sync/runtime/repository.py`
- update `src/brain_sync/runtime/paths.py` only as needed to preserve or
  strengthen safety guarantees
- define the allowed role of any remaining rootless event API
- add direct regressions for the observed leak signature now, not later

Validation gate:

- targeted unit tests for runtime safety and operational-event routing pass
- a direct reproducer proves that a temp or test root cannot append
  brain-scoped operational events into machine-local runtime
- that proof includes the no-session/no-owner case
- at least one command-style or subprocess-shaped path proves the same
  enforcement seam before caller migration or fixture centralization starts
- no remaining modified product-path brain-scoped event write goes through the
  unsafe rootless seam

Checkpoint review focus:

- did the new seam actually close the observed leak signature
- does the no-session/no-owner command-style case fail closed
- is the subprocess-shaped proof exercising the product seam rather than only a
  fixture patch
- is machine-local telemetry policy still explicit

### Phase 2: Brain-Scoped Caller Migration And Durable Anti-Drift Guard

Goals:

- migrate all known brain-scoped operational-event callers to pass `root`
- ensure runtime helpers that already accept `root` no longer discard it before
  writing events
- add a durable anti-drift guard so future callers cannot silently reintroduce
  the unsafe pattern

Required changes:

- caller sweep across application, sync, regen, and runtime helpers
- define an explicit source-of-truth policy for any remaining rootless event
  API:
  - removed entirely
  - narrowed to an explicitly machine-local helper with a hostile or
    self-limiting signature/name
  - or protected by an automated allowlist proving it is used only in approved
    machine-local telemetry contexts
- add automated proof stronger than "someone grepped it"

Validation gate:

- unit and integration tests covering event emission still pass
- automated proof exists that brain-scoped code cannot use the rootless event
  path without tripping a repository guard
- any remaining rootless event entrypoint is provably restricted to explicitly
  machine-local telemetry or removed
- caller migration is checked against an explicit inventory of current caller
  sites, not only an ad hoc grep during review

Checkpoint review focus:

- completeness of the caller sweep
- strength of the anti-drift mechanism
- whether the rootless API is truly unavailable or tightly bounded
- preservation of event semantics and event types

### Phase 3: Centralized Test Isolation Substrate With Full Subprocess Inventory

Goals:

- centralize isolated config/home/runtime/brain fixture acquisition
- reduce duplicated env builders and monkeypatch drift
- make safe subprocess setup the default path
- account for every current subprocess/env-construction path explicitly

Required changes:

- shared helper/fixture substrate for:
  - config dir
  - home env
  - runtime DB and daemon files
  - active brain-root config registration
- explicit inventory of current subprocess/env-construction paths, including:
  - reusable helper modules
  - test-local launchers such as `tests/system/test_cli_commands.py`
  - bespoke launchers such as `tests/e2e/test_db_contention.py`
- for each inventoried subprocess/env path, require one of:
  - migration onto the shared substrate
  - retention as a documented exception with an explicit guard and reason
  - replacement with a shared wrapper that preserves the special behavior
- add a durable validation rule that rejects or flags new ad hoc subprocess env
  builders outside the approved exceptions

Validation gate:

- affected unit, system, MCP, and E2E tests pass with the new shared setup
- every current subprocess/env-construction path is either migrated or
  explicitly documented as an approved exception with guard coverage
- no bespoke subprocess path remains by accident or omission

Checkpoint review focus:

- completeness of the subprocess/env inventory
- whether the shared substrate actually replaced duplication
- whether approved exceptions are narrow, justified, and guarded
- whether xdist safety and per-test isolation remain intact

### Phase 4: Runtime/Config Lookup Hardening

Goals:

- reduce reliance on cached module-level runtime/config paths where that
  increases test patch surface
- make test isolation less dependent on patching many module globals

Required changes:

- targeted refactors in runtime/config path access and downstream consumers
- compatibility-aware handling of any public or semipublic surface change

Validation gate:

- the central isolation substrate can set up test-safe paths with fewer
  special-case monkeypatches
- targeted tests for config-discovered root resolution and runtime path usage
  pass

Checkpoint review focus:

- whether the refactor meaningfully reduces brittleness
- whether any intended config-dir-scoped behavior was changed accidentally

### Phase 5: Fortress Regressions And Suite Safety Guards

Goals:

- prove the wider leak family cannot recur
- prove tests cannot silently use live-user state
- add guardrails that catch future drift early beyond the known leak signature

Required changes:

- extend runtime safety and operational-event tests beyond the Phase 1 direct
  reproducer
- add broader subprocess and suite-guard coverage
- add fixture or suite-level assertions for machine-local config misuse with
  narrow opt-outs for explicit safety simulations

Validation gate:

- targeted unit, system, MCP, and E2E regressions pass
- the new guards fail when isolation is intentionally broken in a controlled
  test
- the final suite proves both the known leak signature and the broader
  anti-drift boundaries

Checkpoint review focus:

- proof strength rather than just green happy-path tests
- whether the new guards are precise enough to be trusted long-term

## Phase Exit Rules

A phase is complete only when all of the following are true:

1. The scoped code changes for that phase are landed locally.
2. The phase validation gate has been run successfully.
3. The checkpoint review confirms the phase met its proof obligations rather
   than only improving nearby infrastructure.
4. Any material execution-relevant deviation is recorded later in the
   implementation notes for the approved plan.

If a phase reveals a missing design choice, contradictory rule, or broader
scope boundary than this plan anticipates, execution should stop and return to
planning rather than improvising a larger redesign mid-flight.

## Recommended Test And Review Cadence

The implementation stage should use this cadence:

1. After Phase 1:
   - run targeted unit safety tests
   - run the direct no-session leak reproducer
   - run the command-style or subprocess-shaped reproducer
   - review the enforcement seam before caller migration
2. After Phase 2:
   - run event-emission unit and integration tests
   - run the anti-drift proof for rootless-event misuse
   - review caller completeness and the lasting guard
3. After Phase 3:
   - run system, MCP, and E2E slices that depend on subprocess isolation
   - review the subprocess/env inventory and all remaining exceptions
4. After Phase 4:
   - run targeted config/runtime resolution tests
   - review compatibility and machine-local telemetry boundaries
5. After Phase 5:
   - run the full affected slice matrix
   - perform the final implementation review against the approved artifact

## Acceptance Criteria

This revision keeps the root-plan acceptance criteria and strengthens them with
execution-shape requirements:

1. The work is implemented in bounded phases rather than as one undifferentiated
   pass.
2. Each phase has a defined validation gate and a review/checkpoint before the
   next phase begins.
3. Phase 1 proves the exact observed leak signature is closed before later
   phases begin.
4. Phase 2 includes a durable anti-drift mechanism stronger than a one-time
   manual grep.
5. Phase 3 explicitly inventories and resolves all current subprocess/env
   launch paths, including test-local bespoke launchers.
6. The final state still satisfies all acceptance criteria in
   `docs/plans/PLAN_test-isolation-hardening.md`.

## Review Focus

The first review pass for the revision derived from this artifact should focus
especially on:

- whether Phase 1 now proves the actual no-session command-style leak is closed
- whether the Phase 2 anti-drift requirement is strong enough to matter after
  the implementing agent is gone
- whether Phase 3 is now broad enough to cover all current subprocess/env
  launch seams
- whether the stronger proof obligations remain practical to implement

## Exit Criteria

This revision should be considered ready for approval only when a reviewer can
confirm that it:

- resolves the three blocking findings from
  `plan_test-isolation-hardening_2_review_1_2026-03-22.md`
- keeps the root plan's safety objectives intact
- gives the implementer clear, practical phase gates with strong proof
  expectations
- reduces both the known leak risk and the future drift risk

If review feedback identifies issues, the planner should create a later plan
revision rather than editing this file in place.

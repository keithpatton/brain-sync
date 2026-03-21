# PLAN_test-isolation-hardening Revision 2: Phased Test Isolation And Operational Event Hardening

## Status

Planning artifact only. This revision supersedes the canonical root plan for
execution planning purposes and adds explicit phased sequencing, validation
gates, and review checkpoints between workstreams.

This stage does **not** approve implementation. It records the preferred
phased execution model for later review and approval.

## Relationship To Prior Plan

This revision refines:

- `docs/plans/PLAN_test-isolation-hardening.md`

The root plan remains the canonical starting artifact. This revision exists
because the implementation should be staged with proof and review checkpoints
between phases rather than executed as one uninterrupted sweep.

## Objective

Preserve the same objective as the root plan while making the implementation
sequence safer:

- tests must never use or write into a live user brain
- tests must never use or write into live machine-local runtime state
- brain-scoped operational-event writes must fail closed when isolation is
  missed
- test acquisition of config, runtime, and brain fixtures should be
  centralized enough to resist drift

## Why Phased Execution Is Required

This plan should be executed in phases because the work spans:

- product-path safety enforcement
- broad caller updates across multiple subsystems
- fixture and harness centralization
- regression-proof expansion across unit, integration, system, MCP, and E2E

Doing all of that in one pass would make it too easy to:

- lose the exact root cause behind a larger fixture rewrite
- break a large test surface without knowing which hardening layer caused it
- ship a partial caller sweep that looks complete only because the old fixture
  patching still masks the defect
- weaken an already-correct subprocess isolation path while improving another

The implementation should therefore land in bounded phases with targeted tests
and a review/checkpoint between phases.

## Authoritative Inputs

This revision inherits the authoritative inputs from the root plan and adds one
execution rule:

- each phase must complete its own validation gate before the next phase begins

Primary constraints remain:

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

## Confirmed Design Decisions

### 1. Product enforcement comes before test-harness cleanup

The operational-event leak must be closed in product code first. Test
centralization is necessary, but it must not be used as a substitute for the
product safety seam.

### 2. Later phases must build on proof from earlier phases

Caller migration should not start until the new root-aware event seam is
implemented and proven. Test harness centralization should not start until the
product routing rule is stable enough to test against.

### 3. Reviews and checks should happen between phases, not only at the end

Each phase should end with:

- targeted test runs
- a quick code review or self-review against the approved phase scope
- a decision to continue, adjust, or return to planning

### 4. The test-harness pass should reduce masking behavior

The current fixture system sometimes hides product-path mistakes by forcing many
modules onto the same temp config dir. The phased execution should move toward
stronger explicit guarantees, not just broader patching.

## Phased Execution Plan

### Phase 1: Product Enforcement Seam

Goals:

- introduce the root-aware operational-event write seam
- preserve or strengthen temp-root fail-closed enforcement
- clearly separate brain-scoped operational events from intentionally
  config-dir-scoped telemetry

Required changes:

- update `src/brain_sync/runtime/repository.py`
- update `src/brain_sync/runtime/paths.py` only as needed to preserve or
  strengthen safety guarantees
- define the allowed role of any remaining rootless event API

Validation gate:

- targeted unit tests for runtime safety and operational-event routing pass
- no remaining product-path brain-scoped event write goes through the unsafe
  rootless seam in the modified code

Checkpoint review focus:

- did the new seam actually close the leak, or did it only rename the old path
- is fail-closed behavior preserved for temp roots
- is machine-local telemetry policy still explicit

### Phase 2: Brain-Scoped Caller Migration

Goals:

- migrate all known brain-scoped operational-event callers to pass `root`
- ensure runtime helpers that already accept `root` no longer discard it before
  writing events

Required changes:

- caller sweep across application, sync, regen, and runtime helpers

Validation gate:

- unit and integration tests covering event emission still pass
- grep/audit confirms no remaining brain-scoped caller uses the unsafe rootless
  event path

Checkpoint review focus:

- completeness of the caller sweep
- preservation of event semantics and event types
- absence of accidental fallback to config-discovered root resolution

### Phase 3: Test Isolation Substrate Centralization

Goals:

- centralize isolated config/home/runtime/brain fixture acquisition
- reduce duplicated env builders and monkeypatch drift
- make safe subprocess setup the default path

Required changes:

- shared helper/fixture substrate for:
  - config dir
  - home env
  - runtime DB and daemon files
  - active brain-root config registration
- migration of in-process, system, E2E, and MCP helpers toward that substrate

Validation gate:

- affected unit/system/E2E/MCP tests pass with the new shared setup
- no helper still needs bespoke isolation logic unless there is a documented
  reason

Checkpoint review focus:

- whether the new substrate actually replaces duplication
- whether subprocess helpers now share one trustworthy env model
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

- prove the leak cannot recur
- prove tests cannot silently use live-user state
- add guardrails that catch future drift early

Required changes:

- extend runtime safety and operational-event tests
- add subprocess/no-session coverage
- add fixture or suite-level assertions for machine-local config misuse with
  narrow opt-outs for explicit safety simulations

Validation gate:

- targeted unit, system, MCP, and E2E regressions pass
- the new guards fail when isolation is intentionally broken in a controlled
  test

Checkpoint review focus:

- proof strength rather than just happy-path green tests
- whether the new guards are precise enough to be trusted long-term

## Phase Exit Rules

A phase is complete only when all of the following are true:

1. The scoped code changes for that phase are landed locally.
2. The phase validation gate has been run successfully.
3. A brief review or self-review confirms the phase did not quietly broaden
   scope or weaken the safety model.
4. Any material execution-relevant deviation is recorded later in the
   implementation notes for the approved plan.

If a phase reveals a missing design choice, contradictory rule, or broader
scope boundary than this plan anticipates, execution should stop and return to
planning rather than improvising a larger redesign mid-flight.

## Recommended Test And Review Cadence

The implementation stage should use this cadence:

1. After Phase 1:
   - run targeted unit safety tests
   - perform a focused review of the enforcement seam before caller migration
2. After Phase 2:
   - run event-emission unit and integration tests
   - perform a caller-completeness audit before touching fixtures
3. After Phase 3:
   - run system, MCP, and E2E slices that depend on subprocess isolation
   - review the shared substrate for drift reduction and helper consistency
4. After Phase 4:
   - run targeted config/runtime resolution tests
   - review compatibility and machine-local telemetry boundaries
5. After Phase 5:
   - run the full affected slice matrix
   - perform the final implementation review against the approved artifact

## Acceptance Criteria

This revision keeps the root-plan acceptance criteria and adds execution-shape
requirements:

1. The work is implemented in bounded phases rather than as one undifferentiated
   pass.
2. Each phase has a defined validation gate and a review/checkpoint before the
   next phase begins.
3. Product enforcement for operational events is completed and verified before
   test-harness centralization begins.
4. The final state still satisfies all acceptance criteria in
   `docs/plans/PLAN_test-isolation-hardening.md`.

## Review Focus

The first review pass for the revision derived from this artifact should focus
especially on:

- whether the phase boundaries are correct and practical
- whether the validation gates are strong enough to catch partial or masked
  fixes
- whether the sequencing prevents the fixture refactor from obscuring the core
  product-path bug
- whether the plan still keeps implementation momentum without turning every
  small change into a new planning round

## Exit Criteria

This revision should be considered ready for approval only when a reviewer can
confirm that it:

- keeps the root plan's safety objectives intact
- adds practical phased execution rather than ceremonial checkpoints
- gives the implementer clear stop-and-review boundaries
- improves the odds of finding residual isolation leaks before the final phase

If review feedback identifies issues, the planner should create a later plan
revision rather than editing this file in place.

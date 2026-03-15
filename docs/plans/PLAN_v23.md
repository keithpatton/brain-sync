# PLAN_v23: Brain Format 1.0 / Runtime v23 Refactor

## Status

Planning artifact only. This document defines the implementation plan for
aligning the codebase to the authoritative Brain Format `1.0` and runtime DB
schema `v23` documents under `docs/brain-format/`.

This stage does **not** change product behavior. It records what the later
implementation stage must do and what the acceptance gates will be.

## Objective

Refactor the codebase so the supported baseline is exactly:

- app version `0.5.0`
- Brain Format `1.0`
- runtime DB schema `v23`

The implementation must follow the `docs/brain-format/` spec set when current
code conflicts with it. Pre-v23 layouts are unsupported legacy inputs for this
release and must not be treated as supported durable layouts.

## Authoritative inputs

The implementation must treat these documents as the source of truth:

- `docs/brain-format/RULES.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/brain-format/VERSIONING.md`
- `docs/brain-format/COMPATIBILITY.md`
- `docs/brain-format/GLOSSARY.md`
- `docs/brain-format/TEMPLATES.md`

`docs/plans/plan_v23_supporting.md` is useful background, but the spec set
above is authoritative for behavior and acceptance.

## Scope

In scope for the implementation stage:

- filesystem contract alignment to Brain Format `1.0`
- source manifest schema and identity rule alignment
- materialization/frontmatter rule alignment
- co-located per-area `.brain-sync/` managed-state layout
- runtime DB relocation and schema reset to `v23`
- watcher, reconciliation, doctor, MCP, and query/path updates caused by the
  new layout and version contract
- test-harness and compatibility-suite work needed to prove the single
  supported baseline

## Non-goals

- no product code changes during this planning stage
- no migration or upgrade path from pre-v23 brains
- no attempt to preserve v21 durable layouts as supported inputs
- no new feature work beyond spec alignment
- no dependency on `brain-example/` as a test-fixture source

## Fixed decisions from the spec

These are not open design questions for implementation:

- root durable manifest is `.brain-sync/brain.json` with `{"version": 1}`
- source manifests live at `.brain-sync/sources/<source_dir_id>.json`
- durable manifest version field name is `version`, not `manifest_version`
- durable manifest/frontmatter identity writes use spec-aligned values and YAML
  `brain_sync_*` frontmatter keys
- HTML comment identity markers remain read fallback only where needed
- runtime DB lives at `~/.brain-sync/db/brain-sync.sqlite`
- daemon status lives at `~/.brain-sync/daemon.json`
- per-area managed state is co-located under `knowledge/<area>/.brain-sync/`
- the root area is valid and uses `knowledge/.brain-sync/...`
- `.brain-sync/` is the single reserved managed namespace and must be excluded
  consistently from readable-content discovery, hashing, regen, and query
  assembly
- the runtime DB schema constant should be `23` to correspond to schema label
  `v23`

## Planning outcomes required in implementation

Before broad behavior rewrites, the implementation stage should establish:

1. Shared path/version helpers so layout and version rewrites are centralized.
2. Version-aware test builders and assertions so the suite stops encoding v21
   assumptions implicitly.
3. A dedicated `tests/compat/` suite for format/runtime compatibility
   contracts.

These three items are the foundation for the rest of the refactor.

## Workstreams

The implementation should be organized into five phases.

### Phase 0: Planning artifact and test foundation

Goals:

- land this planning document
- centralize path/version decisions before feature rewrites
- prepare the test harness for explicit Brain Format `1.0` coverage

Required outputs:

- shared helpers for brain-root paths, per-area managed paths, runtime DB path,
  daemon path, and version constants
- version-aware builders such as:
  - `build_brain_v1(...)`
  - `build_drifted_brain_v1(...)`
  - `build_legacy_pre_v1_brain(...)`
- shared assertions such as:
  - `assert_brain_format_v1(...)`
  - `assert_runtime_rebuildable(...)`
  - `assert_unsupported_legacy_brain(...)`
- initial `tests/compat/` skeleton for the supported row

Primary modules:

- `tests/e2e/harness/brain.py`
- `tests/e2e/harness/assertions.py`
- `tests/compat/*`

### Phase 1: Runtime baseline and init contract

Goals:

- move runtime ownership out of the brain root
- establish the Brain Format `1.0` init baseline
- remove v21 runtime/layout assumptions from bootstrap paths

Implementation requirements:

- move DB ownership to `config.py` and resolve DB path as
  `~/.brain-sync/db/brain-sync.sqlite`
- replace brain-root `.sync-state.sqlite` usage entirely
- replace DB `daemon_status` usage with `~/.brain-sync/daemon.json`
- ensure `brain-sync init` creates only:
  - `.brain-sync/brain.json`
  - `.brain-sync/sources/`
  - `knowledge/`
  - `knowledge/_core/`
- ensure `brain-sync init` does **not** create:
  - `insights/`
  - `schemas/`
  - `.sync-state.sqlite`
  - `.gitignore`
  - `knowledge/.brain-sync/`

Primary modules:

- `src/brain_sync/config.py`
- `src/brain_sync/state.py`
- `src/brain_sync/commands/init.py`
- `src/brain_sync/__main__.py`
- `pyproject.toml`

### Phase 2: Manifest and identity contract

Goals:

- align durable manifests and materialized-file identity with the v23 spec
- remove persisted operational flags from durable state

Implementation requirements:

- refactor source manifests to use:
  - `version`
  - filename `<source_dir_id>.json`
  - no persisted `fetch_children`
  - no persisted `child_path`
- keep read tolerance only where needed for otherwise supported brains
- write synced-file identity using YAML frontmatter with:
  - `brain_sync_source`
  - `brain_sync_canonical_id`
  - `brain_sync_source_url`
- preserve HTML comment parsing only as a read fallback where required
- align durable `source_type` and frontmatter values to the spec
- validate manifest filename identity and repair drift through doctor

Primary modules:

- `src/brain_sync/manifest.py`
- `src/brain_sync/commands/sources.py`
- `src/brain_sync/pipeline.py`
- `src/brain_sync/fileops.py`
- `src/brain_sync/sources/__init__.py`

### Phase 3: Co-located managed state and regen layout

Goals:

- move managed per-area state into the co-located `.brain-sync/` layout
- internalize template loading and standardize managed-namespace exclusion

Implementation requirements:

- move summaries, insight state, journals, and attachments under
  `knowledge/<area>/.brain-sync/`
- support the root area at `knowledge/.brain-sync/...`
- update regen, sidecar handling, child-summary lookup, attachment writes,
  area indexing, and path consumers to the new layout
- internalize template loading so no templates are deployed into the brain
  root
- enforce one shared `.brain-sync/` exclusion policy reused by discovery,
  hashing, regen, reconcile, watcher, and query assembly

Primary modules:

- `src/brain_sync/sidecar.py`
- `src/brain_sync/regen.py`
- `src/brain_sync/regen_lifecycle.py`
- `src/brain_sync/attachments.py`
- `src/brain_sync/fs_utils.py`
- `src/brain_sync/area_index.py`
- `src/brain_sync/mcp.py`

### Phase 4: Watcher, reconciliation, and doctor

Goals:

- rebase filesystem maintenance on v23 filesystem authority rules
- reject unsupported legacy layouts clearly instead of preserving them

Implementation requirements:

- remove mirror-move behavior tied to the old top-level `insights/` tree
- make folder moves update manifests and runtime state while co-located
  managed files move automatically with the folder
- rewrite reconciliation around filesystem authority and the three-tier
  identity resolution chain
- rewrite doctor checks for the Brain Format `1.0` contract
- make doctor repair scope match the spec:
  - may recreate runtime artifacts and missing managed files
  - must not upgrade legacy brains
  - must not delete user knowledge
  - must not delete journals

Primary modules:

- `src/brain_sync/reconcile.py`
- `src/brain_sync/watcher.py`
- `src/brain_sync/commands/doctor.py`
- `src/brain_sync/area_index.py`
- `src/brain_sync/mcp.py`

### Phase 5: Compatibility closeout

Goals:

- prove the single supported compatibility row
- remove remaining v21-only assumptions from tests and fixtures

Implementation requirements:

- add compatibility tests for:
  - app `0.5.0`
  - Brain Format `1.0`
  - runtime DB schema `v23`
- remove or rewrite v21-only tests and fixtures
- verify runtime rebuild behavior
- verify unsupported-legacy detection and re-init guidance

Primary modules:

- `tests/unit/test_state.py`
- `tests/unit/test_manifest.py`
- `tests/unit/test_phase0.py`
- `tests/unit/test_doctor.py`
- `tests/unit/test_regen.py`
- `tests/unit/test_watcher_moves.py`
- `tests/integration/test_legacy_fallback.py`
- `tests/e2e/test_fs_moves.py`
- `tests/e2e/test_offline_reconcile.py`
- `tests/compat/*`

## Dependency order

Must happen first:

- planning document
- shared path/version decisions
- test-harness foundation
- compatibility test skeleton

Then execute in this order:

1. runtime/init/version baseline
2. manifest/frontmatter contract
3. co-located managed-state layout
4. watcher/reconcile/doctor
5. compatibility closeout and full test rewrite

Can proceed in parallel after the foundation is in place:

- runtime/init/state work
- manifest/frontmatter/source-command work
- regen/layout/attachments work

Should wait until path/layout is stable:

- MCP and area-index final rewrites
- final doctor wording and compatibility assertions

## Cross-cutting implementation rules

- follow the spec docs when current code disagrees
- do not preserve unsupported legacy layouts as supported inputs
- do not add migration flows for pre-v23 brains in this release
- treat the filesystem as authoritative and runtime state as rebuildable
- centralize path/version logic rather than repeating literals across
  modules and tests
- use shared exclusion helpers so `.brain-sync/` is never treated as readable
  input
- keep builder-generated fixtures as the primary test strategy; do not depend
  on `brain-example/`

## Module impact by area

### Runtime, init, and versioning

- `src/brain_sync/config.py`
- `src/brain_sync/state.py`
- `src/brain_sync/commands/init.py`
- `src/brain_sync/__main__.py`
- `pyproject.toml`

### Source manifests, source commands, and materialization

- `src/brain_sync/manifest.py`
- `src/brain_sync/commands/sources.py`
- `src/brain_sync/pipeline.py`
- `src/brain_sync/fileops.py`
- `src/brain_sync/sources/__init__.py`

### Regen, area state, and attachments

- `src/brain_sync/sidecar.py`
- `src/brain_sync/regen.py`
- `src/brain_sync/regen_lifecycle.py`
- `src/brain_sync/attachments.py`
- `src/brain_sync/fs_utils.py`

### Reconciliation, watcher, doctor, and query surfaces

- `src/brain_sync/reconcile.py`
- `src/brain_sync/watcher.py`
- `src/brain_sync/commands/doctor.py`
- `src/brain_sync/area_index.py`
- `src/brain_sync/mcp.py`

### Test harness and suites

- `tests/e2e/harness/brain.py`
- `tests/e2e/harness/assertions.py`
- `tests/unit/test_state.py`
- `tests/unit/test_manifest.py`
- `tests/unit/test_phase0.py`
- `tests/unit/test_doctor.py`
- `tests/unit/test_regen.py`
- `tests/unit/test_watcher_moves.py`
- `tests/integration/test_legacy_fallback.py`
- `tests/e2e/test_fs_moves.py`
- `tests/e2e/test_offline_reconcile.py`
- `tests/compat/*`

## Test strategy

### Foundation work required early

- add version-aware builders:
  - `build_brain_v1(...)`
  - `build_drifted_brain_v1(...)`
  - `build_legacy_pre_v1_brain(...)`
- add compatibility assertions:
  - `assert_brain_format_v1(...)`
  - `assert_runtime_rebuildable(...)`
  - `assert_unsupported_legacy_brain(...)`

### Compatibility coverage required

- fresh init produces a conforming Brain Format `1.0` brain
- drifted supported-format brains can be repaired without loss of user
  knowledge
- runtime DB deletion and rebuild does not invalidate a valid brain
- unsupported pre-v23 layouts are detected and not silently treated as
  supported

### Feature-specific coverage required

- `brain.json` creation and repair
- source manifest filename validation
- YAML frontmatter merge behavior
- frontmatter read fallback for legacy HTML comments
- root-area summary and insight-state behavior
- watcher handling for file moves, folder moves, and deletes
- reconciliation path repair via three-tier identity resolution
- attachment lifecycle under `.brain-sync/attachments/<source_dir_id>/`
- doctor checks and fix behavior for the v23 contract
- MCP/query path updates for new summary locations

## Acceptance criteria

Implementation is complete when all of the following are true:

- `brain-sync 0.5.0` creates and operates on Brain Format `1.0` brains
  with runtime DB schema `v23`
- fresh init produces only the spec-approved baseline artifacts
- durable manifests and materialized-file identity match the v23 schema
  and frontmatter rules
- per-area managed state is co-located under `knowledge/**/.brain-sync/`
- runtime DB and daemon state are fully outside the brain root
- deleting runtime DB state does not invalidate a valid brain
- doctor validates supported brains, repairs repairable drift, and clearly
  rejects unsupported legacy layouts without attempting an upgrade
- compatibility tests prove the single supported row and pass without
  relying on `brain-example/`

## Risks and mitigations

- Risk: v21 assumptions are spread through code and tests.
  Mitigation: centralize new path helpers and rewrite high-churn test
  infrastructure first.

- Risk: `.brain-sync/` content is accidentally treated as readable input.
  Mitigation: enforce one exclusion rule reused by discovery, hashing, regen,
  reconcile, watcher, and tests.

- Risk: attachment logic still depends on removed DB tables.
  Mitigation: redesign attachment lifecycle around per-source filesystem
  isolation before deleting old assumptions.

- Risk: version drift between docs and code.
  Mitigation: treat app version, Brain Format version, and runtime DB schema
  labels as explicit acceptance criteria and test assertions.

- Risk: leftover migration logic silently preserves legacy layouts.
  Mitigation: remove active migration flows and add explicit unsupported-legacy
  tests and doctor messaging.

## Open questions to settle during implementation

- Should internal enum naming also be normalized to the spec's durable
  `google_doc` naming, or only durable/on-disk writes?
  Default: normalize durable values first, then adjust internal names only if
  it safely reduces drift.

- Should packaged template sources stay in `src/brain_sync/schemas/insights/`
  or move to a clearer package path?
  Default: keep the package location stable unless runtime loading becomes
  awkward.

- What exact CLI and doctor wording should be used for unsupported legacy
  brains?
  Default: instruct the user to re-initialize into a fresh Brain Format `1.0`
  brain.

## Suggested parallel split for implementation

- Agent 1: runtime/init/state/versioning and compatibility metadata
- Agent 2: manifests, source commands, provider/type alignment, and
  frontmatter/materialization
- Agent 3: regen, insight-state paths, attachments, exclusion rules,
  area index, and MCP path consumers
- Agent 4: watcher, reconciliation, doctor, and compatibility-suite/test
  harness rewrites

Shared guidance for all agents:

- follow the brain-format docs, not current code, when they conflict
- do not preserve unsupported legacy layouts
- land test foundation early
- treat compatibility tests as the final acceptance gate

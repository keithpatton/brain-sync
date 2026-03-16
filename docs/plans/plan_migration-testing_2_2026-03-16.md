# plan_migration-testing_2 — Migration Testing with Frozen Brain Fixtures (Revised)

Revision addressing feedback in `plan_migration-testing_review_1_2026-03-16.md`.

---

## Status

Planning artifact. Revision 2. Ready for re-review.

## Objective

Establish a replayable compatibility-testing workflow for supported Brain
Format `1.0` brains, while putting in place the artifact model needed for
future version-to-version migration testing.

The immediate goal is not to claim a `1.0` -> `2.0` upgrade path before Brain
Format `2.0` exists. The immediate goal is to prove, in CI and repeatedly,
that current brain-sync can:

- load a frozen supported-format brain created earlier
- validate it structurally
- rebuild runtime state without mutating portable state
- repair only the drift that current `doctor --fix` actually repairs
- detect unsupported legacy layouts clearly
- run the supported daemon/support path against a real frozen filesystem snapshot

This supports the product direction toward desktop packaging, installers, and
future updater flows where migration confidence must be demonstrated, not
inferred from tests that only build brains with the latest code.

## Authoritative Inputs

- `docs/brain-format/COMPATIBILITY.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/brain-format/VERSIONING.md`
- `docs/plans/PLAN_migration-testing.md`
- `docs/plans/plan_migration-testing_review_1_2026-03-16.md`

## Supported Baseline Framing

Per `docs/brain-format/COMPATIBILITY.md`, the current supported baseline is:

`brain-sync 0.5.0 supports Brain Format 1.0 with runtime DB schema v23`

This revised plan centers that support story first:

1. load a supported Brain Format `1.0` brain from frozen disk state
2. run the supported health and rebuild flows deliberately
3. verify the brain remains healthy
4. repeat this in CI

Future format-to-format upgrade flows should reuse the same frozen-fixture
model, but they are a later expansion once a new Brain Format exists.

## Artifact Model

The plan now uses one stable name for each artifact class:

- `brain-example/`
  Human-facing example brain for docs and walkthroughs. It should be validated,
  but it is not the frozen migration fixture.
- `tests/fixtures/brains/v1.0-canonical/`
  Append-only frozen clean baseline for Brain Format `1.0`.
- `tests/fixtures/brains/v1.0-drifted/`
  Append-only drift fixture containing only drift that current
  `doctor --fix` can repair.
- `tests/fixtures/brains/v1.0-legacy-remnants/`
  Append-only detect-only fixture representing unsupported pre-`1.0`
  leftovers that must not be silently repaired into a supported brain.

No additional overlapping names such as `v1.0-baseline` or
`v1.0-with-sources` should be introduced.

## Separation of Example Brain and Frozen Canonical Fixture

`brain-example/` and the canonical frozen migration fixture must be separate
artifacts.

Reason:

- `brain-example/` is a living documentation/example asset and will attract
  clarifications, cleanup, and pedagogical edits
- a migration fixture must be append-only historical test data
- separating them preserves the stronger invariant that frozen migration data
  is never also a living docs artifact

Implementation consequence:

1. validate and, if needed, repair `brain-example/`
2. snapshot it into `tests/fixtures/brains/v1.0-canonical/`
3. treat the snapshot as the canonical frozen baseline
4. allow `brain-example/` to continue evolving for documentation purposes

## Validator Scope vs Public Fixture Safety

The prior plan overloaded one validator with two concerns. This revision splits
them.

### `scripts/validate-brain.py`

Purpose: structural and specification validation only.

It should validate Brain Format conformance for any brain path, including:

- checked-in frozen fixtures
- `brain-example/`
- a real user brain during support/debugging

Representative checks:

- `.brain-sync/brain.json` exists and matches the supported schema/version
- source manifests conform to `SCHEMAS.md`
- materialized synced files have valid managed identity frontmatter
- co-located insight-state and summary structure is well-formed
- managed namespace placement rules are respected
- unsupported legacy artifacts are detected when not explicitly expected

It should be importable from tests as well as runnable as a script.

### `scripts/check-public-fixture.py`

Purpose: checked-in fixture safety only.

It should reject:

- real company names
- real domains
- real email addresses
- other commit-blocking public-fixture content that violates repository hygiene

This keeps the structural validator usable on real brains without turning it
into a publication-policy tool.

## Frozen Fixture Rules

Frozen fixtures are portable filesystem snapshots, not runtime cache snapshots.

They must contain portable state such as:

- `.brain-sync/brain.json`
- `.brain-sync/sources/*.json` where the scenario includes synced content
- `knowledge/` content
- co-located managed state under `knowledge/**/.brain-sync/`
- `_fixture.json` metadata describing the scenario and expectations

They must not contain runtime-local state such as:

- runtime DB files
- `daemon.json`
- `.pyc` or `__pycache__/`

Fixtures are append-only. If a fixture is wrong, create a new fixture revision
instead of editing history in place.

## Synced Fixture Creation and Stabilization Flow

For synced fixtures, the freeze point must reflect the durable post-first-sync
state, not the pre-normalization import state.

Required flow for `v1.0-canonical` and any other synced fixture:

1. Start from a validated `brain-example/` working copy or another controlled
   Brain Format `1.0` staging brain.
2. Ensure the intended sources are registered.
3. Let the first live sync run to normalize synced content.
4. Stop the daemon cleanly.
5. Copy or restore the summaries intended to remain in the checked-in fixture,
   if the live sync changed them during stabilization.
6. Clear affected `insight-state.json` files where necessary so baseline
   adoption reflects the final checked-in content.
7. Run `brain-sync doctor --adopt-baseline`.
8. Run targeted regen acceptance checks and require:
   `Done. 0 insight files regenerated.`
9. Run `scripts/validate-brain.py` on the resulting tree.
10. Run `scripts/check-public-fixture.py` on the resulting tree.
11. Snapshot the result into `tests/fixtures/brains/v1.0-canonical/`.

Important constraint: the one-time creation flow may use live sync to settle
the fixture, but the checked-in frozen fixture is thereafter replayed offline
by tests as historical filesystem input.

## Repair Scope Classification

The first revision now distinguishes clearly between:

- repairable by current `doctor --fix`
- detectable-only under current behavior
- future capability not yet implemented

### Repairable now

`v1.0-drifted/` must be limited to drift that current `doctor --fix` already
repairs in the existing codebase. The initial drift set should be drawn from
portable-state cases such as:

- missing `.brain-sync/brain.json`
- missing or wrong managed identity frontmatter on a synced file
- stale manifest `materialized_path` when the file is still rediscoverable by
  canonical identity
- manifest path normalization drift

### Detectable only

The plan should explicitly treat these as detectable-only under current code:

- missing `.brain-sync/sources/` manifest set
- missing `insight-state.json`
- stale summaries requiring regen or re-baselining
- unsupported legacy layouts

These may be useful fixtures, but they must not be described as repairable by
current `doctor --fix`.

### Future capability

If the project later wants `doctor --fix` to reconstruct manifests or perform
additional migration work, that should be added explicitly as product work and
tested only after the capability exists.

## Test Layout

Keep the compatibility contract structure, but fit it to the repo's existing
tier model.

- `tests/compat/`
  Shared fixture loaders, contract assertions, and unit-level compatibility
  tests that fit the existing pattern.
- `tests/integration/`
  Repair-path tests that require real filesystem state and runtime rebuild
  behavior.
- `tests/system/`
  CLI/daemon support-path tests such as `brain-sync run` against a frozen
  fixture.

Shared helper:

- `tests/compat/conftest.py`
  `load_frozen_brain(tmp_path, fixture_name)` plus small assertions for fixture
  metadata and structural expectations

Core compatibility scenarios:

1. Clean canonical fixture
   - load `v1.0-canonical`
   - run `doctor`
   - run `rebuild_db`
   - verify portable state remains valid
2. Repairable drift fixture
   - load `v1.0-drifted`
   - run `doctor --fix`
   - verify only the currently supported repairs are applied
   - verify user knowledge files are preserved
3. Legacy remnants fixture
   - load `v1.0-legacy-remnants`
   - verify clear unsupported-legacy findings
   - verify no silent conversion to supported layout
4. Supported run path
   - load `v1.0-canonical`
   - run `brain-sync run` with fake backend
   - verify startup, readiness, clean shutdown, and post-run health

## Phase Plan

### Phase 1: Validate and Freeze the Clean Baseline

- create `scripts/validate-brain.py`
- create `scripts/check-public-fixture.py`
- validate and, if needed, repair `brain-example/`
- snapshot `brain-example/` into `tests/fixtures/brains/v1.0-canonical/`
- record the synced-fixture stabilization procedure used to produce the
  canonical frozen snapshot

### Phase 2: Add Clean Replay Tests

- add shared frozen-fixture loading helpers
- add clean replay coverage for `v1.0-canonical`
- prove:
  - `doctor` passes
  - `rebuild_db` preserves portable state
  - `brain-sync run` operates successfully on the frozen brain

### Phase 3: Add Repairable Drift Coverage

- create `tests/fixtures/brains/v1.0-drifted/`
- restrict it to drift current `doctor --fix` already repairs
- add tests that verify the supported repairs and nothing more

### Phase 4: Add Detect-Only Legacy Coverage

- create `tests/fixtures/brains/v1.0-legacy-remnants/`
- add tests that verify clear detection and no silent repair path

### Phase 5: Optional Tooling Consolidation

- add a reusable `scripts/freeze-brain.py` only after the manual v1.0 fixture
  flow is proven
- optionally consolidate compatibility builders/helpers where that reduces
  duplication without blurring the line between:
  - current-code builders
  - frozen historical fixtures

This keeps the first implementation slice focused on proving the frozen-fixture
model instead of generalizing the tooling too early.

## Fixture Metadata

Each checked-in frozen fixture should include `_fixture.json` with at least:

- `brain_format_version`
- `created_by_app_version`
- `description`
- `frozen_date`
- `scenario_class`
- `repair_expectation`

Suggested `repair_expectation` values:

- `clean`
- `repairable_by_current_doctor_fix`
- `detect_only`

This makes the repair contract explicit and reviewable.

## Acceptance Criteria

- `brain-example/` passes structural validation, but remains separate from the
  frozen canonical fixture
- `tests/fixtures/brains/v1.0-canonical/` exists as an append-only frozen
  Brain Format `1.0` baseline
- the canonical fixture creation notes explicitly include the post-first-sync
  stabilization flow and baseline-adoption step
- targeted regen acceptance on the frozen canonical fixture can reach:
  `Done. 0 insight files regenerated.`
- replay tests prove that a frozen supported-format brain can be:
  - loaded
  - checked with `doctor`
  - rebuilt with `rebuild_db`
  - operated via `brain-sync run`
  - kept healthy across those flows
- `tests/fixtures/brains/v1.0-drifted/` contains only currently repairable
  drift, and `doctor --fix` repairs it without loss of user knowledge
- `tests/fixtures/brains/v1.0-legacy-remnants/` is detected clearly and is not
  silently converted into a supported-format brain
- structural validation and public-fixture safety checks both run on checked-in
  fixtures
- the naming model stays normalized to:
  `brain-example/`, `v1.0-canonical`, `v1.0-drifted`, and
  `v1.0-legacy-remnants`
- the resulting model is ready to support a future Brain Format `2.0` frozen
  upgrade-source fixture without changing the artifact semantics again

## Risks and Mitigations

- Risk: synced content may not be stable at first import.
  Mitigation: require the explicit post-first-sync stabilization and
  `--adopt-baseline` flow before freezing.

- Risk: documentation edits to `brain-example/` could accidentally change the
  migration baseline.
  Mitigation: keep `brain-example/` and `v1.0-canonical/` separate.

- Risk: tests over-promise current repair behavior.
  Mitigation: classify every fixture as clean, repairable, or detect-only and
  keep `v1.0-drifted/` limited to current `doctor --fix` capabilities.

- Risk: generalized freeze tooling adds complexity before the fixture model is
  proven.
  Mitigation: make `scripts/freeze-brain.py` a later consolidation step, not a
  gate for the first slice.

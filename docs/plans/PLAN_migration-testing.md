# PLAN: Migration Testing with Frozen Brain Fixtures

## Status

Planning artifact. Awaiting review.

## Objective

Establish a migration-testing infrastructure that uses **frozen brain
fixtures** — checked-in filesystem snapshots representing specific Brain Format
versions — to prove that brain-sync can detect, upgrade, and operate on brains
from any supported prior version.

The immediate deliverable is a frozen fixture for Brain Format `1.0` (the
current baseline). The infrastructure must be designed so that when Brain
Format `2.0` arrives, adding a frozen `1.0` → `2.0` upgrade test is a
one-fixture, one-test-class addition rather than a cross-cutting rewrite.

## Motivation

The v23 refactor produced 962 tests, all of which create brains using
`init_brain()` or inline fixture setup. Every brain in the suite is built by
the *current* code and therefore always reflects the *latest* format.

This means:

- there is no way to test that a brain created by app version `0.5.0` can be
  opened and upgraded by app version `0.6.0`
- there is no way to test that `doctor --fix` repairs a real v1.0 brain
  correctly after a format change
- the 16 separate `brain` fixtures across the suite all hardcode the current
  layout, making the next format bump a scattered manual update
- COMPATIBILITY.md recommends version-aware builders (`build_brain_v1`, etc.)
  but none were implemented during the v23 refactor

Frozen fixtures solve this by capturing the *actual durable filesystem state*
of a brain at a specific format version, independent of what the current code
produces.

## Authoritative inputs

- `docs/brain-format/COMPATIBILITY.md` — defines the compatibility row model
  and test obligations
- `docs/brain-format/SCHEMAS.md` — defines manifest and frontmatter shapes
- `docs/brain-format/VERSIONING.md` — defines the three version domains
- `brain-example/` — reference Brain Format `1.0` brain, candidate for the
  canonical v1.0 frozen baseline

## Design

### `brain-example/` as the v1.0 canonical baseline

`brain-example/` already exists as a checked-in Brain Format `1.0` brain with
representative content: two synced sources, multiple knowledge areas, co-located
managed state, attachments, journals, and YAML frontmatter. It was created by
AI during the v23 refactor and has not been validated against the spec.

This plan proposes:

1. **Validate `brain-example/`** against the authoritative spec set using a new
   `scripts/validate-brain.py` script (see below).
2. **Fix any spec violations** found during validation.
3. **Promote `brain-example/`** to serve as both the documentation example and
   the canonical v1.0 frozen baseline for migration tests.
4. **When Brain Format `2.0` ships**: snapshot the current `brain-example/` into
   `tests/fixtures/brains/v1.0-canonical/`, update `brain-example/` to the new
   format, and the frozen v1.0 snapshot becomes the upgrade-source test data.

This avoids maintaining two parallel v1.0 brains. The documentation example
*is* the frozen baseline — they just diverge when the format changes, at which
point the old one goes to cold storage.

### `scripts/validate-brain.py`

A standalone validation script that checks any brain directory against the
Brain Format spec:

- `.brain-sync/brain.json` exists with valid `{"version": N}`
- source manifests match the schema in SCHEMAS.md
  - required fields present and correctly typed
  - `source_type` uses durable values (`confluence`, `google_doc`)
  - filenames match `<source_dir_id>.json` derivation rules
- materialized files have valid YAML frontmatter with required identity keys
- co-located `.brain-sync/insights/` structure is well-formed
  - `summary.md` exists where `insight-state.json` exists
  - `insight-state.json` has required fields
- no managed-namespace violations (no `.brain-sync/` content treated as
  knowledge)
- no legacy artifacts (`insights/`, `schemas/`, `.sync-state.sqlite`,
  `version.json`) unless explicitly expected
- no PII or real company names (placeholder check)

The script should be runnable standalone and also importable for use in tests:

```bash
python scripts/validate-brain.py brain-example/
python scripts/validate-brain.py tests/fixtures/brains/v1.0-drifted/ --expect-drift
```

This script serves triple duty:
- validates `brain-example/` in CI
- validates frozen fixtures after creation
- can be pointed at a real user brain for debugging

### Frozen brain fixtures

A frozen brain fixture is a checked-in directory tree that represents the
complete portable filesystem state of a brain at a specific Brain Format
version.

For v1.0, the primary frozen baseline is `brain-example/` (validated and
promoted per the section above). Additional scenario-specific fixtures live
under `tests/fixtures/brains/`:

```text
brain-example/                       # Canonical v1.0 baseline (validated)
tests/fixtures/brains/
├── v1.0-drifted/                    # v1.0 with repairable drift
└── v1.0-legacy-remnants/            # v1.0 brain with leftover pre-v23 artifacts
```

When Brain Format `2.0` ships:

```text
brain-example/                       # Updated to v2.0
tests/fixtures/brains/
├── v1.0-canonical/                  # Snapshot of brain-example/ at v1.0 freeze point
├── v1.0-drifted/                    # (unchanged)
├── v1.0-legacy-remnants/            # (unchanged)
└── v2.0-drifted/                    # New: v2.0 with repairable drift
```

Each fixture directory contains:

- `.brain-sync/brain.json` with the format version
- `.brain-sync/sources/*.json` manifests (where applicable)
- `knowledge/` tree with representative content
- `knowledge/<area>/.brain-sync/` managed state (summaries, sidecars, journals)
- representative frontmatter in materialized files

Each fixture directory also contains a `_fixture.json` metadata file:

```json
{
  "brain_format_version": "1.0",
  "created_by_app_version": "0.5.0",
  "description": "Clean Brain Format 1.0 with two synced sources and three areas",
  "frozen_date": "2026-03-15",
  "scenarios": ["doctor", "doctor-fix", "regen", "run"]
}
```

### What frozen fixtures must NOT contain

- runtime DB files (`.sync-state.sqlite`, `brain-sync.sqlite`) — these are
  machine-local and must be rebuilt by the code under test
- `daemon.json` — runtime state
- `.pyc` or `__pycache__/`
- any real PII or company names (same rules as CLAUDE.md)

### Fixture lifecycle rules

Frozen fixtures are **append-only versioned snapshots**:

- once a fixture is committed for a format version, it is never modified
- if the fixture needs correction, a new fixture is created (e.g.,
  `v1.0-baseline-r2/`) and the old one is retained for regression coverage
- when Brain Format `2.0` ships, the `v1.0-*` fixtures remain permanently as
  upgrade-source test data
- new `v2.0-*` fixtures are created from the `2.0` code at that time

### Fixture creation

The first set of fixtures should be created by a one-time script that:

1. runs `init_brain()` from the current `0.5.0` code
2. seeds representative knowledge content
3. registers sources via `add_source()`
4. runs a fake regen pass to populate managed state
5. strips runtime-only files
6. writes `_fixture.json`
7. commits the result

This ensures the fixture matches what real `0.5.0` code actually produces,
not a hand-crafted approximation. Future format versions repeat this process
with their own code.

A helper script at `scripts/freeze-brain.py` should automate steps 1-7 so
fixtures are reproducible.

### Fixture loading in tests

A shared helper copies a frozen fixture to `tmp_path` and returns a path:

```python
# tests/compat/conftest.py
import shutil
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "brains"

def load_frozen_brain(tmp_path: Path, fixture_name: str) -> Path:
    """Copy a frozen brain fixture to tmp_path for isolated testing."""
    src = FIXTURE_DIR / fixture_name
    assert src.is_dir(), f"Fixture not found: {fixture_name}"
    dest = tmp_path / "brain"
    shutil.copytree(src, dest)
    return dest
```

Note: `create_brain_from_fixture()` already exists in the E2E harness
([brain.py:133](tests/e2e/harness/brain.py#L133)) and does something similar.
The compat version should be independent so compat tests have no dependency on
E2E harness internals.

### Migration test structure

```text
tests/compat/
├── conftest.py                      # load_frozen_brain(), shared assertions
├── test_brain_format_v1.py          # Existing: constants, init, rebuild, legacy
├── test_frozen_v1_doctor.py         # doctor + doctor --fix on frozen v1.0
├── test_frozen_v1_regen.py          # regen on frozen v1.0 (FakeBackend)
├── test_frozen_v1_run.py            # brain-sync run on frozen v1.0 (system tier)
└── test_frozen_v1_upgrade.py        # Placeholder: v1.0 → v2.0 upgrade (future)
```

### Test scenarios for frozen v1.0 brains

#### 1. Doctor on a frozen v1.0 brain

**Tier**: unit (in-process, no subprocess)

- load `v1.0-baseline` fixture
- run `doctor(root)` — expect zero corruption findings
- run `doctor(root, fix=True)` — expect no mutations to portable state

#### 2. Doctor --fix on a drifted v1.0 brain

**Tier**: integration (real FS + SQLite)

- load `v1.0-drifted` fixture (missing sidecars, missing brain.json, etc.)
- run `doctor(root, fix=True)`
- assert repairable issues are fixed
- assert user knowledge files are untouched
- assert portable brain state now passes `doctor(root)` cleanly

#### 3. Doctor on a v1.0 brain with legacy remnants

**Tier**: integration

- load `v1.0-legacy-remnants` fixture (has leftover `insights/`, `schemas/`,
  `.sync-state.sqlite`)
- run `doctor(root)`
- assert `unsupported_legacy_layout` findings are reported
- run `doctor(root, fix=True)`
- assert legacy artifacts are NOT auto-removed (per current policy)

#### 4. Regen on a frozen v1.0 brain

**Tier**: integration (FakeBackend)

- load `v1.0-with-sources` fixture
- rebuild runtime DB from manifests
- run `regen_all(root, backend=FakeBackend("stable"))`
- assert summaries are written to co-located `.brain-sync/insights/`
- assert insight-state sidecars are written
- assert no files created outside `knowledge/**/.brain-sync/`

#### 5. brain-sync run on a frozen v1.0 brain (E2E)

**Tier**: system or e2e

- load `v1.0-with-sources` fixture
- start daemon subprocess with `BRAIN_SYNC_LLM_BACKEND=fake`
- assert daemon starts cleanly (rebuilds runtime DB from manifests)
- assert daemon readiness
- stop daemon
- assert brain passes `doctor(root)` after shutdown

#### 6. v1.0 → v2.0 upgrade (future placeholder)

Not implemented until Brain Format `2.0` exists. The test will:

- load the `v1.0-with-sources` frozen fixture
- run the future upgrade command or `doctor --fix` with upgrade support
- assert the brain is now Brain Format `2.0` conformant
- assert user knowledge is preserved
- assert managed state is migrated or regenerated

### Version-aware builders (consolidation opportunity)

In addition to frozen fixtures, this plan recommends introducing shared
builders in `tests/compat/conftest.py` to reduce the 16 scattered fixture
definitions:

```python
def build_brain_v1(tmp_path: Path, *, with_sources: bool = False,
                   with_knowledge: bool = True) -> Path:
    """Build a Brain Format 1.0 brain using current init code."""
    root = tmp_path / "brain"
    root.mkdir()
    init_brain(root)
    if with_knowledge:
        _seed_default_knowledge(root)
    if with_sources:
        _seed_default_sources(root)
    return root
```

These builders use *current code* and are appropriate for "does the current
release work?" tests. Frozen fixtures are appropriate for "can the current
release operate on brains created by a prior release?" tests.

Both are needed. They serve different purposes.

## Fixture content specification

### brain-example/ (canonical v1.0 baseline)

Already contains:

- `.brain-sync/brain.json` → `{"version": 1}`
- `.brain-sync/sources/c987654.json` — Confluence source
- `.brain-sync/sources/g1zo3CY98lXDGsagjHUHRciomGysWHdzgt5BAXfljhzvU.json` —
  Google Docs source
- `knowledge/_core/` with about-me and co-located managed state
- `knowledge/teams/platform/` with synced Confluence page + attachment
- `knowledge/initiatives/brain-sync-v1/` with synced Google Docs page
- YAML frontmatter on materialized files
- `insight-state.json` sidecars with hashes
- journals
- root-area managed state at `knowledge/.brain-sync/`

Must be validated by `scripts/validate-brain.py` before promotion. Any
spec violations found should be fixed in the fixture.

### v1.0-drifted

A `v1.0-with-sources` brain with intentional drift:

- `.brain-sync/brain.json` deleted (repairable)
- one sidecar `insight-state.json` deleted (repairable)
- one summary stale relative to its sidecar hash (detectable)
- `.brain-sync/sources/` directory missing (repairable)

### v1.0-legacy-remnants

A `v1.0-baseline` brain with leftover artifacts from pre-v23:

- `insights/` top-level directory with stale summaries
- `schemas/` directory with template files
- `.sync-state.sqlite` at brain root
- `.brain-sync/version.json` instead of `brain.json`

## Implementation phases

### Phase 1: Validation and infrastructure

- create `scripts/validate-brain.py`
- run against `brain-example/` and fix any spec violations
- create `tests/fixtures/brains/` directory
- create `v1.0-drifted/` and `v1.0-legacy-remnants/` fixtures
- create `scripts/freeze-brain.py` for generating future fixtures
- create `tests/compat/conftest.py` with `load_frozen_brain()` helper
- add `validate-brain.py brain-example/` to CI

### Phase 2: Core migration tests

- `test_frozen_v1_doctor.py` — scenarios 1-3 above
- `test_frozen_v1_regen.py` — scenario 4
- validate all pass against current codebase

### Phase 3: E2E migration test

- `test_frozen_v1_run.py` — scenario 5 (system/e2e tier)
- requires daemon harness integration with frozen fixture loading

### Phase 4: Builder consolidation (optional)

- add `build_brain_v1()` and friends to `tests/compat/conftest.py`
- migrate scattered `brain` fixtures to use shared builders where appropriate
- this is cleanup, not blocking

## Acceptance criteria

- `scripts/validate-brain.py` exists and validates against the Brain Format
  spec set
- `brain-example/` passes validation cleanly (any spec violations fixed)
- `brain-example/` validation runs in CI
- two scenario fixtures committed under `tests/fixtures/brains/` (`v1.0-drifted`,
  `v1.0-legacy-remnants`), each with `_fixture.json` metadata
- `tests/compat/test_frozen_v1_doctor.py` passes with scenarios 1-3
- `tests/compat/test_frozen_v1_regen.py` passes with scenario 4
- `tests/compat/test_frozen_v1_run.py` passes with scenario 5
- frozen fixtures contain no runtime DB files
- frozen fixtures contain no PII or real company names
- `scripts/freeze-brain.py` can generate scenario fixtures reproducibly
- adding a future `v2.0` upgrade test requires only: snapshot `brain-example/`
  to `tests/fixtures/brains/v1.0-canonical/`, one new test class, and the
  upgrade logic itself

## Relationship to COMPATIBILITY.md

COMPATIBILITY.md section "Future Evolution" says:

> At that point, compatibility tests should expand to include:
> - format-to-format upgrade flows, if supported

This plan implements the infrastructure that makes that expansion trivial.
Each row in the compatibility table gets a corresponding frozen fixture set,
and upgrade tests load the *prior* version's fixture and assert the *current*
version's upgrade logic works.

## Risks

- Risk: frozen fixtures become stale if we retroactively discover the v1.0
  format was under-specified.
  Mitigation: fixtures are append-only; create corrected fixtures rather than
  modifying originals.

- Risk: fixture size bloats the repo.
  Mitigation: fixtures use minimal representative content (< 50 files each,
  no large binaries beyond a small placeholder attachment).

- Risk: freeze script depends on current code, which may not match what the
  original release actually produced.
  Mitigation: freeze the v1.0 fixtures now, before any format changes ship.
  The fixtures capture what `0.5.0` code produces today.

## Open questions

- Should frozen fixtures be gzipped tarballs instead of checked-in directory
  trees?
  Default: checked-in directory trees. They're small, human-readable in PRs,
  and git handles them well. Tarballs add extraction complexity for minimal
  size savings.

- Should the freeze script accept a format version parameter for future use?
  Default: yes. `scripts/freeze-brain.py --format-version 1.0 --name baseline`
  makes the script reusable for future format versions.

- Should `validate-brain.py` be strict (fail on any deviation) or have a
  severity model like doctor?
  Default: strict by default with `--expect-drift` and
  `--expect-legacy-remnants` flags for scenario fixtures that intentionally
  contain violations.

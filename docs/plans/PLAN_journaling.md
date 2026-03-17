# PLAN_journaling: Journaling as Core Generated Meaning

## Status

Planning artifact only. This document defines the implementation plan for
restoring journaling to its intended role as a core part of brain-sync's
generated meaning.

This stage does **not** implement the fix. It records the diagnosis, scope,
design decisions, sequencing, and acceptance gates for later review and
implementation.

## Objective

Make journaling default-on system behavior again, align the implementation with
the documented portable-brain contract, and add test coverage strong enough to
treat journaling as a correctness-critical generated-meaning surface.

The implementation must ensure that:

- journaling is enabled by default during regeneration
- the runtime config knob is an opt-out `disable_journal` flag rather than an
  opt-in `write_journal` flag
- journal files are written only to the documented
  `knowledge/<area>/.brain-sync/journal/YYYY-MM/YYYY-MM-DD.md` path
- legacy misplaced journal files under `.brain-sync/insights/journal/` are
  preserved and migrated safely
- regeneration, cleanup, doctor, MCP, and test code all agree on the same
  journal contract
- the test suite proves both enabled and disabled behavior with real journal
  write or non-write outcomes

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/GLOSSARY.md`
- `docs/RULES.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/brain/TEMPLATES.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/COMPATIBILITY.md`
- `docs/VERSIONING.md`
- `docs/plans/README.md`
- `AGENTS.md`

Implementation must also align with the current code seams that already own
journal prompting, durable persistence, cleanup, layout, and managed-file
surfaces:

- `src/brain_sync/regen/engine.py`
- `src/brain_sync/brain/layout.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/brain/fileops.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/application/config.py`
- `tests/unit/test_regen.py`
- `tests/unit/test_brain_repository.py`
- `tests/unit/test_fileops.py`
- `tests/integration/test_reconcile.py`
- `tests/integration/test_doctor.py`
- `tests/mcp/test_mcp.py`

## Current State and Diagnosis

The current code and documentation disagree on two core points.

First, the documentation defines journals as a normal part of generated
meaning, stored under `.brain-sync/journal/`, durable, append-only, and
non-regenerable. The implementation currently writes journals under
`.brain-sync/insights/journal/` instead. Cleanup, MCP, and tests have largely
shifted to that implementation reality rather than holding the line on the
documented contract.

Second, the current runtime behavior makes journaling opt-in. The regen config
surface uses `write_journal`, defaults it to `False`, and only enables
journaling when that field is explicitly set. This conflicts with the product
meaning expressed in the docs: journals are presented as core generated meaning
rather than as an optional extra.

The test suite currently fails to catch this drift for two reasons:

- some tests explicitly codify the wrong default by asserting that
  `write_journal` is `False`
- some higher-level test modules currently fail during collection, reducing
  the effective coverage on journal behavior

This plan treats both the behavior and the missing coverage as part of the same
correctness bug.

## Scope

In scope for the implementation stage:

- rename the runtime regen flag semantics from `write_journal` to
  `disable_journal`
- make effective journaling default to enabled when no flag is set
- define and implement backward-compatible handling for existing
  `write_journal` settings
- move journal persistence and lookup to the documented
  `.brain-sync/journal/` path
- preserve and migrate any existing journals found under the legacy
  `.brain-sync/insights/journal/` path
- align cleanup, doctor, MCP, and supporting helpers with the correct journal
  location and durability rules
- repair broken journal-relevant test modules so the intended coverage
  actually runs
- add thorough enabled and disabled behavior tests at unit, integration, and
  MCP levels where appropriate
- update runtime and brain docs so the flag semantics and journal path are
  consistent everywhere

## Non-goals

- no change to the semantic threshold for what counts as a journal-worthy event
- no redesign of summary generation or similarity-guard policy beyond what is
  needed to preserve journal correctness
- no conversion of journals from daily files to another storage model
- no weakening of the existing durability or append-only journal contract
- no unreviewed Brain Format version bump unless review concludes that the
  migration semantics require one

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material contradiction with higher-authority repository rules.

### 1. Journaling is default-on generated meaning

Journaling is a core part of the system's generated meaning, not an optional
feature that must be explicitly enabled.

The implementation should therefore make the effective behavior:

- if no journal-related config is present, journaling is enabled
- if `disable_journal` is `true`, journaling is disabled
- if `disable_journal` is `false`, journaling is enabled

The negative flag exists only to support explicit opt-out.

### 2. `disable_journal` is the authoritative config surface

The runtime config surface should become `regen.disable_journal`.

To avoid silently changing existing user intent during rollout, the
implementation should define explicit precedence:

- `disable_journal` takes precedence when present
- legacy `write_journal` is read only as a compatibility shim when
  `disable_journal` is absent
- the compatibility shim maps `write_journal: true` to journaling enabled and
  `write_journal: false` to journaling disabled

This preserves deliberate prior configuration while still moving the system to
the correct default for users with no journal-related setting.

### 3. The documented `.brain-sync/journal/` path is authoritative

The documented path in `docs/GLOSSARY.md`, `docs/RULES.md`, and
`docs/brain/TEMPLATES.md` is the path the code must follow.

Implementation must converge all journal-writing, journal-preserving, and
journal-discovering code to:

- `knowledge/<area>/.brain-sync/journal/YYYY-MM/YYYY-MM-DD.md`

The code must not preserve the current `.brain-sync/insights/journal/` layout
as an alternative steady-state contract.

### 4. Legacy misplaced journals must be preserved and healed

Existing journals written to `.brain-sync/insights/journal/` are still durable
user-visible historical artifacts and must not be lost.

The implementation should provide one deterministic healing behavior for the
legacy path:

- discover legacy journals at the old path
- move or merge them into the correct `.brain-sync/journal/` path
- avoid duplicate entries when both legacy and correct path already exist
- preserve append order within each daily file as faithfully as practical

Automated cleanup must never treat either current-path journals or legacy-path
journals as disposable regenerable artifacts.

### 5. Test collection health is part of the fix

It is not enough to add more journal tests if the relevant modules do not
collect.

The implementation should repair the current broken imports and ensure the
journal-critical tests run in normal targeted pytest invocation.

### 6. The test strategy must validate behavior, not just flags

Tests must prove actual system outcomes, not only config parsing.

That means the suite must verify:

- prompts include or exclude journal instructions as intended
- structured output parsing behaves correctly in both modes
- meaningful regen writes a journal when journaling is enabled
- meaningful regen does not write a journal when journaling is disabled
- similarity-guarded summary skips still write journals when enabled
- cleanup preserves journals at the correct path
- MCP and doctor surfaces do not misclassify journals

## Planned Workstreams

### Workstream 1: Runtime config semantics and compatibility

Update regen config loading and any related config surfaces so the runtime
behavior becomes default-on with explicit opt-out.

Expected changes:

- replace `write_journal` with `disable_journal` in config-facing code
- define and implement precedence between the new and legacy fields
- add direct config-parsing tests for all combinations that matter

Acceptance target:

- a user with no journal config gets journaling enabled by default

### Workstream 2: Journal path convergence and healing

Move all journal persistence and ownership logic to the documented
`.brain-sync/journal/` location and add healing for legacy misplaced journals.

Likely touchpoints:

- `brain/layout.py`
- `brain/repository.py`
- `brain/fileops.py`
- reconcile and doctor logic that reason about managed artifacts
- MCP surfaces that expose managed meaning

Expected changes:

- repository journal writes target the documented path
- cleanup preserves the documented path
- legacy-path journals are migrated or merged safely
- no new code continues to rely on `.brain-sync/insights/journal/`

Acceptance target:

- after the change, the only supported steady-state journal location is
  `.brain-sync/journal/`

### Workstream 3: Regen behavior and journal gating

Align regen prompt assembly, structured-output parsing, and journal-write
orchestration with the new default-on semantics.

Expected changes:

- normal regen paths request journal output unless explicitly disabled
- disabled mode suppresses journal prompting and journal persistence
- enabled mode still preserves the rule that trivial changes may yield no
  journal entry
- similarity-guard behavior continues to treat temporal events as independent
  from summary rewrite decisions

Acceptance target:

- enabled or disabled behavior is deterministic from config and consistent
  across full-path and helper-level tests

### Workstream 4: Test repair and coverage expansion

Repair the currently broken journal-related test modules and expand coverage to
make journaling a protected invariant rather than an incidental feature.

Minimum required coverage:

- config defaults and compatibility mapping
- prompt construction in enabled and disabled modes
- journal creation on meaningful regen with default config
- journal suppression on meaningful regen when disabled
- empty journal section behavior
- similarity-guard journal persistence
- repository append behavior at the correct path
- cleanup and orphan-handling preservation
- doctor and MCP exclusion or classification behavior for journal paths
- legacy-path healing or migration behavior

Acceptance target:

- targeted journal-related pytest selections collect and pass without manual
  test surgery

### Workstream 5: Documentation alignment

Update the authoritative docs so runtime config, generated-meaning semantics,
and journal paths agree everywhere.

Required doc review:

- `docs/runtime/SCHEMAS.md` for runtime config fields
- `docs/GLOSSARY.md` for generated meaning and journal definitions
- `docs/RULES.md` for managed artifact topology and deletion semantics
- `docs/brain/TEMPLATES.md` for the journal path pattern and examples
- `README.md` if any user-facing config guidance mentions regen settings

Acceptance target:

- no repository doc still describes journaling as opt-in or places journals
  under `.brain-sync/insights/journal/`

## Risks and Review Focus

The review should challenge the plan on these points:

- whether the compatibility behavior around legacy `write_journal` is explicit
  enough to avoid surprising existing users
- whether migrating legacy-path journals can ever duplicate or reorder entries
- whether any code path outside regen writes or reasons about journals and
  could be missed by a narrow implementation
- whether a Brain Format or compatibility note is required because the
  implementation corrects previously written on-disk state
- whether the proposed test matrix is sufficient to guard against future drift

## Acceptance Criteria

The implementation is complete only when all of the following are true:

1. With no `regen.disable_journal` and no legacy `regen.write_journal` in
   `~/.brain-sync/config.json`, a meaningful regeneration produces a journal
   file by default.
2. With `regen.disable_journal: true`, the same meaningful regeneration does
   not produce a journal file.
3. With `regen.disable_journal: false`, journaling is explicitly enabled and a
   meaningful regeneration produces a journal file.
4. If only legacy `regen.write_journal` is present, the implementation applies
   the documented compatibility mapping without ambiguity.
5. All newly written journals land at
   `knowledge/<area>/.brain-sync/journal/YYYY-MM/YYYY-MM-DD.md`.
6. Legacy journals under `.brain-sync/insights/journal/` are preserved and
   healed into the correct path without silent loss.
7. Cleanup, doctor, and MCP behavior preserve or classify journals using the
   correct path and durability rules.
8. The targeted journal-related tests collect and pass, including the modules
   that currently fail before execution.
9. The authoritative docs are consistent about:
   - journals being part of generated meaning
   - journal durability and append-only behavior
   - the correct on-disk journal path
   - the runtime config field name and default semantics
10. No new or updated test encodes the old off-by-default `write_journal`
    behavior as the expected contract.

## Implementation Gate

Per `docs/plans/README.md`, implementation must not begin until an approval
artifact exists for this plan unless the user explicitly asks to bypass the
planning trail.

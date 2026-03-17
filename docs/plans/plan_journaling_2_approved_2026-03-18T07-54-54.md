# Approval

Approved: 2026-03-18T07-54-54
Approved by: Codex GPT-5

Notes:
- revision 2 closes the migration-contract, scope-closure, and coverage-shape gaps from review 1
- legacy journal healing ownership, rollout sequencing, config precedence, and Brain Format 1.0 compatibility stance are now explicit enough for implementation
- journal query/search over recent history remains intentionally out of scope for this plan and should be handled as a follow-up planning item if needed

---

# plan_journaling_2: Journaling as Core Generated Meaning

## Status

Planning artifact only. This document revises
`docs/plans/PLAN_journaling.md` after review feedback in
`docs/plans/plan_journaling_review_1_2026-03-18.md`.

This revision closes the three blocking gaps called out in review:

1. the legacy journal healing behavior is now assigned to one owner with an
   explicit rollout sequence, merge rule, and idempotence contract
2. the stale "broken collection" diagnosis has been removed and replaced with
   a current-state coverage matrix tied to the real compatibility risks
3. the concrete contract surfaces that still encode the wrong journal path are
   now explicitly in scope

This stage does **not** implement the fix. It records the approved-direction
scope, migration contract, sequencing, and acceptance gates for later
implementation review.

## Objective

Make journaling default-on system behavior again, align the implementation with
the documented portable-brain contract, and add coverage strong enough to
treat journaling as a correctness-critical generated-meaning surface.

The implementation must ensure that:

- journaling is enabled by default during regeneration
- the runtime config knob is an opt-out `disable_journal` flag rather than an
  opt-in `write_journal` flag
- journal files are written only to
  `knowledge/<area>/.brain-sync/journal/YYYY-MM/YYYY-MM-DD.md`
- existing misplaced journals under `.brain-sync/insights/journal/` are
  healed deterministically without silent loss
- regeneration, cleanup, doctor, MCP, packaged instructions, and test
  harnesses all agree on the same journal contract
- tests prove both enabled and disabled behavior with real journal write or
  non-write outcomes

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

Implementation must also align with the current code and test surfaces that
already own journal prompting, durable persistence, cleanup, repair/reporting,
MCP-facing meaning, and higher-tier contract harnesses:

- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/resources/INSIGHT_INSTRUCTIONS.md`
- `src/brain_sync/brain/layout.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/brain/fileops.py`
- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/application/doctor.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/interfaces/mcp/resources/brain_sync/SKILL.md`
- `src/brain_sync/runtime/config.py`
- `src/brain_sync/application/config.py`
- `tests/unit/test_regen.py`
- `tests/unit/test_brain_repository.py`
- `tests/unit/test_fileops.py`
- `tests/integration/test_reconcile.py`
- `tests/integration/test_doctor.py`
- `tests/mcp/test_mcp.py`
- `tests/e2e/harness/brain.py`
- `tests/e2e/harness/assertions.py`

## Current State and Diagnosis

The current code and documentation disagree on two core points.

First, the documentation defines journals as a normal part of generated
meaning, stored under `.brain-sync/journal/`, durable, append-only, and
non-regenerable. The implementation currently writes journals under
`.brain-sync/insights/journal/` instead. Cleanup, packaged instructions,
MCP-facing skill text, and test harnesses still encode that wrong path in
multiple places.

Second, the current runtime behavior makes journaling opt-in. The regen config
surface uses `write_journal`, defaults it to `False`, and only enables
journaling when that field is explicitly set. This conflicts with the product
meaning expressed in the docs: journals are presented as core generated meaning
rather than as an optional extra.

The current test problem is not "journal tests fail to collect." The more
important issue is that the collecting tests largely reinforce the wrong
default and the wrong path. The active gap is missing contract coverage around:

- default-on behavior with no journal-related config
- precedence when both the new and legacy config keys are present
- deterministic healing when old-path and new-path day files both exist
- doctor, reconcile, MCP, and harness behavior during the legacy-to-correct
  path transition

This plan treats the behavior drift and the missing contract coverage as the
same correctness bug.

## Compatibility and Versioning Decision

This change is a **Brain Format 1.0 drift-healing bug fix**, not a Brain
Format version change.

Revision 2 resolves that branch explicitly:

- no Brain Format version bump
- no runtime DB schema bump
- no new supported compatibility row
- `docs/COMPATIBILITY.md` should be updated to clarify that supported Brain
  Format `1.0` brains with legacy misplaced per-area journal trees remain
  repairable in place
- `docs/VERSIONING.md` should remain unchanged on the format-bump rule, but
  the implementation and tests should make clear that this is corrective
  healing within the existing `1.0` contract

Rationale:

- the portable contract already says journals belong under `.brain-sync/journal/`
- the current `.brain-sync/insights/journal/` layout is implementation drift
  from that contract, not the authoritative format definition
- healing drift back to the documented `1.0` shape is a compatible repair, not
  a new portable format

## Scope

In scope for the implementation stage:

- rename the runtime regen flag semantics from `write_journal` to
  `disable_journal`
- make effective journaling default to enabled when no flag is set
- define explicit precedence and backward-compatible handling for existing
  `write_journal` settings
- move journal persistence and lookup to the documented
  `.brain-sync/journal/` path
- introduce deterministic healing for any journals found under the legacy
  `.brain-sync/insights/journal/` path
- align cleanup, doctor, MCP, packaged prompt instructions, and higher-tier
  harnesses with the correct journal location and durability rules
- add coverage for enabled, disabled, compatibility, and healing behavior
- update authoritative docs so the flag semantics and journal path are
  consistent everywhere

## Non-goals

- no change to the semantic threshold for what counts as a journal-worthy event
- no redesign of summary generation or similarity-guard policy beyond what is
  needed to preserve journal correctness
- no conversion of journals from daily files to another storage model
- no weakening of the existing durability or append-only journal contract
- no Brain Format version bump for this fix
- no change in this plan to `brain_sync_query` or quick-search/index behavior
  over journal content or "last X days" temporal search; that is a separate
  follow-up issue

## Fixed Design Decisions

These decisions should be treated as settled unless a later review artifact
finds a material contradiction with higher-authority repository rules.

### 1. Journaling is default-on generated meaning

Journaling is a core part of the system's generated meaning, not an optional
feature that must be explicitly enabled.

The effective behavior must be:

- if no journal-related config is present, journaling is enabled
- if `disable_journal` is `true`, journaling is disabled
- if `disable_journal` is `false`, journaling is enabled

The negative flag exists only to support explicit opt-out.

### 2. `disable_journal` is the authoritative config surface

The runtime config surface becomes `regen.disable_journal`.

The precedence rule must be explicit and fixed:

1. if `disable_journal` is present, it wins
2. else if legacy `write_journal` is present, it is read as a compatibility
   shim
3. else journaling is enabled by default

Compatibility mapping:

- `write_journal: true` -> journaling enabled
- `write_journal: false` -> journaling disabled

This preserves deliberate prior configuration while still moving no-config
users to the intended default.

### 3. The documented `.brain-sync/journal/` path is authoritative

The documented path in `docs/GLOSSARY.md`, `docs/RULES.md`, and
`docs/brain/TEMPLATES.md` is the path the code must follow.

The supported steady-state location is:

- `knowledge/<area>/.brain-sync/journal/YYYY-MM/YYYY-MM-DD.md`

The code must not preserve `.brain-sync/insights/journal/` as an alternative
steady-state contract.

### 4. Legacy healing is repository-owned and deterministic

`BrainRepository` is the owner of legacy journal-layout healing.

The implementation should introduce a dedicated repository operation for
area-scoped healing and require journal-affecting callers to use it rather
than improvising their own migration behavior.

The repository healing contract must be:

- input: one knowledge area
- source: `.brain-sync/insights/journal/`
- target: `.brain-sync/journal/`
- output: target path contains the healed daily files, and the healed legacy
  subtree is removed after success

Deterministic merge rule for a daily file when both source and target exist:

- parse each file as append blocks separated by the existing timestamp-heading
  entry format
- preserve the current target-file block order as the authoritative base
- append any legacy blocks that are not already present byte-for-byte in the
  target, preserving the legacy file's original block order
- do not rewrite or reorder already-present target blocks

This makes healing idempotent: after one successful heal, re-running the same
operation produces no additional changes.

### 5. Rollout sequencing is fixed

The implementation should follow this sequence:

1. add repository-owned healing primitives and correct-path helpers
2. update journal writes to heal the area before any append and then write only
   to `.brain-sync/journal/`
3. update reconcile, doctor, MCP, packaged instructions, and harnesses to
   understand the transition and the correct steady-state path
4. add or update tests that lock in config precedence, healing, and correct
   path behavior
5. update docs to the final contract wording

This order prevents the main race identified in review: a new-path write
landing beside an untouched old-path file without deterministic healing.

### 6. Transition behavior for doctor, reconcile, and MCP must be explicit

During the implementation transition:

- reconcile must preserve legacy-path journals until repository-owned healing
  has moved them
- doctor must treat per-area legacy journal placement as repairable drift, not
  unsupported-format corruption
- MCP-facing area-reading surfaces must continue to exclude journals from the
  insight payload regardless of whether a legacy or healed path is present

The plan does **not** require journal content to become query-searchable in
this change.

### 7. The test strategy must validate behavior, not only config parsing

Tests must prove actual outcomes, not only field parsing.

Required behaviors to prove:

- prompts include or exclude journal instructions as intended
- structured output parsing behaves correctly in both modes
- meaningful regen writes a journal when journaling is enabled
- meaningful regen does not write a journal when journaling is disabled
- similarity-guarded summary skips still write journals when enabled
- repository append behavior uses the correct path
- healing is idempotent
- cleanup preserves journals at both the legacy and correct paths until healed
- doctor and MCP do not misclassify journals during the transition

## Planned Workstreams

### Workstream 1: Runtime config semantics and compatibility

Update regen config loading and related config surfaces so the runtime behavior
becomes default-on with explicit opt-out and explicit legacy precedence.

Expected changes:

- replace `write_journal` with `disable_journal` in config-facing code
- define and implement the fixed precedence order
- add direct config-parsing tests for:
  - no keys present
  - only `disable_journal`
  - only `write_journal`
  - both keys present

Acceptance target:

- a user with no journal config gets journaling enabled by default

### Workstream 2: Repository-owned path convergence and healing

Move all journal persistence and healing logic to `BrainRepository`.

Likely touchpoints:

- `brain/layout.py`
- `brain/repository.py`
- `brain/fileops.py`

Expected changes:

- repository journal writes target the documented path
- repository exposes one area-scoped healing operation
- healing follows the fixed merge rule
- successful healing removes the healed legacy subtree
- re-running healing produces no further mutation

Acceptance target:

- after the change, the only supported steady-state journal location is
  `.brain-sync/journal/`

### Workstream 3: Runtime surfaces and transition-safe behavior

Align reconcile, doctor, MCP-facing resources, packaged instructions, and test
harnesses with the corrected contract.

Required surfaces:

- `src/brain_sync/sync/reconcile.py`
- `src/brain_sync/application/doctor.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/interfaces/mcp/resources/brain_sync/SKILL.md`
- `src/brain_sync/regen/resources/INSIGHT_INSTRUCTIONS.md`
- `tests/e2e/harness/brain.py`
- `tests/e2e/harness/assertions.py`

Expected changes:

- reconcile preserves and, where appropriate, routes legacy journals toward
  repository-owned healing rather than deleting them
- doctor recognizes legacy per-area journal placement as repairable drift
- MCP and packaged instructions describe the correct journal location
- e2e harness helpers and assertions stop encoding journal-as-child-of-insights

Acceptance target:

- no live code, packaged instruction, or harness still describes the old path
  as the intended steady-state contract

### Workstream 4: Regen behavior and journal gating

Align prompt assembly, structured-output parsing, and journal-write
orchestration with the new default-on semantics.

Expected changes:

- normal regen paths request journal output unless explicitly disabled
- disabled mode suppresses journal prompting and journal persistence
- enabled mode still permits "no journal file" when the model returns an empty
  journal section for a non-journal-worthy change
- any journal append heals the area first, then writes only to the correct path

Acceptance target:

- enabled or disabled behavior is deterministic from config and consistent
  across helper-level and regen-path tests

### Workstream 5: Coverage matrix and contract tests

Replace the stale test diagnosis with a current-state coverage matrix tied to
the real unresolved risks.

Minimum required coverage:

- config defaults and compatibility mapping
- both-key precedence
- prompt construction in enabled and disabled modes
- journal creation on meaningful regen with default config
- journal suppression on meaningful regen when disabled
- empty journal section behavior
- similarity-guard journal persistence
- repository append behavior at the correct path
- repository healing from legacy path to correct path
- idempotent healing when both paths already exist
- cleanup and orphan-handling preservation
- doctor and MCP behavior against both layouts during transition
- one higher-tier e2e or compatibility-style test that proves a supported Brain
  Format `1.0` brain carrying the misplaced legacy journal subtree is healed in
  place without loss

Acceptance target:

- tests protect the product contract, not only the local implementation detail

### Workstream 6: Documentation alignment

Update the authoritative docs so runtime config, generated-meaning semantics,
and journal paths agree everywhere.

Required doc review:

- `docs/runtime/SCHEMAS.md` for runtime config fields
- `docs/GLOSSARY.md` for generated meaning and journal definitions
- `docs/RULES.md` for managed artifact topology and deletion semantics
- `docs/brain/TEMPLATES.md` for the journal path pattern and examples
- `docs/COMPATIBILITY.md` for the drift-healing support note
- `README.md` if any user-facing config guidance mentions regen settings

Acceptance target:

- no repository doc still describes journaling as opt-in or places journals
  under `.brain-sync/insights/journal/`

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
   the fixed compatibility mapping without ambiguity.
5. If both `disable_journal` and `write_journal` are present,
   `disable_journal` wins, and this precedence is tested.
6. All newly written journals land at
   `knowledge/<area>/.brain-sync/journal/YYYY-MM/YYYY-MM-DD.md`.
7. Healing from `.brain-sync/insights/journal/` to `.brain-sync/journal/` is
   repository-owned, deterministic, and idempotent.
8. If both legacy and correct-path day files already exist, healing follows the
   fixed merge rule and does not duplicate already-present blocks.
9. Successful healing removes the healed legacy subtree after the target is
   safely updated.
10. Reconcile, doctor, and MCP behavior preserve or classify journals using the
    fixed transition rules during the rollout.
11. At least one higher-tier test proves that a supported Brain Format `1.0`
    brain carrying legacy misplaced journal files is healed in place without
    loss of journal history.
12. The authoritative docs are consistent about:
    - journals being part of generated meaning
    - journal durability and append-only behavior
    - the correct on-disk journal path
    - the runtime config field name and default semantics
    - this being supported Brain Format `1.0` drift healing rather than a new
      Brain Format
13. No live code, packaged instruction, MCP-facing skill text, or harness still
    encodes `.brain-sync/insights/journal/` as the intended steady-state path.
14. No new or updated test encodes the old off-by-default `write_journal`
    behavior as the expected contract.

## Implementation Gate

Per `docs/plans/README.md`, implementation must not begin until an approval
artifact exists for this revision unless the user explicitly asks to bypass the
planning trail.

# Review

Plan reviewed: `PLAN_migration-testing.md`
Review date: `2026-03-16`
Reviewer: `codex`

## Verdict

Approval recommended only after one revision.

This review artifact does not approve the plan. Create an approved artifact only
after the plan is revised to address the issues below.

## Executive Summary

This is an important and timely plan.

The core idea is strong: if `brain-sync` is going to be supportable as a
desktop product with installers, auto-update behavior, and version-to-version
migration guarantees, then we need durable, replayable representations of prior
brain states. Without that, we cannot credibly claim that supported upgrade
paths are tested.

I agree with the product motivation:

- portable brain formats need to be treated as durable contracts
- supported-version migration paths need replayable test coverage
- runtime-local state must remain clearly distinct from portable on-disk state
- support tooling such as `doctor`, `doctor --fix`, and `brain-sync run` should
  be exercised against real prior-version filesystem snapshots

That said, the plan under-specifies some important migration realities we
learned during the v21 -> v23 work, and it makes a few assumptions that do not
match current code behavior. I would not approve it as written yet.

## What The Plan Gets Right

- It identifies the right problem: current tests mostly build brains using the
  latest code, which does not prove prior-version migration support.
- It correctly treats portable filesystem state as the thing that must be
  frozen, not rebuildable runtime DB state.
- It correctly aims for append-only historical fixtures so old supported states
  remain replayable after the codebase evolves.
- It correctly distinguishes between "current release works" builders and
  "current release can operate on an older brain" frozen fixtures.
- It is well-aligned with a future desktop-updater world, where migration
  confidence becomes a product requirement rather than a testing nicety.

## Required Revisions

### 1. Separate `brain-example/` from the canonical frozen migration fixture

The plan currently proposes using `brain-example/` as both:

- the living documentation/example brain
- the canonical frozen v1.0 migration baseline

I do not think those should remain the same artifact.

Reason:

- a documentation example will inevitably attract cleanup, copy edits, and
  pedagogical improvements
- a migration fixture must be append-only historical test data
- coupling them weakens the very freeze guarantees the plan is trying to create

Recommendation:

- snapshot `brain-example/` now into `tests/fixtures/brains/v1.0-canonical/`
- treat that snapshot as the real frozen migration baseline
- allow `brain-example/` to remain the human-facing example brain

This is a small increase in fixture count, but it preserves the stronger
invariant: frozen migration data is never also a living docs artifact.

### 2. Add the real post-first-sync stabilization step for synced content

The current fixture-creation section assumes that running current code to build
and freeze a representative brain is enough. That is not sufficient for synced
areas.

During the live v21 -> v23 migration work, we observed that synced content does
not reach its durable post-migration state until after the first live sync has
normalized imported files. In practice that means:

- legacy managed headers are rewritten into v23 frontmatter
- legacy attachment references may be rewritten into co-located
  `.brain-sync/attachments/...` paths
- remote content may have diverged since the source snapshot

That means the fixture-freeze flow must explicitly model the real stabilization
sequence for synced areas:

1. create/import the brain
2. register sources
3. let first live sync normalize synced files
4. stop the daemon
5. copy or restore the intended summaries
6. clear affected `insight-state.json` files where necessary
7. run `doctor --adopt-baseline`
8. run targeted regen acceptance checks and require
   `Done. 0 insight files regenerated.`

This should be added to the plan explicitly. Otherwise the "frozen baseline"
risks being captured too early, before the brain has settled into its actual
durable v1.0 form.

### 3. Correct the `doctor --fix` assumptions

The plan currently treats some drift scenarios as repairable that are not
currently repairable by `doctor --fix`.

Most importantly:

- a missing `.brain-sync/sources/` directory is not currently reconstructed by
  `doctor --fix`

Today, `doctor` can detect files with managed identity but no manifest. That is
good. But it does not synthesize manifests from those files. So this scenario
should not be described as repairable unless the plan is also expanded to
include manifest reconstruction work.

Recommendation:

- change the drift fixture so it only contains drift that current `doctor --fix`
  can actually repair, or
- expand the plan to explicitly add new `doctor --fix` functionality for
  manifest reconstruction and then test that behavior

Without that change, the plan is promising test behavior against non-existent
repair capabilities.

### 4. Split structural validation from fixture sanitization

The proposed `scripts/validate-brain.py` is doing two jobs at once:

- validate structural/spec conformance
- reject PII and real company names

Those are related, but they are not the same concern.

A structural brain validator should be usable on:

- frozen fixtures
- `brain-example/`
- a real user brain during support/debugging

A fixture/publication sanitizer should be used when deciding whether a checked-in
fixture is safe to commit publicly.

Recommendation:

- make `validate-brain.py` a structural/spec validator
- if needed, add a separate fixture-sanitization mode or companion script for
  public-fixture checks

Otherwise the validator becomes awkward to use on real brains, which the plan
also says it should support.

### 5. Normalize fixture naming before implementation

The plan currently uses multiple names for what appear to be overlapping
concepts:

- `brain-example/`
- `v1.0-baseline`
- `v1.0-with-sources`
- `v1.0-canonical`

That naming drift will create confusion during implementation.

Recommendation:

Choose and define exactly one name for each class of fixture:

- documentation example brain
- canonical frozen clean baseline
- drifted repair scenario
- legacy-remnants scenario

For example:

- `brain-example/` = human-facing docs example
- `tests/fixtures/brains/v1.0-canonical/` = frozen clean baseline
- `tests/fixtures/brains/v1.0-drifted/` = repair scenario
- `tests/fixtures/brains/v1.0-legacy-remnants/` = unsupported-legacy scenario

## Recommended Scope Adjustments

### Keep the first implementation slice smaller

I recommend a narrower first execution target than the full plan currently
implies.

Suggested first slice:

1. validate and, if needed, repair `brain-example/`
2. snapshot it into `tests/fixtures/brains/v1.0-canonical/`
3. build a strict structural validator
4. add one clean compat test for:
   - `doctor`
   - `rebuild_db`
   - `brain-sync run`
5. add one deliberately drifted fixture that only tests known repairable
   `doctor --fix` behavior

Then, once that is working, add more drift/legacy fixtures.

That keeps the first milestone focused on proving the frozen-fixture model
rather than trying to solve every repair scenario at once.

### Make migration replay the central acceptance story

Because the user’s product concern is long-term supportability, the acceptance
criteria should say this more directly.

Suggested acceptance framing:

- we can load a frozen prior-version brain
- we can run the supported migration/support path deliberately
- we can prove the resulting brain is healthy
- we can do this repeatedly in CI

That makes the product value clearer than talking mostly in terms of fixture
infrastructure.

## Suggested Revision Shape

I recommend the revised plan make these explicit:

### Objective refinement

State plainly that the purpose is to enable replayable supported migration paths
for product supportability, especially for future desktop-installer/updater
flows.

### Artifact model

Define:

- `brain-example/` as a docs/example brain
- `tests/fixtures/brains/v1.0-canonical/` as the frozen migration baseline

### Fixture creation flow

For synced fixtures, include the post-first-sync stabilization flow before
declaring a fixture frozen.

### Validator scope

Define `validate-brain.py` as structural/spec validation only.

### Repair scope

Mark each drift scenario as one of:

- repairable by current `doctor --fix`
- detectable-only
- future capability

### Phase structure

A good revised phase order would be:

1. validate and freeze clean v1.0 canonical fixture
2. add clean compat tests (`doctor`, `rebuild_db`, `run`)
3. add repairable drift fixture(s)
4. add unsupported-legacy fixture(s)
5. optionally consolidate builders

## Approval Conditions

I would approve the next revision if it:

- separates `brain-example/` from the frozen canonical fixture
- adds the synced-content stabilization step
- corrects or narrows the `doctor --fix` assumptions
- splits validator scope from sanitization scope
- normalizes fixture naming

## Closing View

The direction is absolutely right.

This is the sort of infrastructure that will matter more and more as
`brain-sync` becomes a real product with versioned installers and user brains
that must survive upgrades predictably. The plan should go ahead, but it should
do so with a tighter model of what is actually frozen, what is actually
repairable, and what the durable migration path really looks like in practice.

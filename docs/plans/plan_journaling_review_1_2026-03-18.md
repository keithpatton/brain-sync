# plan_journaling Review 1 - Direction Is Right, But The Migration Contract Is Not Yet Tight Enough

**Reviewer:** Codex GPT-5
**Date:** 2026-03-18
**Reviewed document:** `docs/plans/PLAN_journaling.md`
**Reviewed against:**
- `docs/plans/README.md`
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
- `AGENTS.md`
- current code in `src/brain_sync/brain/layout.py`
- current code in `src/brain_sync/brain/fileops.py`
- current code in `src/brain_sync/brain/repository.py`
- current code in `src/brain_sync/regen/engine.py`
- current code in `src/brain_sync/sync/reconcile.py`
- current code in `src/brain_sync/application/doctor.py`
- current code in `src/brain_sync/interfaces/mcp/server.py`
- current code in `src/brain_sync/interfaces/mcp/resources/brain_sync/SKILL.md`
- current code in `src/brain_sync/regen/resources/INSIGHT_INSTRUCTIONS.md`
- current tests in `tests/unit/test_regen.py`
- current tests in `tests/unit/test_brain_repository.py`
- current tests in `tests/integration/test_doctor.py`
- current tests in `tests/integration/test_reconcile.py`
- current tests in `tests/mcp/test_mcp.py`
- current tests in `tests/e2e/harness/brain.py`
- current tests in `tests/e2e/harness/assertions.py`

**Purpose:** Review the canonical journaling plan with a challenge-first
standard and decide whether it is strong enough to hand to an implementer
without core decisions being guessed during execution.

---

## What Is Already Correct

The plan is aimed at a real product-contract bug, and its main diagnosis is
grounded in current code.

The reviewed plan correctly identifies that:

- docs already treat journaling as durable generated meaning under
  `.brain-sync/journal/`
- `src/brain_sync/regen/engine.py` still defaults journaling off via
  `write_journal: bool = False`
- `src/brain_sync/brain/repository.py` still appends journals under
  `.brain-sync/insights/journal/`
- current unit and integration tests still encode the old implementation
  reality in several places

That is enough to justify a plan. The remaining problems are not about whether
the work is needed. They are about whether the plan closes the migration,
compatibility, and scope details tightly enough for approval.

---

## Findings

### F1. The legacy journal healing behavior is still underspecified, and the missing sequencing leaves a real migration risk

This is the main blocking issue.

The plan correctly says legacy journals under
`.brain-sync/insights/journal/` must be preserved and healed, but the actual
behavior is still described too loosely:

- "move or merge"
- "avoid duplicate entries"
- "preserve append order within each daily file as faithfully as practical"

That is not yet a deterministic migration contract.

Current code makes the sequencing problem real:

- `src/brain_sync/brain/repository.py` is the live write path for journal
  appends
- `src/brain_sync/sync/reconcile.py` only cleans orphan
  `.brain-sync/insights/` trees
- `src/brain_sync/application/doctor.py` only flags the unsupported
  top-level `root/insights` legacy layout, not per-area legacy journal
  placement under `.brain-sync/insights/journal/`

Without an explicit sequence, an implementer still has to guess questions that
materially change behavior:

- which surface owns healing: regen, repository, reconcile, doctor, or an
  explicit one-shot migration path
- when healing runs relative to default-on journaling, so a newly written
  `.brain-sync/journal/` file does not race with an untouched legacy file
- what exact merge rule applies when both locations already contain the same
  day file
- whether healing is idempotent
- whether the legacy file is removed after successful healing or retained as a
  compatibility shadow

Revision 2 should define one deterministic healing owner and rollout order, and
it should turn the merge behavior into explicit rules rather than reviewer
questions.

Revision 2 should also make the compatibility/versioning decision explicit
rather than leaving it as review bait. The plan currently says there should be
"no unreviewed Brain Format version bump unless review concludes..." but the
plan itself should resolve that branch. Given `docs/VERSIONING.md` and the
current supported Brain Format `1.0` row in `docs/COMPATIBILITY.md`, the
revision should say either:

1. this is supported Brain Format `1.0` drift healing with no format bump,
   plus the required compatibility note and tests, or
2. this is a portable contract change that requires a format/versioning action,
   with rationale

Leaving that choice open is not approval-ready.

### F2. Workstream 4 is built on a stale diagnosis, so the test plan is not yet anchored to current code reality

This is the second blocking issue.

The plan says some journal-relevant higher-level modules currently fail during
collection and treats "repair broken imports" as part of the fix.

That does not match the current repository state I checked:

- `tests/unit/test_regen.py`, `tests/unit/test_brain_repository.py`,
  `tests/unit/test_fileops.py`, `tests/integration/test_reconcile.py`,
  `tests/integration/test_doctor.py`, and `tests/mcp/test_mcp.py` all collect
  successfully
- a broader `pytest --collect-only -m "unit or integration or external or mcp"`
  pass also succeeds

So the reviewed plan is currently pointing implementers at a problem that, as
of 2026-03-18, is not the active failure mode. That is a contradiction with
current code reality, and it weakens confidence in the rest of the plan's test
inventory.

More importantly, the acceptance criteria still do not lock down some of the
most compatibility-sensitive cases the plan itself says matter:

- precedence when both `disable_journal` and legacy `write_journal` are
  present
- idempotent healing when old-path and new-path day files both already exist
- behavior of doctor/reconcile/MCP surfaces against both layouts during the
  transition
- higher-tier contract protection beyond unit/integration/MCP if the repo
  wants this to be a durable format invariant rather than only a local unit
  detail

Revision 2 should remove the stale "broken collection" claim unless it names
the exact failing module set, and it should replace that space with an exact
coverage matrix keyed to the real unresolved behavior risks.

### F3. The plan does not inventory all of the concrete contract surfaces that still encode the wrong journal location

The third blocking issue is scope closure.

The plan says journaling must be enforced consistently across regen, cleanup,
doctor, MCP, and tests. But the actual touchpoint list still stops short of
several live surfaces that currently encode the old path or old assumptions:

- `src/brain_sync/sync/reconcile.py` is the cleanup owner for orphaned managed
  insight trees
- `src/brain_sync/application/doctor.py` is the repair/reporting owner for
  legacy layout handling
- `src/brain_sync/regen/resources/INSIGHT_INSTRUCTIONS.md` still documents
  journal files under `.brain-sync/insights/journal/`
- `src/brain_sync/interfaces/mcp/resources/brain_sync/SKILL.md` still tells
  MCP readers to look for journals under `.brain-sync/insights/`
- `tests/e2e/harness/brain.py` and `tests/e2e/harness/assertions.py` still
  encode journal-as-child-of-insights assumptions

Those are not optional polish items. If they are left out of the plan's
authoritative seam list and doc/test workstreams, an implementer can follow the
approved plan and still leave repo-internal instructions or higher-tier test
harnesses describing the wrong contract.

Revision 2 should do one of these explicitly:

1. add these files to the authoritative seam/touchpoint inventory and to the
   relevant workstreams, or
2. narrow scope and explain why these surfaces are intentionally deferred to a
   follow-up plan

The current in-between form is too easy to under-implement.

---

## Recommended Revision Shape

Revision 2 should keep the current direction, but it should close the following
gaps before approval:

1. Define one deterministic legacy healing owner, trigger point, merge rule,
   idempotence rule, and rollout sequence.
2. Replace the stale "broken collection" diagnosis with a current-state test
   matrix that explicitly covers default-on behavior, explicit opt-out,
   legacy-only config, both-key precedence, and old-path/new-path healing.
3. Expand the touchpoint inventory so cleanup, doctor, MCP-facing resources,
   regen resources, and higher-tier test harnesses are either explicitly in
   scope or explicitly deferred.
4. Resolve the compatibility/versioning branch in the plan text itself instead
   of leaving it as an open review question.

---

## Verdict

Changes required.

Create a revised plan artifact before any approval artifact is created. This
review artifact does not approve the plan and does not authorize
implementation.

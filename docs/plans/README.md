# Planning Directory

This folder holds engineering plans, review artifacts, approvals, and related
notes. The naming convention is designed to make the lifecycle readable in a
filesystem listing without needing to open each file.

The planning directory is append-only. Existing artifacts are never modified or renamed as part of the normal workflow.

## Lifecycle

Each plan starts from the canonical root plan and then branches by outcome:

1. `PLAN_<id>.md` is the canonical root plan.
2. The latest plan version is evaluated by the reviewer or reviewer/approver.
3. If changes are required, `plan_<id>[_<iteration>]_review_<n>_<date>.md`
   records the issues to resolve.
4. The planner answers that review with a new revision
   `plan_<id>_<iteration>_<date>.md`.
5. If the latest revision is acceptable, create
   `plan_<id>_<iteration>_approved_<datetime>.md`.

Reviews always attach to a specific plan version. Revisions create a new plan
file rather than overwriting the previous one. Approval is represented as a
final suffix on the approved plan version.

A plan is approved only when the corresponding
`plan_<id>_<iteration>_approved_<datetime>.md` artifact exists. Implementation
begins only after that approval artifact exists, unless the user explicitly
asks to bypass the planning trail.

The important clarification is that a passing evaluation round normally ends in
an approval artifact, not in a final positive review artifact plus a separate
approval artifact.

Supporting inputs may exist alongside the plan trail when a planner needs extra implementation context. They inform a plan, but they are not part of the plan → review → revision → approval lifecycle.

Architecture reviews under `docs/architecture/reviews/` are one important class
of supporting input. They diagnose and recommend; they do not authorize work by
themselves.

When a plan emerges from an architecture review:

- the plan should cite the review in its authoritative inputs or context
- the review may list the derived plan in a `Derived Plans` section once that
  plan has been approved
- the plan remains the authoritative execution artifact

## Schema

Canonical root plan:

```text
PLAN_<id>.md
```

The canonical root plan is considered iteration 1. Subsequent revisions begin at iteration 2.

Plan revision:

```text
plan_<id>_<iteration>_<date>.md
```

Review:

```text
plan_<id>[_<iteration>]_review_<n>_<date>.md
```

Approved revision:

```text
plan_<id>_<iteration>_approved_<datetime>.md
```

Where:

- `<id>` is a short stable identifier for the planning topic, such as `v23`, `storage-refactor`, or `api-redesign`
- `<iteration>` is the revised plan number, starting at `2`
- `<n>` is the review number, starting at `1`
- `_approved` appears only on the approved file
- `<timestamp>` is either:
  - `<date>` as `YYYY-MM-DD` for plans and reviews
  - `<datetime>` as `YYYY-MM-DDTHH-MM-SS` for approvals when a more precise marker is useful

Reviews without an iteration number refer to the canonical root plan, which is iteration 1.

## Agent Roles

The planning directory supports three roles: planner, reviewer, and approver.

One agent may hold both the reviewer and approver roles. In that common flow,
the agent should review first, try to find substantive problems, and then emit
only one artifact for that pass:

- a review artifact when the plan must come back for revision
- an approval artifact when the plan is ready to execute

Do not create both artifacts for the same approval pass unless the user
explicitly wants separate reviewer and approver records preserved.

### Planner

The planner is responsible for producing plan revisions.

The planner may:

- create the initial plan `PLAN_<id>.md`
- create revised plans `plan_<id>_<iteration>_<date>.md`
- incorporate review feedback into a new revision

Role scope rule:

- unless the user explicitly assigns additional roles for the same task, an
  agent acting as the planner must stop after creating the plan artifact
- a planner-only task must not also create review or approval artifacts
- preserving the planner, reviewer, and approver trail means keeping those
  artifacts separate, not having the planner generate the later-role artifacts
  by default

The planner must never:

- overwrite a previous plan revision
- modify an existing review artifact as part of the review cycle
- modify an existing approval artifact

Revisions always produce a new plan file.

### Reviewer

The reviewer evaluates a plan revision and records feedback in a separate review artifact.

A review file must use:

- `plan_<id>[_<iteration>]_review_<n>_<date>.md`

Reviews may contain:

- critique
- risks
- suggested improvements

The reviewer must never modify the plan file being reviewed.

The reviewer must not treat a review artifact as approval or as permission to
begin implementation.

The reviewer should apply a challenge-first standard. Approval should be
withheld when the plan still has unresolved scope ambiguity, missing acceptance
criteria, under-specified sequencing, contradictory guidance, or risks left for
the implementer to guess through.

If the reviewer is also acting as approver and the plan is acceptable, the
review should stop at that internal conclusion and the durable artifact for that
pass should be the approval artifact, not an extra final review file.

### Approver

The approver determines whether a plan revision is acceptable.

Approval is represented by creating an approval artifact:

- `plan_<id>_<iteration>_approved_<datetime>.md`

The approval file is created by copying the approved plan revision and adding the `_approved_<datetime>` suffix.

Only the most recent plan revision may be approved. If a review identifies issues, the planner must produce a new revision before approval can occur.

Approval must not modify the original plan file.

Approval is the authoritative handoff for implementation. If non-blocking
implementation notes still matter after approval, put them in the approval
attestation rather than leaving them only in a separate final review artifact.

If the approver finds the plan acceptable, the next required action is to
create the approval artifact. The approver should stop after creating that
artifact unless separately asked to implement the plan.

If the same agent is serving as reviewer and approver, do not create a
same-pass "approval recommended" review artifact and then a second approval
artifact. Create the approval artifact directly.

## One Artifact Per Evaluation Pass

For a given evaluation of the latest plan version, create exactly one durable
decision artifact:

- review artifact, if changes are still required
- approval artifact, if the plan is acceptable

This avoids two common failure modes:

- the final review and the approval attestation drifting apart
- implementation-relevant advice being left in the wrong artifact

If the user explicitly wants separate reviewer and approver artifacts for the
same passing round, that is allowed. In that case:

- the review may recommend approval
- the approval artifact remains authoritative
- any implementation-relevant notes that still matter must be copied into the
  approval attestation

Otherwise, when a round ends in approval, do not create a review artifact for
that same round.

## Approval Threshold

Approval should mean more than "good enough to start coding."

Do not approve while any of the following remain materially unresolved:

- scope or boundary ambiguity
- key design decisions deferred to implementer guesswork
- missing or weak acceptance criteria
- contradictions with higher-authority docs or current code reality
- sequencing gaps that could invalidate later work
- open review findings that change the plan's requirements

Non-blocking advisories may remain, but they should fit cleanly in approval
notes without changing the approved plan's meaning.

## Approval Attestation

An approval file may include a short attestation header above the approved plan contents.

Example:

```md
# Approval

Approved: 2026-03-15T19-32-00
Approved by: reviewer-agent

Notes:
- plan meets v23 architectural invariants
- no unresolved risks remain

---

<copy of approved plan follows>
```

This keeps approval visible while preserving the approved plan text as a separate append-only artifact.

The approval artifact is the authoritative implementation handoff. Any advisory
notes that should survive into execution belong here.

When copying the approved plan into the approval artifact, remove or rewrite
plan-only boilerplate that would be false after approval, such as:

- "this file is not approval"
- "the next required action is to create an approval artifact"

## Implementation Gate

The planning workflow has a hard boundary between review, approval, and
implementation:

- a review artifact may recommend approval
- a review artifact is not an approval artifact
- approval is complete only when `plan_<id>_<iteration>_approved_<datetime>.md` exists
- implementation must not begin from a review artifact alone

If a reviewer finds a plan acceptable, the next required action is to create
the approval artifact. Agents must not treat phrases inside a review file as
permission to skip that step.

If the user explicitly asks to bypass the planning trail, that instruction
overrides this default workflow.

## Review Wording Guidance

To keep the gate unambiguous:

- do not use verdicts such as `Approved for execution`
- do not end a review artifact by telling the next agent to implement
- default review verdicts should be challenge-oriented, such as `Changes required`
- use `Approval recommended` only when the user explicitly wants separate reviewer and approver artifacts for the same passing round

In the common combined reviewer/approver flow, omit the positive review artifact
entirely and create the approval artifact instead.

Example review verdict:

```md
## Verdict

Changes required.

Create a new plan revision that resolves the findings in this review.
This review artifact does not approve the plan and does not authorize
implementation.
```

Example approval artifact:

```md
# Approval

Approved: 2026-03-15T06-47-00
Approved by: reviewer-agent

Notes:
- no unresolved risks remain

---

<copy of approved plan follows>
```

Use `plan_v23_3_approved_2026-03-15T06-47.md` in this directory as the
concrete pattern to mirror for future approval artifacts.

## Supporting Inputs

An optional supporting input may be kept in this folder when a plan needs a separate context or implementation-guidance document.

Supporting input file:

```text
plan_<id>_supporting.md
```

Supporting inputs:

- are optional
- may provide context, analysis, or implementation guidance used to produce a plan
- are not plan revisions, reviews, or approvals
- must not be used to represent approval

When present, they should be treated as supplementary input to the planning artifacts, similar to context for the planner or reviewer.

## Implementation Notes

Any agent involved in the execution of an approved plan may add material
implementation notes in the relevant notes file when one exists.

Implementation notes are for execution-relevant context that may not be obvious
from the commit history alone, such as:

- approved variations from the plan
- implementation clarifications
- bounded deferments
- non-obvious tradeoffs or constraints the next agent must preserve

Implementation notes are not a duplicate changelog. Do not use them for:

- routine summaries of code changes already clear from commits
- validation logs already captured elsewhere
- file-by-file implementation inventories
- status narration with no lasting execution relevance

Implementation notes file:

```text
plan_<id>_<iteration>_notes.md
```

Implementation notes should:

- use one notes file per approved plan version
- append new notes at the top so the newest entry is seen first
- be written in date/time-descending order
- record only material execution-relevant decisions, clarifications, approved variations, or bounded deferments

Example:

```md
# Plan v23.3 Implementation Notes

2026-03-16T09:12:00
Change: `_core` context for non-`_core` regen now uses summary only.
Reason: Token determinism and prompt pressure reduction.
Status: Implemented.

2026-03-15T18:40:00
Change: Approval trail requires an `_approved_<datetime>` artifact before implementation.
Reason: Keep the planning gate explicit.
Status: Clarified.
```

## Filename Rules

Use uppercase only for the canonical root plan:

- `PLAN_<id>.md`

Use lowercase for every later artifact:

- `plan_<id>_review_<n>_<date>.md`
- `plan_<id>_<iteration>_<date>.md`
- `plan_<id>_<iteration>_review_<n>_<date>.md`
- `plan_<id>_<iteration>_approved_<datetime>.md`

## Ordering Guidance

Keep names short and predictable so related files stay grouped together in directory listings:

- the root plan stays first as `PLAN_<id>.md`
- reviews sort near the plan they discuss
- later revisions increase only the iteration number
- approval stays visually obvious with the `_approved` suffix

The naming scheme is designed so that standard filesystem sorting naturally groups plans, reviews, and revisions in chronological order.

## v23 Example

```text
docs/plans/
├── PLAN_v23.md
├── plan_v23_supporting.md
├── plan_v23_review_1_2026-03-15.md
├── plan_v23_2_2026-03-15.md
├── plan_v23_2_review_1_2026-03-15.md
├── plan_v23_3_2026-03-15.md
└── plan_v23_3_approved_2026-03-15T19-32-00.md
```

Lifecycle example:

```text
PLAN_v23.md
   ↓
plan_v23_supporting.md
   ↘
plan_v23_review_1_2026-03-15.md
   ↓
plan_v23_2_2026-03-15.md
   ↓
plan_v23_2_review_1_2026-03-15.md
   ↓
plan_v23_3_2026-03-15.md
   ↓
plan_v23_3_approved_2026-03-15T19-32-00.md
```

## Current Files

Some older files in this folder predate these clarifications and may still show
positive review artifacts alongside approvals, or copied plan text that was not
normalized for the approved state. Follow the rules in this README for future
artifacts so the trail stays consistent and easy to scan.

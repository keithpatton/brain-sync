# Planning Directory

This folder holds engineering plans and their reviews. The naming convention is designed to make the lifecycle readable in a filesystem listing without needing to open each file.

The planning directory is append-only. Existing artifacts are never modified or renamed as part of the normal workflow.

## Lifecycle

Each plan moves through only these stages:

1. `PLAN_<id>.md` is the canonical root plan.
2. `plan_<id>_review_<n>_<date>.md` records review feedback for that plan version.
3. `plan_<id>_<iteration>_<date>.md` records the next revised plan iteration.
4. `plan_<id>_<iteration>_approved_<datetime>.md` marks the approved revision.

Reviews always attach to a specific plan version. Revisions create a new plan file rather than overwriting the previous one. Approval is represented as a final suffix on the approved plan version.

Supporting inputs may exist alongside the plan trail when a planner needs extra implementation context. They inform a plan, but they are not part of the plan → review → revision → approval lifecycle.

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

### Planner

The planner is responsible for producing plan revisions.

The planner may:

- create the initial plan `PLAN_<id>.md`
- create revised plans `plan_<id>_<iteration>_<date>.md`
- incorporate review feedback into a new revision

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
- an approval recommendation

The reviewer must never modify the plan file being reviewed.

### Approver

The approver determines whether a plan revision is acceptable.

Approval is represented by creating an approval artifact:

- `plan_<id>_<iteration>_approved_<datetime>.md`

The approval file is created by copying the approved plan revision and adding the `_approved_<datetime>` suffix.

Only the most recent plan revision may be approved. If a review identifies issues, the planner must produce a new revision before approval can occur.

Approval must not modify the original plan file.

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
└── plan_v23_2_approved_2026-03-15T19-32-00.md
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
plan_v23_2_approved_2026-03-15T19-32-00.md
```

## Current Files

The v23 files in this folder have been aligned to this convention. Keep future plan artifacts on the same pattern so the revision trail stays easy to scan.

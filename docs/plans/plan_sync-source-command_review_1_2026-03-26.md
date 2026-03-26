# Review

Plan under review: `docs/plans/PLAN_sync-source-command.md`
Reviewer: codex-gpt-5
Date: 2026-03-26

## Summary

The plan is directionally strong and is anchored on the right invariants:
direct source processing, daemon independence, existing per-source leases, and
no inline regen. I am not approving it yet because a few contract choices are
still deferred to implementation, and those choices materially affect CLI/MCP
behavior and daemon-parity semantics.

## Findings

### 1. Source selector contract is still unresolved

Phase 0 explicitly leaves a core surface decision open:

- canonical ID only
- canonical ID or URL

That is not a minor implementation detail. It changes:

- CLI compatibility with existing source-management commands, which commonly
  accept canonical ID or URL
- whether the MCP tool can share the same transport-neutral facade cleanly
- error semantics for ambiguous or malformed identifiers
- documentation and test expectations

Approval should not leave this choice to the implementer. The next revision
should state the selector contract explicitly for every surface in scope and,
if CLI and MCP intentionally differ, explain why.

### 2. The CLI outcome and exit-code contract is underspecified

The plan defines helpful outcome states, but it still leaves the CLI contract
materially open with language such as:

- "unless the CLI contract intentionally wants non-zero exit for contention"
- "CLI-level proof ... where practical"

That is not specific enough for approval. The plan should explicitly map each
result state to CLI behavior, including at least:

- printed summary shape
- exit code for `changed`
- exit code for `unchanged`
- exit code for `lease_conflict`
- exit code for `not_found`
- exit code for `remote_missing`
- exit code for unexpected internal error

Without that mapping, the acceptance criteria are too weak to prevent
incompatible handler and system-test interpretations.

### 3. "Same source-processing path as daemon polling" is still ambiguous in one important way

The plan correctly centers `process_source(...)`, but the daemon's effective
single-source polling behavior is broader than that call alone. In
`src/brain_sync/sync/daemon.py`, the daemon also owns follow-on behavior around
the processing call, including:

- loading and consuming pending child-discovery requests
- processing discovered children and scheduling them immediately
- updating the in-memory/runtime polling projection after the sync attempt
- handling `remote_missing` through the normal missing-source observation path

Right now the plan does not say whether `sync-source` must mirror those
follow-on semantics, intentionally ignore them, or adopt a narrower rule.
That gap matters because `docs/RULES.md` defines `fetch_children` and
`child_path` as one-shot operational inputs that are consumed at execution
time, not latent durable settings.

The next revision should explicitly answer at least:

- whether a pending child-discovery request is consumed by `sync-source`
- whether discovered children are processed/scheduled in the same invocation
- how `remote_missing` updates durable/runtime state outside the daemon loop
- whether a successful forced sync refreshes the persisted next-poll timing or
  intentionally leaves scheduler timing unchanged

Without those answers, "same path as daemon polling" still leaves too much
behavior to implementer judgment.

## Verdict

Changes required.

Create a new plan revision that resolves the findings in this review.
This review artifact does not approve the plan and does not authorize
implementation.

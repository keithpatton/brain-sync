# Review

Plan reviewed: `docs/plans/plan_regen-refactor_3_2026-03-22.md`
Reviewer: Codex
Date: 2026-03-22

## Verdict

Changes required.

Create a new plan revision that resolves the findings below. This review
artifact does not approve the plan and does not authorize implementation.

## Findings

### 1. The phased gate model is described, but it is still not operationally real enough to enforce pauses and decisions

Revision 3 materially improves the checkpoint language, but it still leaves the
actual gate mechanics under-specified for an approved execution trail.

The plan now requires each phase to pause, produce findings, surface product
calls, review docs, and continue only after the checkpoint is accepted. That is
the right direction. The remaining approval blocker is that the plan does not
say where those checkpoints live durably, who is authorized to accept them, or
what minimum proof makes a checkpoint pass versus fail. In the current planning
workflow, that gap matters. `docs/plans/README.md` gives the implementer a
notes-file mechanism for durable execution-relevant decisions, but revision 3
does not bind the phase checkpoints to that or any other durable artifact. As
written, the pauses could collapse into chat-only narration or implementer
self-approval. The same problem appears in the proof language: terms such as
`materially fewer`, `strong enough`, and `real findings` are directionally
useful, but the plan still does not define what evidence is sufficient to let
the next phase start.

Required revision:

- make the checkpoint trail durable rather than conversational by naming where
  each phase checkpoint must be recorded
- state who can clear the next phase to begin
- tighten the checkpoint proof expectations enough that continuation is not left
  to implementer interpretation

### 2. The sequencing still forces backend-capability decisions too late, which risks re-encoding Claude-specific assumptions in Phase 2

The plan says REGEN must become more backend-agnostic and capability-aware, but
the phase order still leaves a material sequencing gap between that goal and
the current code reality.

Current REGEN remains strongly Claude-shaped. `src/brain_sync/regen/engine.py`
still hard-codes `CLAUDE_TIMEOUT`, `MAX_PROMPT_TOKENS = 120_000`, a
`MINIMAL_SYSTEM_PROMPT` explicitly described as a Claude CLI optimization,
Claude-specific structured-output parsing, and the `_InvokeClaudeShim`
compatibility path. At the same time, Phase 2 requires
`model-aware or capability-aware prompt budgeting instead of one hard-coded
universal budget`, while Phase 6 is where the plan first names the
backend-capability seams that would define things like context budget,
structured-output reliability, and startup overhead expectations.

That leaves the implementer with no approved source of truth for capability
policy during the phase that most needs one. In practice, the implementer would
have to invent an interim capability model or add model-string heuristics in
Phase 2, which is exactly how Claude-specific assumptions would get tightened
further before the later backend-readiness phase arrives.

Required revision:

- resolve the sequencing by either moving the backend-capability contract
  earlier, or by stating a bounded interim capability rule that is explicit
  enough to guide Phase 2 without re-coupling REGEN to Claude-specific policy

### 3. Phase 3 still leaves the target propagation contract too open-ended relative to the current code and rules

Propagation is one of the core product and architecture decisions in this plan,
and revision 3 still does not specify the target contract tightly enough for
approval.

Current repo reality is concrete, not abstract. In `src/brain_sync/regen/topology.py`,
wave propagation currently includes `regenerated`, `skipped_no_content`,
`cleaned_up`, and `skipped_rename`. In `src/brain_sync/regen/engine.py`,
single-path walk-up continues on those outcomes and also on `skipped_backfill`.
`docs/regen/README.md` documents that asymmetry explicitly. `docs/RULES.md`
already frames propagation normatively in terms of when a parent is processed
and when walk-up stops. Revision 3 says the target is dependency-based
propagation and one authoritative shared rule set, but it still does not say
what the intended target behavior is for the concrete edge cases that matter:
rename-only, no-content cleanup, explicit cleanup, similarity skips,
backfill-only paths, and failure cases.

That is still too much plan-level meaning left for the implementer to infer.
Those are not code-shape details; they define whether a parent is considered
dirty and therefore directly affect REGEN behavior, the explanatory REGEN docs,
and potentially `docs/RULES.md`.

Required revision:

- either add the target propagation matrix directly to the plan, or
- add a mandatory pre-implementation product-call checkpoint for those specific
  outcome classes so the implementer cannot decide them ad hoc while executing
  Phase 3

### 4. The plan still does not pin down the product contracts for summary/journal coupling and observability scope tightly enough

Revision 3 correctly elevates both topics, but it still leaves the decisive
contract choices too open for an approval handoff.

Current behavior is already opinionated. `src/brain_sync/regen/engine.py` and
`docs/regen/README.md` allow a journal entry to be written even when the
similarity guard keeps the existing summary. `docs/RULES.md` also treats
journals as durable and non-regenerable. Phase 4 asks for clearer handling when
summary and journal diverge or when one artifact fails, but it does not state
what outcome the system should treat as valid, invalid, retriable, or partially
successful. That leaves a material product decision open in exactly the place
where the plan says the implementer must not guess.

The same problem exists in Phase 5. The required diagnostics include why a path
ran, skipped, propagated, or chunked, plus per-artifact token cost and
high-churn paths. But the plan does not say whether that diagnostic contract is
supposed to live in logs, `operational_events`, `token_events`, `regen_locks`,
new runtime schema, or some mixed surface. Current runtime docs and schemas
describe only the existing machine-local surfaces. If Phase 5 changes those
runtime contracts, the plan must make the documentation and versioning trigger
explicit enough that the implementer does not have to guess whether
`docs/runtime/README.md`, `docs/runtime/SCHEMAS.md`, `docs/VERSIONING.md`, and
`docs/COMPATIBILITY.md` are now required updates or merely optional follow-up.

Required revision:

- make the Phase 4 product-call outputs explicit enough to resolve
  summary/journal partial-success semantics
- make the Phase 5 observability scope explicit enough to identify the intended
  runtime contract surface and the resulting doc/versioning obligations

## Summary

Revision 3 is stronger than the prior plan revision, especially on
documentation awareness and the stated intent to pause between phases.
Approval is still withheld because the plan does not yet make the phase gates
durable enough, still sequences capability policy too late for a
backend-agnostic prompt-budgeting phase, and still leaves the decisive
propagation, artifact-coupling, and observability contracts open to implementer
judgment.

# Review

Plan reviewed: `docs/plans/plan_source-lifecycle-hardening-v2_3_2026-03-22.md`
Review date: 2026-03-22
Reviewer: Codex GPT-5

## Verdict

Changes required.

Create a new plan revision that resolves the blocking findings in this review.
This review artifact does not approve the plan and does not authorize
implementation.

## Summary

The contract direction is sound: replacing session-gated finalization freshness
with direct command-time revalidation is a coherent product model for the CLI
and it keeps the important safety boundary at destructive commit time. The
scope also stays appropriately focused on explicit finalization semantics.

I am not approving this revision yet because the plan still leaves two
important implementation choices unresolved: the exact post-change
`finalize-missing` result model, and the versioning/compatibility/runtime-schema
story for retained session-confirmation fields.

## Blocking Findings

### 1. The acceptance and system-test language still implies a multi-invocation gate that contradicts the stated contract

The plan's product decision says command-time revalidation becomes the sole
freshness check and that the two-step same-session confirmation requirement is
intentionally removed. But the proof language still says:

- real CLI usage should work through `normal repeated subprocess usage`
- the system suite should prove that `two normal CLI subprocess invocations`
  move a source from `missing` to `finalized`

That is no longer a neutral wording choice. It leaves the implementer guessing
whether approval still expects a residual two-call gate, or whether a source
already in durable `knowledge_state = missing` should finalize on a single
explicit `finalize-missing` invocation when revalidation still shows absence.

A revision should choose one exact product rule and make the acceptance and
test expectations match it. If the intended contract is truly "command-time
revalidation is the only freshness check," the normal success proof should be
written as a single explicit finalization call against an already-missing
source, with repeated subprocess usage covered only as an allowed process model
rather than as a required extra confirmation step.

### 2. The revised plan does not fully choose the post-change `finalize-missing` result contract

The plan clearly removes session identity as a functional deletion gate, but it
does not explicitly finish the user-facing result model after that change.
Current product surfaces and tests treat `pending_confirmation` as a concrete
CLI and MCP outcome. This revision says retained confirmation/session fields
may remain observational or compatibility-retained, but it never states
whether:

- `pending_confirmation` remains a supported result at all
- `pending_confirmation` remains only for some non-happy-path situations
- missing-confirmation counts are still surfaced to users/tools or become pure
  diagnostics
- CLI and MCP contracts should remove, preserve, or narrow any existing
  payload and exit-code behavior tied to that result

That ambiguity is material because the current tests, docs, and transports
already expose a concrete result contract. A revision should state the exact
terminal result set and behavior expected after this simplification for CLI and
MCP, including whether `pending_confirmation` survives, what fields remain in
successful or handled responses, and what proof is required in unit/system/MCP
tests for that contract.

### 3. Versioning, compatibility, and runtime-schema consequences are still under-specified and currently contradict higher-authority docs

The authoritative docs already describe the current-session freshness rule as
part of the supported `v28` runtime contract. In particular, the current
versions of `docs/VERSIONING.md`, `docs/COMPATIBILITY.md`,
`docs/runtime/SCHEMAS.md`, `docs/runtime/README.md`, `docs/RULES.md`, and
`docs/architecture/ARCHITECTURE.md` all describe `last_missing_confirmation_session_id`
as functionally relevant to destructive finalization.

This revision correctly names `docs/VERSIONING.md` and
`docs/COMPATIBILITY.md` as authoritative inputs, but it does not include them
in the required documentation updates or acceptance criteria. It also does not
choose the exact compatibility posture for the retained field:

- does runtime schema stay at `v28` with the same column retained but reduced
  to observational semantics
- does that semantics change require an explicit compatibility note even if the
  physical schema does not change
- if the field is now dead enough to remove, does that require a runtime-schema
  bump and migration obligations in this round or an explicit deferment

Those choices should not be left to the implementer. A revision should state
the exact schema/versioning/compatibility decision and require the owning docs
to be updated consistently. It should also name the compatibility proof that
follows from that choice, such as whether migration tests remain unchanged,
whether retained rows/fields must still round-trip, and whether compatibility
docs must explicitly describe the field as observational-only.

## Non-blocking Suggestions

- Add one short sentence that explicitly says the rest of the v2 same-source
  serialization and conflict contracts remain unchanged by this follow-up, so
  the approval boundary stays visibly narrow.
- If retained confirmation/session fields remain in payloads or events for
  diagnostics, name the minimum surfaces where they may still appear so review
  can distinguish intentional compatibility retention from accidental policy
  coupling.
- Keep the implementation-notes expectation that this is a product-contract
  simplification rather than a quiet implementation workaround; that framing is
  useful and worth preserving into the next revision.

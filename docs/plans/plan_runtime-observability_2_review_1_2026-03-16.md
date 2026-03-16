# plan_runtime-observability_2 Review 1 - Event Contract Added, Approval Recommended

**Reviewer:** Codex GPT-5
**Date:** 2026-03-16
**Reviewed document:** `docs/plans/plan_runtime-observability_2_2026-03-16.md`
**Prior review:** `docs/plans/plan_runtime-observability_review_1_2026-03-16.md`
**Reviewed against:**
- `docs/plans/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `docs/brain-format/README.md`
- `docs/brain-format/GLOSSARY.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/brain-format/VERSIONING.md`
- `docs/brain-format/COMPATIBILITY.md`
- current runtime/state code in `src/brain_sync/`

**Purpose:** Review the revised runtime observability plan after the first
review, with specific attention to whether it now gives future agents a
brain-sync-native event contract, authoritative documentation homes, complete
interface coverage, and workable stale-daemon semantics.

---

## Review-1 Resolution Status

The key issues from the first review are resolved.

| ID | Prior issue | Resolution in revision 2 | Verified |
|---|---|---|---|
| C1 | Missing event taxonomy / placement rulebook | Added dedicated event contract section plus required `docs/architecture/OBSERVABILITY.md` | Yes |
| C2 | Incomplete doc/schema obligations | Added explicit `SCHEMAS.md`, `GLOSSARY.md`, spec-index, and architecture responsibilities | Yes |
| S1 | MCP coverage blind spot | Added MCP as first-class origin and dedicated interface instrumentation phase | Yes |
| S2 | Stale-daemon model undefined | Added heartbeat cadence, stale threshold, reader-facing state model, and startup recovery rules | Yes |
| M1 | Identity mapping not explicit | Added canonical mapping for `knowledge_area`, `synced_source`, and daemon sessions | Yes |

---

## Findings

No blocking findings.

The revised plan now does the main thing the first version did not: it turns
runtime observability into a governed contract rather than just a table-addition
exercise. The split between:

- runtime schema in `docs/brain-format/SCHEMAS.md`
- shared terms in `docs/brain-format/GLOSSARY.md`
- event policy and future-extension guidance in
  `docs/architecture/OBSERVABILITY.md`

is clear and matches the repository's documentation authority model.

The revised workstreams also line up much better with the actual code seams:

- daemon lifecycle and snapshot work in `state.py` / `__main__.py`
- reconcile semantics in `reconcile.py`
- regeneration queue semantics in `regen_queue.py` / `regen.py`
- interface coverage across both `cli/handlers.py` and `mcp.py`

That closes the biggest support and future-agent risks from the original plan.

---

## Advisory Notes

### A1. Reconciliation payloads should preserve the three current semantic outputs

This is not a blocking issue, but it is worth preserving during implementation.
The current reconcile path has three distinct semantic results in
`src/brain_sync/reconcile.py`:

- orphan state cleaned
- tracked knowledge-area content changed
- previously untracked knowledge area enqueued

The revised plan gives enough room to represent these via approved events plus
documented payload fields or reason types. The implementation should make sure
that support tooling can still distinguish those cases rather than collapsing
everything into a generic "reconciliation completed" summary.

### A2. Approval artifact should remain separate from this review

This review recommends approval, but it is **not** approval.

Per `docs/plans/README.md`, the next step is to create a separate approval
artifact named on the approved-plan pattern before implementation begins.

---

## What The Revision Gets Right

1. It explicitly requires the event contract before broad instrumentation,
   which is the right guardrail for future agents.
2. It uses brain-sync vocabulary and identity primitives instead of generic
   telemetry language.
3. It treats CLI and MCP as equally first-class interface origins.
4. It makes the stale-daemon model concrete enough for `status`, timeline, and
   export to converge on one interpretation.
5. It keeps the runtime event ledger in machine-local runtime state, aligned
   with the repo's current state-authority model.

---

## Verdict

Approval recommended.

Create `plan_runtime-observability_2_approved_<datetime>.md` before
implementation. This review artifact does not itself approve the plan.

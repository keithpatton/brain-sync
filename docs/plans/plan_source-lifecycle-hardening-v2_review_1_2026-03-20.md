# Review

Plan reviewed: `docs/plans/PLAN_source-lifecycle-hardening-v2.md`
Review date: 2026-03-20
Reviewer: Codex GPT-5

## Verdict

Changes required.

Create a new plan revision that resolves the blocking findings in this review.
This review artifact does not approve the plan and does not authorize
implementation.

## Blocking Findings

### 1. Lifecycle serialization still leaves key participating writes to implementer guesswork

The plan correctly says serialization must expand beyond move/finalization, but
it never converts that into an explicit participating-operation contract.
`lifecycle-affecting write paths that materially require it` is too open-ended
for an approval artifact, especially in a hardening closure round. The plan
names explicit remove and mentions watcher/reconcile participation, but it does
not state which same-source operations must acquire the lease, which must fail
or wait on an active lease, and which are only required to revalidate and abort
if a conflicting mutation wins first. A revision should enumerate the intended
lifecycle-affecting write set and the participation rule for each path so
review can tell whether serialization is fully closed rather than partially
improved.

### 2. Restart-safe finalization still does not choose a concrete freshness contract

The plan clearly identifies the inherited-history hole, but it still leaves the
enforcement mechanism optional. Saying docs/schema should be updated `if an
explicit epoch, owner, or confirmation freshness field is required` leaves the
core safety contract undecided. The acceptance criteria also rely on `predates
the current process epoch or attachment` without defining the exact predicate
that every implementation and test must share. A revision should require one
explicit current-process/session confirmation contract, including how the
runtime row proves freshness versus inherited history, so destructive
eligibility cannot be reintroduced through local heuristics.

### 3. Move conflict handling is directionally right but not yet a defined product contract

The plan says CLI/MCP move conflicts must be deterministic and must not leak
raw exceptions, but it never defines what deterministic means for users and
tests. There is no exact terminal result set, no CLI exit behavior, no MCP
payload contract, and no statement of whether `remove` conflict handling should
match the same pattern or intentionally differ. That leaves the implementer
choosing the user-facing behavior during execution instead of following an
approved contract. A revision should state the exact move conflict result
surface for CLI and MCP.

### 4. The event-proof contract is too vague to review and omits duplicate/best-effort semantics

The plan requires `operational_events` to prove ordering and terminal outcomes,
but it never names the minimum lifecycle/finalization event slice, the stable
fields tests may rely on, or the delivery semantics. As written, review cannot
tell whether tests should assert on exact event names, on generic event
categories, or on inferred outcomes. It also risks implying exact-once
behavior, even though the earlier notes explicitly frame the table as
non-authoritative operational history. A revision should name the minimum event
types and stable fields needed for overlap/restart proof and should say
explicitly that emission is best-effort and may duplicate, so tests prove
ordering/terminal outcome without depending on exact-once delivery.

### 5. Shared canonical-id validation is required in principle but not yet specified as one normative contract

The plan asks for a shared validator, but it does not define the canonical-id
contract that validator owns or which surfaces must use it. The current text
could still be satisfied by multiple thin wrappers around scattered heuristics,
or by a validator used only for finalization while other lifecycle commands
keep separate admission rules. A revision should name the owning contract and
state which CLI/MCP lifecycle surfaces must use it, along with the exact
failure behavior for invalid targeting.

## Non-blocking Suggestions

- Fold the minimum lifecycle/finalization event slice from
  `docs/plans/plan_source-lifecycle-hardening_9_notes.md` directly into the new
  revision so the proof contract lives in the plan rather than only in notes.
- Add one short implementation-boundary sentence stating whether lifecycle
  serialization is expected to be enforced exclusively at `sync/lifecycle.py`
  and `sync/finalization.py`, or whether any lower-level guard is also
  required.
- Tighten the test fortress wording by naming at least one dedicated
  integration or system test for shared canonical-id validation so the contract
  is exercised outside MCP alone.

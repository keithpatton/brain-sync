# plan_source-lifecycle-hardening_3 Review 1 - Changes Required

**Reviewer:** Codex GPT-5
**Date:** 2026-03-20
**Reviewed document:** `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md`
**Reviewed against:**
- `AGENTS.md`
- `docs/plans/README.md`
- `docs/RULES.md`
- `docs/GLOSSARY.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/brain/README.md`
- `docs/brain/SCHEMAS.md`
- `docs/runtime/README.md`
- `docs/runtime/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `README.md`
- `docs/plans/plan_source-lifecycle-hardening_review_1_2026-03-20.md`
- `docs/plans/plan_source-lifecycle-hardening_2_review_1_2026-03-20.md`
- `docs/plans/plan_source-state-boundary_2_approved_2026-03-19T19-05-47.md`
- `docs/plans/plan_source-fetch-hardening_2_approved_2026-03-18T11-00-51.md`
- current code reality in:
  - `src/brain_sync/sync/daemon.py`
  - `src/brain_sync/sync/pipeline.py`
  - `src/brain_sync/application/sources.py`
  - `src/brain_sync/application/source_state.py`
  - `src/brain_sync/application/sync_events.py`
  - `src/brain_sync/application/child_discovery.py`
  - `src/brain_sync/application/reconcile.py`
  - `src/brain_sync/application/doctor.py`
  - `src/brain_sync/interfaces/cli/handlers.py`
  - `src/brain_sync/interfaces/mcp/server.py`
  - `src/brain_sync/brain/manifest.py`
  - `src/brain_sync/brain/repository.py`
  - `src/brain_sync/runtime/repository.py`
  - `src/brain_sync/sources/base.py`
  - `src/brain_sync/sources/confluence/attachments.py`
  - `tests/unit/test_architecture_boundaries.py`

**Purpose:** Review revision 3 with a challenge-first standard, with special
focus on local explicit-finalization eligibility, cross-machine `missing`
determinism after portable `missing_since_utc` removal, `source_lifecycle_runtime`
row scope, elimination of old destructive doctor surfaces, closure of the
dedicated `finalize-missing` boundary across CLI and MCP, enforceability of the
zero `sync -> application` target and named orchestrator modules, concreteness
of the write-authority rule beyond generic import checks, documentation
alignment, anti-monolith package shape, and fortress-level test coverage.

---

## Verdict

Changes required.

Revision 3 is substantially stronger than revision 2. It now locks the target
version row, names the dedicated destructive entrypoints, defines a clearer
local-confirmation model, sharpens the admin-listing split, and gives `sync/`
a much more concrete target module map.

I am still withholding approval because three contract edges and one
documentation edge remain loose enough that implementation could drift:

- the plan adds a refusal condition of "stale" runtime coordination without
  defining what makes `source_lifecycle_runtime` stale
- the explicit-finalization ordering and failure model now conflict about
  whether anything still happens after manifest deletion
- the write-authority rule is still not concrete enough for the current
  boundary-test harness to enforce beyond broad import checks
- the required doc-update set still leaves authoritative entry points exposed
  to drift

This review artifact does **not** approve the plan and does **not** authorize
implementation. Create a new plan revision rather than editing
`plan_source-lifecycle-hardening_3_2026-03-20.md` in place.

---

## Critical Issues

### C1. The plan now requires finalization to reject "stale" runtime coordination, but it never defines what makes `source_lifecycle_runtime` stale

Revision 3 is much tighter on local eligibility than revision 2:

- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:390-414`
- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:768-770`
- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:807-810`

Those sections clearly define:

- row existence
- `missing_confirmation_count >= 2`
- fresh local revalidation
- no conflicting lease
- no first-observation-and-finalize in one invocation

But the entrypoint contract adds an extra rule:

- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:468-474`

It says explicit finalization must refuse when local runtime coordination is
"absent, insufficient, or stale." The plan never defines the stale case.
Nothing in the `source_lifecycle_runtime` schema, reducer rules, acceptance
criteria, or tests says whether staleness means:

- elapsed time since `local_missing_last_confirmed_utc`
- an expired or abandoned lease
- a row that predates a manifest rediscovery
- a row missing a fresh preflight confirmation
- or something else entirely

That matters because this plan intentionally removes the only old portable time
anchor (`missing_since_utc`) and replaces it with local runtime observation
history. Leaving a new "stale runtime coordination" concept undefined would
push destructive-policy invention back onto the implementer.

Required revision:

- either define the exact stale-runtime condition and how it is computed
- or remove that term from the finalization contract and rely only on the
  already-defined eligibility and fresh-revalidation rules
- update acceptance and test expectations accordingly

### C2. The explicit-finalization ordering and failure model now contradict each other about whether any cleanup may still occur after manifest deletion

Revision 3 is correctly trying to make manifest deletion the final destructive
step:

- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:657-672`

That section is crisp:

1. acquire lease
2. reload and revalidate
3. remove source-owned files
4. remove runtime coordination rows
5. delete the manifest last

It then states why deleting the manifest last is required for retry safety.

But the failure model later includes:

- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:695-700`

specifically:

- "crash after manifest deletion but before auxiliary runtime cleanup"

That creates a real sequencing contradiction. If the manifest must be deleted
last, there should not still be unspecified runtime cleanup after that point.
If there *is* post-delete cleanup, then manifest deletion is not actually the
last authoritative step and the restart model is no longer exact.

This is not a wording nit. It directly affects how an implementation proves the
plan's main safety guarantee in the face of interruption.

Required revision:

- make the ordering and failure model agree exactly
- either state that no authoritative cleanup remains after manifest deletion
- or enumerate the exact post-delete tail work that may remain and why it is
  non-authoritative and retry-safe

---

## Significant Issues

### S1. The write-authority rule is still not concrete enough beyond import checks for the current boundary-test harness

The plan is much better than revision 2 on target shape:

- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:498-567`
- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:573-591`
- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:781-783`

It now explicitly names:

- zero production `sync -> application` imports
- `sync/lifecycle.py` and `sync/finalization.py` as the orchestrators
- `sync/pipeline.py` as allowed to materialize but not own lifecycle state
- direct manifest-level mutation imports as forbidden outside `brain.repository`

That is directionally correct, but it is still not exact enough for the
existing enforcement style in
`tests/unit/test_architecture_boundaries.py:27-52`,
`tests/unit/test_architecture_boundaries.py:119-129`, and
`tests/unit/test_architecture_boundaries.py:473-515`.

Current architecture enforcement is mostly:

- package dependency allowlists
- file-level off-graph import allowlists
- forbidden direct imports from lower-level mutation helpers

Current code reality already has several legitimate `BrainRepository` imports
outside the planned orchestrators, including:

- `src/brain_sync/sync/pipeline.py:28`
- `src/brain_sync/application/doctor.py:37`
- `src/brain_sync/sources/confluence/attachments.py:11-12`

So "only lifecycle.py and finalization.py may drive portable source lifecycle
mutation through `brain.repository`" is still too semantic unless the plan also
says what exact testable boundary will distinguish:

- lifecycle mutation calls
- permitted materialization calls
- permitted diagnostic reads
- permitted attachment/file helpers

Without that, an implementer can satisfy the import graph while still leaving
write authority diffuse.

Required revision:

- define the exact static enforcement shape for write authority
- name the specific `BrainRepository` lifecycle-mutation methods that must be
  reserved to the approved orchestrator modules, or an equivalent exact rule
  that the architecture tests can encode
- state separately what `sync/pipeline.py`, doctor diagnostics, and
  `sources/confluence/attachments.py` may still call so the allowlist stays
  closed and auditable

### S2. The required doc-update set is still insufficient to keep authoritative entry points aligned

Revision 3 correctly requires updates to the major schema and cross-cutting
docs:

- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:143-152`
- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:165-202`

But under the repository's documentation-governance rules:

- `AGENTS.md:13-24`
- `AGENTS.md:58-74`

changing the portable contract requires updating `docs/brain/`, and changing
runtime schema requires updating `docs/runtime/`, not just selected schema
files.

That matters here because one of the authoritative entry points is already
stale today:

- `docs/brain/README.md:6-8` still says Brain Format `1.0` is current

and the runtime entry point is also part of the documented starting surface:

- `AGENTS.md:63-64`
- `docs/runtime/README.md:17-25`

Revision 3 also makes dedicated CLI and MCP finalization entrypoints official:

- `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:449-452`

but the required `README.md` updates only force:

- CLI `finalize-missing`
- removal/revision of destructive doctor references if they appear
- conditional MCP documentation updates only if an old doctor surface is shown

Current `README.md` does not list the destructive doctor mode, but it *does*
have user-facing CLI and MCP command/tool tables:

- `README.md:232-246`
- `README.md:255-270`

So the current wording would still allow the official new MCP tool to ship
without being added to the README's user-facing tool table.

Required revision:

- explicitly require updates to `docs/brain/README.md`
- explicitly require updates to `docs/runtime/README.md` if the runtime entry
  point needs to reflect the new `v27` lifecycle table and current row
- require `README.md` to document both official user-facing finalization
  surfaces: the CLI command and the MCP tool, not only CLI plus conditional MCP
  cleanup

---

## What Works

1. Revision 3 resolves the largest findings from revision 2. The local
   confirmation model, cross-machine inherited-`missing` rule, doctor-surface
   replacement, and anti-monolith `sync/` target are all materially sharper.
2. The split between active polling projection and administrative registry view
   is now exact enough and directly addresses the current `load_state()` /
   `list_sources()` gap in
   `src/brain_sync/application/source_state.py:34-53` and
   `src/brain_sync/application/sources.py:334-363`.
3. The plan now carries forward the sharp `stale` compatibility rule
   explicitly, including compatibility coverage:
   `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:346-348` and
   `docs/plans/plan_source-lifecycle-hardening_3_2026-03-20.md:831-842`.
4. The CLI/MCP closure around the old doctor destructive surfaces is much
   better than in revision 2 and is now close to approvable.

---

## Required Plan Changes

Before approval, revise the plan so it:

1. Defines or removes the newly introduced "stale runtime coordination"
   refusal condition for explicit finalization.
2. Makes the explicit-finalization ordering and failure model agree exactly
   about whether anything can still occur after manifest deletion.
3. Tightens the write-authority section so the architecture test suite can
   enforce it beyond generic import checks.
4. Expands the required documentation updates to cover the authoritative entry
   points under `docs/brain/`, `docs/runtime/`, and the README's MCP tool
   table.

---

## Conclusion

Revision 3 is close. The remaining blockers are no longer about the overall
direction of the lifecycle design; they are about the last few exactness gaps
that keep destructive behavior, architecture enforcement, and documentation
alignment from being completely unambiguous.

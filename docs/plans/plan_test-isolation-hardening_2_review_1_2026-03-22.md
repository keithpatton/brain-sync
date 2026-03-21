# plan_test-isolation-hardening_2 Review 1 - Validation Still Lands Too Late

**Reviewer:** Codex GPT-5
**Date:** 2026-03-22
**Reviewed document:** `docs/plans/plan_test-isolation-hardening_2_2026-03-22.md`
**Reviewed against:**
- `docs/plans/README.md`
- `AGENTS.md`
- `docs/plans/PLAN_test-isolation-hardening.md`
- current runtime and test harness code in `src/brain_sync/` and `tests/`

---

## Verdict

Changes required.

This revision improves the implementation shape materially. The phase boundaries
are much clearer than the root plan, and the intent to stop for proof between
workstreams is the right direction.

The remaining blockers are all in proof strength and completeness. As written,
the plan still allows later phases to proceed before the specific observed leak
pattern is re-proved closed in product code, relies on a manual caller audit
where future drift needs a durable guard, and defines fixture centralization too
narrowly to cover all current subprocess launch paths.

This review artifact does **not** approve the plan and does **not** authorize
implementation.

---

## Findings

### F1. Phase 1 still does not require proof that the observed no-session command-style leak is closed before later phases begin

The revision says Product Enforcement must come before test-harness cleanup and
that later phases should build on proof from earlier phases
([`plan_test-isolation-hardening_2_2026-03-22.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/plan_test-isolation-hardening_2_2026-03-22.md):76-100).
But the actual Phase 1 validation gate only requires targeted unit tests for
runtime safety and operational-event routing, plus a code audit that no
remaining modified product path uses the unsafe rootless seam
([`plan_test-isolation-hardening_2_2026-03-22.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/plan_test-isolation-hardening_2_2026-03-22.md):120-130).

That is weaker than the root problem statement and root-plan acceptance bar.
The observed leak shape was specifically command-style, with `session_id = NULL`
and `owner_id = NULL`
([`PLAN_test-isolation-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_test-isolation-hardening.md):35-53),
and the root plan already requires proof that this pattern fails closed plus at
least one subprocess regression for the same class of failure
([`PLAN_test-isolation-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_test-isolation-hardening.md):394-395,434-436).
This revision defers `no-session` and subprocess coverage to Phase 5
([`plan_test-isolation-hardening_2_2026-03-22.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/plan_test-isolation-hardening_2_2026-03-22.md):218-229),
which means caller migration and fixture work can proceed before the actual leak
pattern has been re-proved closed in product code.

That creates exactly the masking risk the phased rewrite is supposed to avoid:
later harness work could make the suite green without proving that a missed
isolation env var no longer leaks machine-local `operational_events`.

**Required revision:** Strengthen Phase 1 so its exit gate includes a direct
reproducer of the observed failure mode, not just generic unit coverage. At
minimum, Phase 1 should require proof that:

1. a temp or test root plus machine-local config/runtime still fails closed for
   brain-scoped operational-event writes
2. the same failure holds when `session_id` and `owner_id` are both absent
3. at least one command-style or subprocess-shaped path proves the enforcement
   seam itself, before fixture centralization starts

If the plan wants the broader fortress suite to remain in Phase 5, that is
fine, but the known leak signature cannot wait until the final phase.

### F2. Phase 2 uses a grep/audit checkpoint where the plan needs a durable anti-drift guard

Phase 2 correctly identifies a broad caller sweep across application, sync,
regen, and runtime helpers
([`plan_test-isolation-hardening_2_2026-03-22.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/plan_test-isolation-hardening_2_2026-03-22.md):132-154).
That matches current code reality: `record_operational_event(...)` is called
from application, sync, regen, and runtime code across many sites, not one or
two isolated helpers, including:

- [`src/brain_sync/application/local_files.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/application/local_files.py)
- [`src/brain_sync/application/query_index.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/application/query_index.py)
- [`src/brain_sync/application/sources.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/application/sources.py)
- [`src/brain_sync/regen/engine.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/regen/engine.py)
- [`src/brain_sync/regen/queue.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/regen/queue.py)
- [`src/brain_sync/sync/finalization.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/sync/finalization.py)
- [`src/brain_sync/sync/lifecycle.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/sync/lifecycle.py)
- [`src/brain_sync/sync/reconcile.py`](C:/Users/keith/source/repos/brain-sync/src/brain_sync/sync/reconcile.py)

The problem is the validation gate: "grep/audit confirms no remaining
brain-scoped caller uses the unsafe rootless event path"
([`plan_test-isolation-hardening_2_2026-03-22.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/plan_test-isolation-hardening_2_2026-03-22.md):144-148)).
That is an implementation-time check, not a durable guard against future drift.
The root plan's fortress expectations are stronger: rootless operational-event
usage should be forbidden or tightly bounded to explicitly machine-local
telemetry
([`PLAN_test-isolation-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_test-isolation-hardening.md):418-423).

With the current revision, an implementer could finish Phase 2 by manual audit,
then a later caller could silently reintroduce rootless brain-scoped event
writes without tripping an explicit repository-level safeguard.

**Required revision:** Add a concrete anti-drift mechanism to the Phase 2 or
Phase 5 scope and acceptance path. For example:

1. make the rootless API unavailable to brain-scoped callers by removal,
   narrowing, or a deliberately hostile name/signature
2. require an automated proof that any remaining rootless API is used only for
   explicitly machine-local telemetry
3. define the caller sweep against an explicit source-of-truth inventory, not
   only an ad hoc grep at review time

The revised plan does not need to prescribe the exact test implementation, but
it does need to require a durable guard stronger than "someone grepped it once."

### F3. Phase 3 centralization is not scoped broadly enough to cover the current bespoke subprocess paths

The Phase 3 goals are right, but the execution scope is still helper-centric:
it names `tests/conftest.py`, system/E2E/MCP helpers, and migration "toward"
the shared substrate
([`plan_test-isolation-hardening_2_2026-03-22.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/plan_test-isolation-hardening_2_2026-03-22.md):156-183)).
That misses current subprocess launch paths that are outside those helper files,
including:

- the direct subprocess regression in
  [`tests/system/test_cli_commands.py`](C:/Users/keith/source/repos/brain-sync/tests/system/test_cli_commands.py)
- the barriered daemon launcher in
  [`tests/e2e/test_db_contention.py`](C:/Users/keith/source/repos/brain-sync/tests/e2e/test_db_contention.py)

The root plan called out direct `subprocess.run()` drift as part of the current
risk surface
([`PLAN_test-isolation-hardening.md`](C:/Users/keith/source/repos/brain-sync/docs/plans/PLAN_test-isolation-hardening.md):155-160)).
As written, this revision could declare Phase 3 successful while those test-local
launchers remain bespoke and outside the shared model, even though they are
exactly the kind of path that can bypass isolation by accident.

**Required revision:** Expand Phase 3 so it explicitly inventories all current
subprocess/env-construction paths, not only the reusable helper modules. The
plan should require one of the following for every current exception:

1. migrate it onto the shared substrate
2. keep it bespoke only with a documented reason and explicit guard
3. add a durable validation check that rejects new ad hoc subprocess env
   builders outside the approved exceptions

Without that, the fixture-centralization phase is not complete enough to prove
that tests cannot touch live machine-local runtime or a live brain by default.

---

## Conclusion

This revision is close, but it is not yet ready for approval. Tightening the
Phase 1 proof to include the actual leak signature, replacing the Phase 2
manual audit with a durable anti-drift requirement, and broadening Phase 3 to
cover all current subprocess launch seams should make the next revision much
stronger.

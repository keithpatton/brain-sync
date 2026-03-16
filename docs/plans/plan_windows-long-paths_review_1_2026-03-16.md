# plan_windows-long-paths Review 1 - Strong Diagnosis, Two Scope Gaps To Close

**Reviewer:** Codex GPT-5
**Date:** 2026-03-16
**Reviewed document:** `docs/plans/PLAN_windows-long-paths.md`
**Reviewed against:**
- `docs/plans/README.md`
- `docs/brain-format/README.md`
- `docs/brain-format/RULES.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- current code in `src/brain_sync/fileops.py`
- current code in `src/brain_sync/fs_utils.py`
- current code in `src/brain_sync/pipeline.py`
- current code in `src/brain_sync/regen.py`
- current code in `src/brain_sync/reconcile.py`
- current code in `src/brain_sync/__main__.py`
- current code in `src/brain_sync/commands/doctor.py`
- current code in `src/brain_sync/commands/sources.py`

**Purpose:** Review the new Windows long-path correctness plan against the
portable brain contract, the planning workflow, and the current runtime/read
paths that would have to participate in any durable fix.

---

## Verdict

The plan has the right diagnosis and the right overall direction.

Treating this as a shared path-access bug instead of a `doctor`-only special
case is the correct architectural instinct, and reusing the existing
`win_long_path()` policy is a good constraint.

It is **not ready for approval as written**.

Two blocking issues remain:

1. the plan leaves watcher/reconciliation coverage as an open question even
   though the current runtime correctness path depends on those modules sharing
   the same filesystem view as doctor and regen
2. the plan does not yet lock down the outward path contract needed to prevent
   Windows-only `\\?\` forms from leaking into portable manifest state or
   user-visible diagnostics

---

## Critical Issues

### C1. Watcher and reconciliation coverage cannot remain optional if this is a shared read-correctness fix

`PLAN_windows-long-paths.md` correctly frames the defect as cross-cutting in
the fixed design decisions:

- lines 114-122 say this is not a doctor-only bug
- lines 145-149 say regen correctness should be restored from the same root
  cause

But the plan then leaves a major part of that same root cause unresolved as an
open question in lines 285-286:

> Do any existing watcher or reconciliation paths need the same treatment, or
> is doctor/regen/read-path coverage enough for the first fix set?

That should not stay open before approval.

In the current codebase, startup reconcile and live watcher handling are part
of the system's correctness path, not optional UX layers:

- `src/brain_sync/fs_utils.py` drives content discovery through
  `is_readable_file()`, `get_child_dirs()`, and `find_all_content_paths()`
- `src/brain_sync/reconcile.py` uses `find_all_content_paths()` and then
  `classify_folder_change()` to decide orphan cleanup and offline-change regen
  enqueueing
- `src/brain_sync/__main__.py` uses `classify_folder_change()` again for live
  watcher events before deciding whether to enqueue regen or treat an event as
  a rename-only change

If implementation fixes `doctor`, `extract_source_id()`, and selected regen
reads but leaves these runtime paths on ordinary `Path.is_file()` /
`Path.iterdir()` behavior, the daemon can still end up with a different view of
the same overlong file than doctor does. That risks continuing false dirty
detection, missed content discovery, or incorrect startup reconcile results on
Windows.

That is especially important in this repository because the architecture
document treats filesystem truth as authoritative and startup reconcile as a
correctness path, not cache warming.

**Recommendation:** Revise the plan so watcher/reconciliation treatment is no
longer optional. Either:

- explicitly include the `fs_utils.py -> reconcile.py -> __main__.py` path in
  scope for this change, or
- narrow the stated objective so it no longer promises shared read correctness

My recommendation is the first option. The current plan language already points
there.

### C2. The plan must explicitly preserve portable relative-path outputs while using long-path forms internally

The plan is strong on one important principle: lines 132-143 correctly insist
that manifest `materialized_path` remains authoritative portable state.

What is still missing is an explicit contract for how Windows-safe helpers are
allowed to surface paths back out to the rest of the application.

That matters because the authoritative docs require `materialized_path` to stay
portable and relative to `knowledge/`:

- `docs/brain-format/RULES.md` line 555:
  `Relative path from knowledge/ to local file`
- `docs/brain-format/SCHEMAS.md` line 56:
  `Relative path from knowledge/ to the materialized file`

The current code already shows why this needs to be nailed down in the plan:

- `src/brain_sync/fileops.py` says `rediscover_local_path()` returns a path
  relative to root, but its implementation currently returns the matched path
  object directly from `resolved_root.rglob(...)`
- `src/brain_sync/commands/doctor.py` then feeds that result into
  `update_manifest_materialized_path(..., normalize_path(new_path))` during
  `doctor --fix`
- `src/brain_sync/commands/sources.py` also expects rediscovered paths to be
  safe for `found.relative_to(knowledge_root)`

If the implementation starts rooting scans at `\\?\`-prefixed paths without an
explicit outward-path rule, it becomes easy to:

- write machine-local absolute paths into portable manifests
- leak `\\?\` paths into doctor drift messages
- create inconsistent contracts between `doctor`, `sources`, and future helper
  call sites

This is not theoretical. The current rediscovery seam is already close enough
to that boundary that a Windows-safe rewrite could accidentally codify the
wrong behavior.

**Recommendation:** Add a fixed design decision or acceptance criterion that
states all of the following:

- extended-length prefixes are an internal access mechanism only
- helpers may use `\\?\` forms internally for existence/read/glob operations
- any path returned across module boundaries must be converted back to the
  normal non-prefixed form expected by callers
- any path persisted to manifest fields must remain root-relative portable
  state under the existing Brain Format contract
- user-visible diagnostics must not print `\\?\` forms

Without that rule, the implementation could fix visibility while silently
damaging portability.

---

## What The Plan Gets Right

1. The diagnosis distinguishes the portable-manifest problem from the separate
   runtime-DB `regen_locks` drift issue, which is an important scoping
   clarification.
2. Reusing the existing Windows path helper is better than introducing a second
   policy surface.
3. The plan is right to reject any "fix" that weakens the manifest
   `materialized_path` contract.
4. The verification section is aimed at observable behavior rather than just
   helper-level implementation details.

---

## Recommended Plan Revision

Before approval, revise `PLAN_windows-long-paths.md` so it:

1. Resolves watcher/reconciliation coverage as a plan decision instead of an
   open question.
2. Names the concrete shared helper contract for outward-facing path values, so
   portable manifests and diagnostics never receive internal `\\?\` forms.
3. Updates workstreams and verification criteria to reflect those decisions.

---

## Approval Criteria For The Next Revision

I would approve the next revision if it:

- makes all correctness-critical readers share one Windows-safe filesystem view
- explicitly includes or deliberately narrows watcher/reconcile scope
- protects the Brain Format contract for `materialized_path`
- makes it impossible for internal long-path prefixes to leak into portable
  state or user-visible output

---

## Conclusion

The plan is close. The diagnosis is good, and the design direction is mostly
right.

What still needs tightening is the boundary definition:

- which runtime paths must participate in the same fix set
- which path forms are allowed internally versus externally

Approval is **not** recommended for the current plan revision. The planner
should create a revised plan artifact rather than editing
`PLAN_windows-long-paths.md` in place.

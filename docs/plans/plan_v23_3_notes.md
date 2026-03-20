# Plan v23.3 Implementation Notes

2026-03-20T18:15:39+13:00
Change: Closure review recorded for `plan_v23_3_approved_2026-03-15T06-47.md`; repository history indicates the approved v23 baseline landed and then received bounded cleanup.
Reason: Commit `9960867` on 2026-03-15 (`Implement Brain Format 1.0 runtime v23 baseline`) is the direct execution commit, with follow-up commits `0f4c1f0` on 2026-03-15 (`Align Brain Format docs and rename packaged templates`) and `4a8f13a` on 2026-03-16 (`Fix offline reconcile seeding for nested areas`) matching the implementation notes below.
Assumed completion date: 2026-03-16T00:32:50+13:00.
Status: Completed (inferred from git history).

2026-03-16T00:32
Change: Startup reconcile now enqueues the deepest newly contentful untracked areas so offline-created nested paths seed regen from the actual level of change.
Reason: Live watcher already starts from child paths and walks upward correctly; startup reconcile needed to match that behavior for offline edits.
Status: Implemented.

2026-03-15T22:34
Change: Packaged insight source files were renamed from `src/brain_sync/schemas/insights/` to `src/brain_sync/templates/insights/`.
Reason: These files are templates, not schemas, and the package layout now matches the glossary and reference terminology.
Status: Implemented.

2026-03-15
Change: Non-_core regen now uses _core summary only.
Reason: Token determinism and prompt pressure reduction.
Status: Implemented.

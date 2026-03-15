# Plan v23.3 Implementation Notes

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

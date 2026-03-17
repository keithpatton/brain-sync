# Plan runtime-observability.3 Implementation Notes

2026-03-17T12:35
Change: Use `plan_runtime-observability_3_approved_2026-03-16T15-57-33.md` as the implementation basis; the earlier revision 2 approval is superseded.
Reason: Revision 3 is the latest approved artifact and already carries forward the required reconciliation distinctions from `TreeReconcileResult`.
Status: Clarified.

2026-03-17T12:35
Change: Observability documentation and schema updates must follow the post-approval authority split: portable contract in `docs/brain/`, runtime schema in `docs/runtime/SCHEMAS.md`, shared vocabulary/versioning in `docs/GLOSSARY.md`, `docs/VERSIONING.md`, and `docs/COMPATIBILITY.md`, and event-contract guidance in `docs/architecture/OBSERVABILITY.md`.
Reason: The repository no longer uses the older `docs/brain-format/*` taxonomy referenced by the approved plan text.
Status: Clarified.

2026-03-17T12:35
Change: Portable-brain semantic instrumentation should target the `BrainRepository` seam and its direct semantic callers, with `manifest.py`, `sidecar.py`, and `fileops.py` treated as lower-level primitives rather than instrumentation boundaries. Runtime ledger persistence, runtime DB schema, and daemon snapshot work remain in `state.py` and other runtime-plane modules.
Reason: The repository now has an explicit portable-vs-runtime state boundary, including folder-move application, source-path healing, attachment cleanup, and journal-safe managed-area cleanup.
Status: Clarified.

2026-03-17T12:35
Change: Source lifecycle events such as source moved, source missing, and source reappeared are not yet fully centralized inside `BrainRepository`; the initial observability implementation should either add small repository-facing outcome types for those transitions or instrument `commands/sources.py` reconciliation as the temporary semantic authority rather than logging low-level manifest helper calls directly.
Reason: Current repository methods cover resolution and path synchronization, but missing/reappeared manifest-status transitions still live in the source reconciliation flow.
Status: Clarified.

2026-03-17T12:35
Change: Regeneration observability must preserve the newer portable-write discipline by keeping runtime lifecycle events attached to queue/lock/orchestration transitions and portable area-mutation events attached to durable repository or sidecar-persistence outcomes; event recording must not re-couple runtime-only transitions to portable sidecar rewrites.
Reason: Portable insight-state persistence and runtime regen lifecycle were separated after the plan approval, and the ledger work should build on that seam rather than undo it.
Status: Clarified.

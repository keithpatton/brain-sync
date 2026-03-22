# Plan operational-events-hardening 3 Implementation Notes

2026-03-22T18:05:11+13:00
Change: Post-review hardening added emitter-backed field-lock enforcement across the full locked catalog and strengthened the ownership guard to reject any non-repository string literal reference to `operational_events`.
Reason: The standard implementation review found the first proof pass too weak for acceptance criteria 8 and 10; these follow-up tests close the bypass gaps and prove the required-field contract across the real production emitter callsites and reviewed lifecycle paths.
Status: Completed.

2026-03-22T17:19:28+13:00
Change: Approved plan implementation completed in the working tree with catalog-backed event naming, repository-owned operational-event pruning, daemon startup wiring, enforcement tests, and the required doc updates.
Reason: This records material completion for the approved artifact and the validation slice that proved the hardening pass before handoff.
Status: Completed.

2026-03-22T17:19:28+13:00
Change: `application/sources.py` now emits one `source.updated` operational event per migrated source during legacy-context migration instead of one aggregate event without a canonical ID.
Reason: The approved field-lock matrix requires `source.updated` to keep row `canonical_id`; preserving that contract was more important than keeping an aggregate payload shape that could not identify a single source.
Status: Implemented.

2026-03-22T17:19:28+13:00
Change: The `reconcile.path_updated` event emitted on the missing-to-reappeared reconcile path now carries `details.old_path` and `details.new_path`.
Reason: The approved field-lock matrix requires those stable detail keys for `reconcile.path_updated` across current production emission paths, including rediscovery during reconcile.
Status: Implemented.

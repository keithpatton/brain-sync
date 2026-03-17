# Plan brain-repository 4 Implementation Notes

2026-03-17T16:05:00
Change: Portable-brain write mediation now routes normal runtime writes through `brain_repository.py`, with `state.py` narrowed to runtime-plane writes and compatibility wrappers.
Reason: Land the approved write-boundary correction before observability.
Status: Implemented.

2026-03-17T16:05:00
Change: The current explicit exception set for direct primitive portable writes is:
- `src/brain_sync/commands/init.py` for empty-brain bootstrap
- `src/brain_sync/state.py` migration code inside the v20 -> v21 upgrade block
- `src/brain_sync/pipeline.py` rootless fallback materialization path used outside normal runtime brain-root execution
Reason: Keep the temporary exception list explicit and small while avoiding a larger bootstrap/migration redesign in this pass.
Status: Clarified.

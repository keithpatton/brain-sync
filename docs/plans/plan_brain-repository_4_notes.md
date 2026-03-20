# Plan brain-repository 4 Implementation Notes

2026-03-20T18:15:39+13:00
Change: Closure review recorded for `plan_brain-repository_4_approved_2026-03-17T13-40-01.md`; git history indicates the approved repository-boundary work landed.
Reason: Commit `5b6f1d5` on 2026-03-17 (`Tighten portable write mediation behind brain repository`) aligns with the approved revision, and the earlier boundary-establishing commit `34d7b81` on 2026-03-17 (`Introduce brain repository boundary`) supplies the immediate execution context.
Assumed completion date: 2026-03-17T14:09:47+13:00.
Status: Completed (inferred from git history).

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

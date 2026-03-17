# Plan architecture-hardening.2 Implementation Notes

2026-03-17T21:45:00
Change: Child-discovery now lives in runtime table `child_discovery_requests` instead of manifests or `SourceState`.
Reason: Make `fetch_children` / `child_path` machine-local request state with one runtime owner while keeping Brain Format `1.0` unchanged.
Status: Implemented.

2026-03-17T21:45:00
Change: Shared regen, area-index lifecycle, and status reporting now route through `application/` entrypoints used by CLI and MCP.
Reason: Thin transport orchestration and give REGEN/query-facing workflows a narrower shared surface ahead of deeper subsystem refactors.
Status: Implemented.

2026-03-17T23:40:00
Change: Phase 2 review follow-up fixed disk-before-DB ordering for insight save/delete, made child-discovery requests truly one-shot, corrected co-located journal-path coverage, and added an explicit compat ratchet for supported `v23 -> v24` runtime DB migration.
Reason: Tighten the new application/runtime seam so the landed refactor matches the intended semantics, not just the package shape.
Status: Implemented.

2026-03-17T23:40:00
Change: Mixed-plane DTO ownership in `runtime/repository.py` (`SourceState`, `SyncState`, `InsightState`) remains deferred.
Reason: Phase 2 moved cross-plane composition into `application/`, but splitting or renaming those DTOs is a larger follow-up and would broaden this commit beyond the must-fix review findings. Treat as bounded debt for the next hardening pass / Phase 3 follow-up.
Status: Deferred.

2026-03-18T10:45:00+13:00
Change: Application-owned source and insight read models now live under `application/`, with callers and tests migrated to that seam; `runtime/repository.py` is narrowed to runtime persistence records and locks only.
Reason: Make cross-plane DTO ownership truthful so composed views are owned where composition actually happens, and remove the stale runtime-to-brain path-normalization debt at the same time.
Status: Implemented.

2026-03-18T10:45:00+13:00
Change: The documented transitional debt for mixed-plane DTO ownership was retired; remaining deferred hardening work is REGEN public-surface narrowing and the last sync-to-regen helper reach-throughs.
Reason: Phase 3 started by finishing the explicit Phase 2 deferment first, leaving the next bounded slice focused on REGEN/service boundary cleanup rather than state-model ownership.
Status: In progress.

2026-03-18T10:45:00+13:00
Checkpoint: Clean commit point reached after the Phase 3 DTO ownership slice.
Changed:
- added application-owned state models for merged source and insight views
- updated application workflows, daemon orchestration, and tests to use the new seam
- narrowed `runtime/repository.py` to runtime persistence records and locks
- retired the stale runtime-to-brain path-normalization boundary debt
Remains:
- narrow the public REGEN surface so callers stop depending on the broad `brain_sync.regen` barrel
- remove the remaining `sync/reconcile.py` and `sync/watcher.py` reach-through to regen helpers
- optionally land the child-request validation and daemon/MCP regression follow-ups noted below
Next agent:
- start with `src/brain_sync/regen/__init__.py`, `src/brain_sync/application/regen.py`, `src/brain_sync/regen/queue.py`, `src/brain_sync/sync/reconcile.py`, and `src/brain_sync/sync/watcher.py`
- keep ratcheting `tests/unit/test_architecture_boundaries.py` and the architecture doc as each transitional seam is retired
Status: Checkpoint ready.

2026-03-18T11:20:00+13:00
Change: Reviewer follow-up removed the application `SyncState.version` field so the merged read model no longer exposes runtime DB schema details, and added a direct daemon regression test for child-discovery consume-and-clear behavior.
Reason: Close the remaining misleading coupling to runtime schema versioning and ratchet the one-shot child-request lifecycle in the actual daemon path, not only at command/request setup time.
Status: Implemented.

2026-03-18T13:40:00+13:00
Change: Phase 4 began with new application-owned placement, local-file, and brain-browsing workflows; CLI add/add-file/remove-file and the MCP query/open/placement/file tools now route through `application/` entrypoints instead of reaching directly into `brain/`, `query/`, and source-title helpers.
Reason: Thin the transports around shared document-ingest and brain-browse policy so behavior changes land once in `application/` instead of being duplicated across CLI and MCP.
Status: Implemented.

2026-03-18T13:40:00+13:00
Change: Architecture boundary ratchet shrank the closed orchestration allowlists for `interfaces/cli/handlers.py` and `interfaces/mcp/server.py` to match the new thinner transport shape.
Reason: Phase 4 is only worthwhile if the reduced reach-through is enforced; the fitness test now locks in that MCP depends on `application/` plus runtime bootstrap concerns, and CLI no longer reaches directly into query/regen transport-adjacent helpers for placement/file workflows.
Status: Implemented.

2026-03-18T13:40:00+13:00
Checkpoint: Clean commit point reached after the first Phase 4 transport-thinning slice.
Changed:
- added `application/browse.py`, `application/local_files.py`, and `application/placement.py`
- rewired CLI add/add-file/remove-file to shared application workflows
- rewired MCP placement, local-file, query, context, area-open, and file-open tools to shared application workflows
- tightened `tests/unit/test_architecture_boundaries.py` to the thinner transport import sets
Remains:
- move more shared reconcile/reporting/source-management response shaping into `application/` where it meaningfully reduces remaining transport duplication
- decide whether the next slice should continue Phase 4 transport thinning first or resume the REGEN public-surface narrowing in parallel
- keep the existing sync-to-regen transitional debt limited to `sync/reconcile.py` and `sync/watcher.py` until the REGEN seam is narrowed intentionally
Next agent:
- start with `src/brain_sync/interfaces/cli/handlers.py`, `src/brain_sync/interfaces/mcp/server.py`, `src/brain_sync/application/sources.py`, `src/brain_sync/application/status.py`, and `src/brain_sync/application/reconcile.py`
- look for remaining response-assembly or request-normalization logic duplicated between CLI and MCP, especially around reconcile/status/source admin flows
- if you resume REGEN work instead, keep ratcheting `tests/unit/test_architecture_boundaries.py` as each transport or sync import is retired
Status: Checkpoint ready.

2026-03-18T14:20:00+13:00
Change: Interim review follow-up restored the CLI interactive add fallback to `"Untitled"` when URL title resolution yields nothing, introduced an application-owned `UnsupportedSourceUrlError`, and narrowed the `brain_sync.application` barrel to application-submodule re-exports only.
Reason: Preserve pre-slice CLI add behavior and make the Phase 4 transport-thinning ratchet truthful instead of allowing lower-level query/source concepts to hide behind the application barrel.
Status: Implemented.

2026-03-18T14:20:00+13:00
Change: Added a direct CLI regression test for the unresolved-title add path and a new architecture ratchet asserting that `brain_sync.application.__init__` re-exports only `application/*` submodules.
Reason: Lock in the review fixes so future Phase 4 work cannot silently reintroduce the CLI behavior regression or weaken the transport boundary through barrel exports.
Status: Implemented.

2026-03-18T14:35:00+13:00
Change: Review follow-up fixed the remaining CLI unsupported-HTTP-URL path so `check_source_exists()` raising `UnsupportedSourceUrlError` is handled inside `handle_add()` instead of bubbling out as an uncaught transport exception; added direct CLI regression coverage for that path.
Reason: Preserve the CLI's friendly unsupported-source handling across both the early duplicate-check path and the later add path.
Status: Implemented.

2026-03-17T22:17:43+13:00
Checkpoint: Stable commit point reached after Phase 2 review follow-up and external re-review.
Reached:
- Phase 1 is complete.
- Phase 2 is complete enough to commit with one explicit deferment: mixed-plane DTO ownership still lives in `runtime/repository.py`.
- Review-confirmed fixes now in place:
  - disk-before-DB ordering restored for application insight save/delete workflows
  - child discovery behaves as one-shot request state at the application seam
  - co-located journal preservation tests now exercise the real Brain Format `1.0` layout
  - compat suite now ratchets supported `v23 -> v24` runtime DB migration
- Full validation passed before commit:
  - `ruff check`
  - `pyright`
  - `python -m pytest -n auto -m "unit or integration or mcp" --timeout=30`
Notes for next agent:
- Start with Phase 3 hardening.
- Treat the deferred DTO ownership split as the first candidate slice of the next pass:
  - move or redefine merged view DTO ownership so `application/` owns composed read models more truthfully
  - then continue narrowing REGEN/public surfaces and remaining transport-to-lower-layer reach-through
- Non-blocking review follow-ups still open if desired:
  - make `runtime.child_requests.save_child_discovery_request()` reject invalid `child_path` + `fetch_children=False` calls instead of silently deleting
  - add explicit regression coverage for daemon consume-and-clear behavior and MCP invalid-child-request error mapping
Status: Checkpoint committed next.

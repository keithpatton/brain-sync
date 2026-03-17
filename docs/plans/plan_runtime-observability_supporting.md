# Runtime Observability Supporting Input

Portable brain IO audit completed on 2026-03-17 against the current `main`
branch after the `BrainRepository` introduction and portable/runtime
write-discipline changes.

This document is not a plan revision. It is supporting implementation context
for `plan_runtime-observability_3_approved_2026-03-16T15-57-33.md`.

## Purpose

Before adding the runtime event ledger, identify which filesystem IO paths are:

- legitimate at their current layer
- low-level primitives that should stay below the repository boundary
- portable brain mutation or semantic-read seams that should move behind
  `BrainRepository` so observability can instrument a smaller number of trusted
  boundaries

The highest-value target is **portable mutation centralization**. Read-only
query surfaces matter less for event emission and can remain outside the
repository when they are simple presentation/query code.

## Recommended Rule Tightening

The current repository rule is directionally correct, but still too easy to
read as "use `BrainRepository` for some managed operations" rather than "use it
for all portable-brain semantic mutation."

Recommended long-lived rule:

1. Any mutation of portable brain state under the brain root must either:
   - go through `BrainRepository`, or
   - be a documented exception for bootstrap/import-export/test harness work.
2. `fileops.py`, `manifest.py`, and `sidecar.py` are primitive modules. Command,
   daemon, pipeline, regen, watcher, and repair code should not call their
   portable mutation helpers directly when a repository-level operation is the
   real semantic action.
3. Runtime-plane modules must not become portable-state owners. In particular,
   `state.py` should not grow new manifest or sidecar mutation responsibilities
   beyond narrow migration/bootstrap exceptions.

## Classification Criteria

### Legitimate current-layer IO

Use this classification when the IO is one of:

- runtime-only state under `~/.brain-sync/`
- low-level reusable primitive code below the repository boundary
- user-supplied import/export or local utility work outside managed portable
  semantics
- read-only query/presentation code that does not define portable-brain
  semantic authority
- watcher edge-observation behavior that does not itself define convergence
  semantics

### Should move behind `BrainRepository`

Use this classification when the IO performs or defines:

- source manifest lifecycle
- source missing/reappeared transitions
- source-owned file movement or cleanup
- managed attachment lifecycle under `knowledge/**/.brain-sync/`
- summary/journal/sidecar persistence or cleanup
- portable repair/convergence behavior
- semantic classification of filesystem reality that later observability should
  emit once at a trusted boundary

## Audit Summary

### Already legitimate at current layer

| Cluster | Classification | Reason |
|---|---|---|
| `src/brain_sync/fileops.py` | Primitive layer | Explicit low-level filesystem helper module |
| `src/brain_sync/manifest.py` | Primitive layer | Explicit low-level manifest serializer/store |
| `src/brain_sync/sidecar.py` | Primitive layer | Explicit low-level insight-state serializer/store |
| `src/brain_sync/config.py`, `src/brain_sync/logging_config.py`, runtime parts of `src/brain_sync/state.py` | Legitimate runtime IO | Machine-local runtime/config/daemon/DB ownership |
| `src/brain_sync/commands/init.py` brain bootstrap and skill install paths | Legitimate exception | Bootstrap/setup work, not ongoing portable semantic authority |
| `src/brain_sync/commands/placement.py`, `src/brain_sync/docx_converter.py` | Legitimate utility IO | Reads user-provided local files for placement/conversion |
| Read-only query surfaces such as `src/brain_sync/area_index.py` and read-only parts of `src/brain_sync/mcp.py` | Legitimate read-side IO | Presentation/query code, not mutation authority |
| `src/brain_sync/watcher.py` raw observation checks | Legitimate edge IO | Watcher may observe filesystem directly; semantic follow-up should still centralize |
| CLI/MCP support export or local file copy helpers outside the brain root | Legitimate interface IO | User handoff/export behavior, not managed portable state |

### Portable mutation seams that should move behind `BrainRepository`

| Cluster | Current behavior | Why it should move |
|---|---|---|
| `src/brain_sync/commands/sources.py` | Direct manifest writes/deletes, direct missing/reappeared transitions, direct folder moves, direct attachment-dir moves, direct target-dir creation | This module still owns real source lifecycle semantics instead of only orchestrating repository outcomes |
| `src/brain_sync/pipeline.py` | Direct target-dir creation, direct managed markdown write via `write_if_changed()`, direct duplicate managed-file cleanup, direct manifest `sync_hint` update | Materialization is a semantic repository action and should become one eventable boundary |
| `src/brain_sync/attachments.py` | Direct managed attachment writes and legacy attachment migration moves/deletes | Managed attachment lifecycle is portable managed state under the repository plan |
| `src/brain_sync/regen.py` | Direct summary write, direct sidecar cleanup path, direct insight cleanup orchestration | Summary/journal/sidecar persistence is one of the explicit seams we want evented centrally |
| `src/brain_sync/state.py` portable helpers | `save_portable_insight_state()`, `delete_insight_state()`, `clear_children_flag()` mutate sidecars/manifests from the runtime-plane module | Violates the now-explicit portable/runtime split and weakens a clean event boundary |
| `src/brain_sync/commands/doctor.py` portable fixes | Direct manifest normalization writes and direct manifest deletion paths remain in doctor | Repair paths should use the same repository-owned portable semantics as mainline flows |

### Mixed / policy choice

| Cluster | Classification | Rationale |
|---|---|---|
| `src/brain_sync/cli/handlers.py` add/remove local file under `knowledge/` | Legitimate for now, optional later centralization | These are direct user file-management commands rather than managed state semantics, but if the product goal becomes "all portable mutations emit through one seam", repository helpers for import/delete would help |
| `src/brain_sync/mcp.py` add/remove file under `knowledge/` | Legitimate for now, optional later centralization | Same reasoning as CLI add/remove file; interface eventing may be sufficient even without repository ownership |

## High-Priority Gaps Before Observability

These are the biggest centralization gaps if the immediate goal is "event all
portable brain activity in one place."

### 1. Source lifecycle is still split

`commands/sources.py` still directly performs:

- source registration manifest creation
- source removal manifest deletion
- missing marking
- missing clearing / reappeared transition
- second-stage deletion for still-missing sources
- manual manifest fallback writes during moves

This is the most important remaining gap for source-level eventing such as:

- `source.moved`
- `source.missing`
- `source.reappeared`
- `source.deleted`

### 2. Materialization writes are not yet repository-owned

`pipeline.py` still owns the portable write of the managed markdown file and
duplicate-file cleanup, while only part of the manifest update uses the
repository.

If observability lands first without closing this, materialization events will
still need to hook multiple call sites.

### 3. Area-state persistence is still split across regen/state/sidecar

The runtime/portable split improved recently, but the code seam is still not a
single repository-owned area-state API.

Current split:

- `regen.py` writes `summary.md`
- `state.py` writes/deletes portable insight-state sidecars
- `BrainRepository` appends journals and cleans regenerable artifacts

This is good enough to continue functioning, but not yet the single portable
mutation seam implied by the repository direction.

### 4. Doctor still has direct portable mutation paths

Doctor now uses `BrainRepository` for several repairs, but some manifest
normalization and deregistration actions still mutate portable state directly.

That means observability would otherwise need special-case doctor event hooks
instead of inheriting repository outcomes.

## Suggested Pre-Observability Cleanup Order

If the goal is to maximize central event emission before the ledger work, the
best order is:

1. Close source lifecycle transitions under `BrainRepository`.
2. Add repository-owned materialization commit operations for synced markdown
   plus attachment lifecycle.
3. Add repository-owned area-state persistence operations for summary, journal,
   sidecar, and cleanup.
4. Move doctor portable repairs onto those same repository operations.
5. Then add runtime event emission at repository and runtime-plane boundaries.

## Practical Implementation Guidance

Observability does not need every read path centralized first.

The important thing is to centralize **semantic portable mutations** and
runtime lifecycle transitions. If those become trusted seams, the first event
ledger can stay small and stable.

Until that cleanup is complete, instrumentation should prefer:

- `BrainRepository` methods where they already exist
- source reconciliation in `commands/sources.py` as the temporary semantic
  source-lifecycle boundary
- runtime-plane lifecycle methods in `state.py` for daemon/runtime DB events

Instrumentation should avoid:

- direct event emission in `manifest.py`
- direct event emission in `sidecar.py`
- direct event emission in `fileops.py`

Those modules are too low-level and would turn the ledger into an IO trace
instead of a semantic history.

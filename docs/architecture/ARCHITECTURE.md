# Architecture

This document explains the current brain-sync system architecture.

Use it for design intent, module responsibilities, state models, rationale,
and technical debt. For the normative portable contract, see
`docs/brain-format/`. Dependency direction rules are defined in `AGENTS.md`.

---

## 1. System Structure

All source lives under `src/brain_sync/`.

| Group | Modules | Purpose |
|---|---|---|
| Entry points | `__main__`, `mcp` | Daemon loop and MCP stdio server |
| Commands / CLI | `commands/`, `cli/` | User-facing operations and CLI wiring |
| Sync pipeline | `pipeline`, `converter`, `docx_converter`, `sources/` | Fetch, convert, materialize, and update source content |
| Source adapters | `sources/base`, `sources/registry`, `sources/confluence/`, `sources/googledocs/` | Per-source fetch logic behind the adapter protocol |
| REST clients | `confluence_rest` | Confluence REST API wrapper used by adapters and attachment flows |
| LLM abstraction | `llm/base`, `llm/claude_cli`, `llm/fake` | Backend protocol, production transport, deterministic fake |
| Regen | `regen`, `regen_lifecycle`, `regen_queue` | Deterministic insight regeneration and queueing |
| State | `state`, `token_tracking` | Runtime DB access, daemon status, and telemetry |
| Layout helpers | `layout` | Centralized path and version helpers for Brain Format `1.0` |
| Manifests | `manifest` | Source manifest read/write under `.brain-sync/sources/` |
| Sidecars | `sidecar` | Per-area insight state read/write under `knowledge/**/.brain-sync/insights/` |
| Attachments / indexing | `attachments`, `area_index` | Attachment storage and area search indexing |
| Utilities | `config`, `fileops`, `fs_utils`, `logging_config`, `retry`, `scheduler` | Shared helpers with no domain coupling |
| Watcher | `watcher` | Filesystem event monitoring and path-update coordination |
| Reconcile | `reconcile` | Startup filesystem reconciliation against manifest and regen state |

---

## 2. Module Responsibilities

**Utilities** are low-level helpers. `config.py` is the canonical source for
the user-level config directory, config file, runtime DB path, and daemon
status path.

**Core modules** implement sync, reconciliation, and regeneration. The sync
pipeline fetches and materializes source content into `knowledge/`. Regen
produces derived summaries, journals, and per-area insight state from the
knowledge tree.

**Interfaces** expose the system to users and tools. The CLI commands operate
on the same core modules as the MCP tools. The watcher provides online change
detection; reconciliation provides the equivalent correction path for offline
changes.

**Entry points** wire everything together. `__main__.py` runs the daemon loop;
`mcp.py` exposes repository-safe tool access over stdio.

### Startup Reconcile Lifecycle

When `brain-sync run` starts, it reconciles filesystem truth before entering
the normal sync loop:

```text
reconcile_sources()        -> manifest-driven file resolution and missing-source handling
reconcile_knowledge_tree() -> regen-state cleanup and offline content-change detection
load_state()               -> manifest-authoritative merge with runtime progress cache
regen_session()            -> acquire regen ownership
RegenQueue()               -> enqueue reconciled paths
watcher.start()            -> begin filesystem monitoring
sync loop                  -> normal operation
```

`reconcile_knowledge_tree()` compares the live `knowledge/` tree with
per-area insight state and `regen_locks` rows:

1. prune rows for deleted areas
2. detect offline content changes for tracked areas
3. enqueue newly relevant areas when filesystem state implies regen work

Because v23 co-locates managed area state under `knowledge/<area>/.brain-sync/`,
folder moves carry summaries and attachment directories with them
automatically. The system repairs manifests and runtime state, but no longer
maintains a separate top-level insight mirror.

### Ownership Model

| Layer | Owner | Responsibility |
|---|---|---|
| `knowledge/` plus source manifests plus `sync_cache` | sync / reconcile / watcher | Source-of-truth document locations and durable registration intent |
| `knowledge/**/.brain-sync/insights` plus journals plus per-area attachments plus `regen_locks` | regen | Derived meaning and regen coordination |
| `~/.brain-sync/` runtime DB and daemon status | runtime | Machine-local cache, telemetry, and process state |

The filesystem remains authoritative. Runtime state is disposable and must be
rebuildable from manifests and per-area insight state.

### Attachment Storage

Attachments are stored inside each area's managed subtree:

```text
knowledge/area/
  c12345-page.md
  .brain-sync/
    attachments/
      c12345/
        a67890-diagram.png
```

This per-source directory isolation is the key v23 simplification. Attachments
move with their area, and removing a source's attachments is a simple
directory cleanup rather than a relationship-tracking exercise.

### Architectural Principles

**Import purity**: modules may define constants and helpers at import time, but
must not resolve environment-dependent runtime state during import.

**Single managed namespace**: `.brain-sync/` is the only reserved managed
namespace. Code that walks the knowledge tree must consistently exclude it from
readable-content discovery and hashing.

**Manifest-authoritative registration**: manifests are the durable record of
what sources exist; runtime tables only cache progress and coordination.

**Co-located managed state**: area summaries, insight state, journals, and
attachments live with the area they describe. That removes the old mirror-tree
coupling.

### LLM Backend Abstraction

All LLM invocations go through `LlmBackend.invoke()` in `llm/base.py`.

- `ClaudeCliBackend` is the production backend.
- `FakeBackend` is the deterministic test backend.

Backend resolution happens at regen entry points and is then threaded through
the call chain. Telemetry is recorded alongside backend results but is not part
of the backend protocol itself.

### Source Adapter Pattern

The sync pipeline is source-type-agnostic. Source-specific behavior lives under
`src/brain_sync/sources/<type>/`.

Key abstractions:

- `SourceAdapter`
- `SourceCapabilities`
- `UpdateCheckResult`
- `SourceFetchResult`
- `AuthProvider`

This lets shared modules materialize, place, reconcile, and remove sources
without branching on provider-specific behavior.

---

## 2.5. State Authority Model

### Authority Hierarchy

The system uses a tiered authority model:

| State class | Authoritative location | Portable | Rebuildable |
|---|---|---|---|
| Source registration intent | `.brain-sync/sources/*.json` | Yes | No |
| Source sync freshness hint | manifest `sync_hint` plus `sync_cache` | Hint yes, DB no | Yes |
| Insight hashes | `knowledge/**/.brain-sync/insights/insight-state.json` | Yes | Yes |
| Regen lifecycle | `regen_locks` | No | Yes |
| Token telemetry | `token_events` | No | Loss accepted |
| Runtime DB schema marker | `meta` | No | Yes |

Portable state lives in the brain root. Runtime state lives under the user
config directory and may be deleted without invalidating the brain.

### Managed-File Identity

Materialized synced documents carry YAML frontmatter identity:

```yaml
---
brain_sync_source: confluence
brain_sync_canonical_id: confluence:123456
brain_sync_source_url: https://acme.atlassian.net/wiki/spaces/ENG/pages/123456
---
```

Reconciliation uses a three-tier resolution chain:

1. manifest `materialized_path`
2. frontmatter identity scan
3. canonical-prefix filename fallback

Readers may still tolerate legacy HTML comment markers as a fallback, but new
writes use YAML frontmatter only.

### Source Manifests

Each synced source has a manifest at `.brain-sync/sources/<source_dir_id>.json`.

v23 durable fields:

- `version`
- `canonical_id`
- `source_url`
- `source_type`
- `materialized_path`
- `target_path`
- `sync_attachments`
- `status`
- optional `missing_since_utc`
- optional `sync_hint`

Operational one-shot flags such as `fetch_children` and `child_path` are no
longer part of the durable manifest contract.

### Brain Control Plane

The portable brain root contains:

```text
{brain_root}/
  .brain-sync/
    brain.json
    sources/
  knowledge/
```

The runtime DB and daemon status are intentionally outside the brain root:

```text
~/.brain-sync/
  config.json
  daemon.json
  db/brain-sync.sqlite
```

That separation is what keeps the brain root fully portable and safe to commit.

### DB Table Justifications

v23 runtime DB tables:

| Table | Purpose | If deleted |
|---|---|---|
| `meta` | Runtime schema marker | Recreated |
| `sync_cache` | Polling schedule and sync progress cache | Rebuilt from manifests and sync hints |
| `regen_locks` | Cross-process regen coordination | Reset to idle |
| `token_events` | Local telemetry history | History lost only |

### Startup Tree Walk

The startup reconciliation walk is a correctness path, not cache warming. Its
job is to bring runtime state back into agreement with filesystem truth after
offline changes.

---

## 3. Known Technical Debt

**Watcher edge cases**: Windows symlink handling and rapid sequential move
events still need hardening.

**Regen complexity**: `regen.py` remains one of the largest modules and is a
candidate for further decomposition.

**AreaIndex staleness model**: `AreaIndex.is_stale()` is still a best-effort
performance hint rather than a full correctness proof.

### Derived State Inventory

| View | Source of truth | Owner | Refresh trigger | Correctness role |
|---|---|---|---|---|
| Global context cache | `knowledge/_core/` | `regen.py` | invalidated on `_core` changes | Correctness-critical |
| AreaIndex | `knowledge/**/.brain-sync/insights/summary.md` plus `knowledge/` structure | `BrainRuntime` | staleness check before queries | Performance-only |

### Resolved (2026-03)

- Config and runtime-path helpers are centralized in `config.py` and `layout.py`.
- `regen.py` no longer imports from command-layer modules.
- Manifests are the authoritative durable registration layer in v23.
- Atomic file writes use fsync-based crash-safe behavior.
- `mcp.py` runtime state moved out of import-time globals.
- `AreaIndex` was extracted from the entrypoint layer into `area_index.py`.
- Public state APIs replaced several direct command-layer uses of private DB helpers.
- Deterministic `FakeBackend` support reduced subprocess overhead in tests.

---

## 3.5. Telemetry

### Three Independent State Systems

| System | Location | Purpose | Lifetime |
|---|---|---|---|
| Content state | `knowledge/**/.brain-sync/insights/insight-state.json` | Content, structure, and summary hashes | Durable |
| Concurrency lock | `regen_locks` | Regen ownership and recovery | Transient |
| Invocation telemetry | `token_events` | Append-only LLM accounting | Local history |

`session_id` groups related regen calls for usage analysis. `owner_id` is the
cross-process lock identity. They serve different purposes even when their
lifetimes often align.

Telemetry is workflow-agnostic via `resource_type` and `resource_id`.

---

## 4. Hardening Roadmap

Planned future work:

1. improve `AreaIndex` staleness detection
2. split `regen.py` into smaller focused modules
3. harden watcher event handling further
4. narrow broad exception handling where safe

---

## 5. Private Cross-Module Imports

### Production code

| Symbol | Consumer | Notes |
|---|---|---|
| `scheduler._scheduled_keys` | `__main__.py` | Attribute access, not import |
| `commands.context._require_root` | `commands/sources.py` | Intra-package use |
| `confluence_rest._request` | `sources/confluence/comments.py` | Reuses retry behavior |

### Test code

| Symbol(s) | Consumer |
|---|---|
| `state._connect` | Selected unit tests |
| selected private `regen.py` helpers | `tests/unit/test_regen.py` |

Tests may validate private helpers directly. Production code should avoid
growing new cross-module private coupling.

---

## 6. Maintenance

This document should remain concise and explanatory.

It should be updated whenever module responsibilities, authority models,
dependency direction, or major structural constraints change.

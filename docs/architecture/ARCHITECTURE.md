# Architecture

This document is the canonical description of the brain-sync system architecture.
It defines module structure, responsibilities, known technical debt,
and the intended hardening direction of the system.

Both human contributors and AI agents should treat this document
as the authoritative architectural reference for the repository.

---

## 1. System Structure

All source lives under `src/brain_sync/`.

| Group | Modules | Purpose |
|---|---|---|
| Entry points | `__main__`, `mcp` | Daemon loop, MCP stdio server |
| Commands / CLI | `commands/`, `cli/` | User-facing operations (add, add-file, remove, remove-file, list, move, init) |
| Sync pipeline | `pipeline`, `converter`, `docx_converter`, `sources/` | Fetch, convert, and write knowledge files |
| Source adapters | `sources/base`, `sources/registry`, `sources/confluence/`, `sources/googledocs/` | Per-source fetch logic behind `SourceAdapter` protocol |
| REST clients | `confluence_rest` | Confluence REST API wrapper (used by adapter + attachments) |
| Regen | `regen`, `regen_lifecycle`, `regen_queue` | Deterministic insight regeneration (leaf → ancestor) |
| State | `state`, `token_tracking` | SQLite WAL persistence (sources, documents, relationships, insight state, token events) |
| MCP | `mcp` | FastMCP tool interface over stdio |
| Attachments | `attachments`, `area_index` | Attachment sync lifecycle, area indexing |
| Utilities | `config`, `fileops`, `fs_utils`, `logging_config`, `retry`, `scheduler` | Shared helpers with no domain coupling |
| Watcher | `watcher` | Filesystem event monitoring, insight folder mirroring |

Dependency direction rules are defined in `CLAUDE.md`.

---

## 2. Module Responsibilities

**Utilities** — stateless helpers: path operations, logging setup, retry logic, scheduling. No domain knowledge. `config` is the canonical source for `CONFIG_DIR`, `CONFIG_FILE`, `load_config()`, and `save_config()` — all config access must go through this module.

**Core modules** — domain logic: sync pipeline fetches and converts sources; regen produces insights from knowledge; state persists all sync and regen metadata in SQLite. Journal entries are generated alongside summaries via structured XML output. Journal writing is independent of the summary similarity guard — temporal events are recorded even when the summary abstraction doesn't change. Controlled by `write_journal` config flag.

**Interfaces** — MCP server exposes brain operations as tools over stdio; watcher monitors the filesystem and queues regen work.

**Commands / CLI** — orchestrate core modules into user-facing operations. Commands are the public API consumed by both CLI handlers and MCP tools. Two command families: **sync source management** (`add`/`remove`/`list`/`update`/`move`) for URL-based sources tracked in the database, and **file management** (`add-file`/`remove-file`) for local `.md`/`.txt` files placed directly in knowledge/ with no DB tracking. Includes `commands/placement.py` for document placement suggestions and filename helpers (used by both MCP tools and CLI commands).

**Entry points** — `__main__` runs the daemon loop; `mcp` runs the FastMCP stdio server. Both wire together commands, scheduling, and interfaces.

### Startup Reconcile Lifecycle

When `brain-sync run` starts, it reconciles offline filesystem changes before entering the sync loop:

```
reconcile_sources()  → scan knowledge/ for moved ID-anchored files, update sources.target_path
load_state()         → read corrected DB state
regen_session()      → acquire regen ownership
RegenQueue()         → create queue, enqueue reconciled paths
watcher.start()      → begin filesystem monitoring (after reconcile to avoid spurious events)
sync loop            → normal operation
```

**Ownership model:**

| Layer | Owner | Responsibility |
|---|---|---|
| `knowledge/` + `sources` table | sync / reconcile / watcher | Source-of-truth document locations |
| `insights/` + `insight_state` table | regen | Derived artifacts from knowledge |

Reconcile is a pure state-repair operation — it only updates `sources.target_path` in the DB. Regen detects path changes on its next run and rebuilds insights at the correct locations, cleaning up orphaned `insight_state` entries.

### Attachment Storage

Attachments (binary files downloaded alongside a synced source) are stored at area level under `_attachments/{page_id}/`. The `_attachments` directory is reserved — it is excluded from content discovery, regen, and watching (listed in `EXCLUDED_DIRS` alongside `_core`).

```
knowledge/area/
  _attachments/
    c12345/                    ← keyed by canonical prefix (stable, collision-safe)
      a67890-diagram.png
  c12345-gap-analysis.md
```

Path computation is centralised in `attachments.attachment_local_path()` — used by sync, remove, move, and inline `attachment-ref:` resolution.

### Architectural Principles

**Import purity** — Modules may define behavior at import time, but must not resolve environment-dependent runtime state at import time. Filesystem access, config resolution, and index construction must be deferred to explicit startup/lifespan hooks.

**MCP runtime ownership** — `BrainRuntime` is the single owner of MCP process state (root path, area index, concurrency locks). Module-level variables in `mcp.py` must remain pure definitions (constants, helper functions, tool registrations). Any variable whose value depends on filesystem state, configuration, or runtime execution must live in `BrainRuntime`. Future contributors adding new runtime state (connections, caches, locks) must add it to `BrainRuntime`, not as a new module global.

### Source Adapter Pattern

The sync pipeline uses a `SourceAdapter` protocol (`sources/base.py`) to abstract per-source fetch logic. Each source type (Confluence, Google Docs) implements the protocol as a package under `sources/`.

```
sources/base.py        — SourceAdapter protocol, AuthProvider protocol, shared dataclasses
sources/registry.py    — Lazy dict registry: get_adapter(SourceType) → SourceAdapter
sources/confluence/    — ConfluenceAdapter (wraps confluence_rest.py)
sources/googledocs/    — GoogleDocsAdapter (native OAuth2 via browser consent, HTML export)
```

**Key abstractions:**
- `SourceCapabilities` — declares what a source supports (version check, comments, attachments, children)
- `UpdateCheckResult` — cheap pre-fetch check; `adapter_state` passes opaque data to `fetch()` to avoid duplicate API calls
- `SourceFetchResult` — full fetch result with markdown, comments, title, optional source HTML
- `AuthProvider` — per-source auth (Confluence: config/env credentials; Google Docs: native OAuth2 via browser consent)

**Pipeline orchestration:** `pipeline.process_source()` is source-agnostic. It calls `get_adapter()`, gates behaviour on `capabilities`, and delegates fetch/check to the adapter. Attachment sync is gated by `supports_attachments`; child discovery by `supports_children`.

**Registry:** Lazy instantiation with no startup wiring. Adapters are created on first access and cached. `reset_registry()` available for testing.

---

## 3. Known Technical Debt

**Watcher edge cases** — Windows symlink handling and rapid sequential move events are not fully robust.

**Regen complexity** — `regen.py` is the largest module with many private helpers; candidates for extraction exist.

**AreaIndex staleness model** — `AreaIndex.is_stale()` only checks `insights/**/summary.md` mtimes, but the index depends on more: knowledge file presence, directory structure, children changes. The index can be stale without `is_stale()` detecting it. This is a performance hint, not an authoritative freshness contract. Next MCP correctness debt item.

### Derived State Inventory

| View | Source of Truth | Owner | Refresh Trigger | Correctness Role |
|---|---|---|---|---|
| Global context cache | `knowledge/_core/`, `schemas/`, `insights/_core/` files | `regen.py` | `invalidate_global_context_cache()` — called by watcher on `_core/` changes and by daemon on `_core/` sync | Correctness-critical (stale cache → regen uses wrong context) |
| AreaIndex | `insights/**/summary.md` + `knowledge/` structure | `BrainRuntime` (MCP) | `is_stale()` mtime check before each query | Performance-only (stale index → search misses, not data corruption) |

### Resolved (2026-03)

- **Config duplication** — all config constants and I/O centralised in `config.py`; consumers import from there (Phase B)
- **Dependency direction violations** — `regen.py` no longer imports from `commands.context` (Phase B/C)
- **Dead v1 manifest system** — `manifest.py` and related test code removed; v2 uses SQLite state exclusively (Phase E)
- **Silent exception swallowing** — retry, pipeline, regen, and MCP modules now log at debug level instead of silently passing (Phase G)
- **Atomic file writes** — `fileops.atomic_write_bytes` uses `os.fsync()` and directory fsync for crash safety (Phase A)
- **Thread-safe config** — `config.py` uses `threading.Lock` for concurrent access from watcher thread (Phase A/B)
- **Module-level side effects in `mcp.py`** — `resolve_root()` and `AreaIndex.build()` moved from import-time to server lifespan via `BrainRuntime` dataclass
- **AreaIndex in entry point** — `AreaIndex` and `AreaIndexEntry` extracted from `mcp.py` (entry point) to `area_index.py` (core layer) so command modules can use the index without importing from an entry point
- **State persistence coupling** — `state._connect` no longer imported by command modules; replaced with public API (`delete_source`, `update_source_flags`, `ensure_db`, `update_source_target_path`)
- **Cache invalidation race** — `process_source()` in daemon loop now invalidates global context cache when `_core/` sources change, closing the race between sync writes and regen reads
- **Dead alias** — `_find_all_content_paths` alias removed from `regen.py`; callers use `find_all_content_paths` from `fs_utils` directly

---

## 3.5. Telemetry

### Three Independent State Systems

| System | Table/Column | Purpose | Lifetime |
|---|---|---|---|
| Content state | `insight_state` | Content hashes, regen status, error tracking | Per-resource, updated each regen |
| Concurrency lock | `insight_state.owner_id` | Regen ownership for crash recovery | Transient, cleared on completion |
| Invocation telemetry | `token_events` | Append-only LLM cost accounting | Retained for configurable period (default 90 days) |

`token_events` is a cross-cutting telemetry store for all LLM workflows — regen, query, classify, and any future agent operations. Token usage is recorded exclusively here. The `insight_state` table contains only content state and regen coordination fields — token columns were removed in schema v16.

### Identity Model

`session_id` and `owner_id` are generated independently in `regen_lifecycle.py`. `session_id` groups all LLM invocations within one regen session for cost aggregation. `owner_id` manages concurrent regen slot ownership. Their lifetimes currently align but they serve different purposes.

### Resource Abstraction

`token_events` uses `resource_type`/`resource_id` to remain workflow-agnostic:

| Workflow | resource_type | resource_id |
|---|---|---|
| Regen (chunk or final) | `"knowledge"` | knowledge path |
| Future query | `"query"` | query identifier |
| Future classify | `"document"` | document ID |

### Timing

`duration_ms` measures provider invocation time for a single attempt. Retry backoff delays are excluded — each retry attempt gets its own `token_events` row with its own `duration_ms`.

### Retention

Old `token_events` rows are pruned on daemon startup. Default retention: 90 days. Configurable via `token_events.retention_days` in `~/.brain-sync/config.json`:

```json
{ "token_events": { "retention_days": 90 } }
```

### Extension Model

New LLM workflows should:
1. Use operation type constants from `token_tracking.py` (`OP_REGEN`, `OP_QUERY`, `OP_CLASSIFY`)
2. Pass `session_id`, `operation_type`, `resource_type`, `resource_id` to `invoke_claude()`
3. Query via MCP `brain_sync_usage` tool or CLI `brain-sync status`

---

## 4. Hardening Roadmap

Planned architecture evolution, in order:

1. **AreaIndex staleness model** — make `is_stale()` aware of knowledge file presence and directory structure changes
2. **Regen modularisation** — extract private helpers from `regen.py` into focused sub-modules
3. **Watcher robustness** — harden filesystem event handling for platform edge cases
4. **Exception narrowing** — replace broad `except Exception` handlers with specific exception types

This roadmap is informational and guides future refactors.

---

## 5. Private Cross-Module Imports

### Production code

| Symbol | Consumer | Notes |
|---|---|---|
| `scheduler._scheduled_keys` | `__main__.py` | Attribute access, not import |
| `commands.context._require_root` | `commands/sources.py` | Intra-package (both in `commands/`) |
| `confluence_rest._request` | `sources/confluence/comments.py` | Reuses REST client retry logic |

### Test code (acceptable)

| Symbol(s) | Consumer |
|---|---|
| `state._connect` | `test_commands`, `test_regen_queue`, `test_watcher_moves` |
| `regen._preprocess_content`, `_split_markdown_chunks`, `_build_chunk_prompt`, `_first_heading`, `_REGEN_INSTRUCTIONS`, `_parse_structured_output`, `_write_journal_entry` | `test_regen` |

Tests may access private helpers for direct validation.
Production modules should avoid this coupling — each entry above is a candidate for future refactoring.

---

## 6. Maintenance

This document should remain concise and focused on architectural structure.
It must not contain task plans or temporary refactoring instructions.

Agents must update this document whenever a change modifies module responsibilities, dependency direction, architectural phases, or structural constraints.

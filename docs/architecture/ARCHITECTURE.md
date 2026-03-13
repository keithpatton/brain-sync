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
| LLM abstraction | `llm/base`, `llm/claude_cli`, `llm/fake` | Backend protocol, Claude CLI transport, deterministic test fake |
| Regen | `regen`, `regen_lifecycle`, `regen_queue` | Deterministic insight regeneration (leaf → ancestor) |
| State | `state`, `token_tracking` | SQLite WAL persistence (sources, documents, relationships, insight state, token events) |
| Manifests | `manifest` | Source manifest read/write (`.brain-sync/sources/*.json`) |
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
reconcile_sources()  → manifest-driven: 3-tier file resolution, two-stage missing, orphan DB pruning
load_state()         → manifest-authoritative merge (manifests + DB progress cache)
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

Reconcile is a manifest-driven state-repair operation. It iterates all manifests (including missing-status), uses 3-tier file resolution (materialized_path → identity header → prefix glob), implements two-stage missing protocol, and prunes orphan DB rows. `load_state()` merges manifest intent with DB sync progress — manifests are authoritative for registration, the DB is a disposable cache. Missing-status sources are excluded from runtime state (not schedulable). Regen detects path changes on its next run and rebuilds insights at the correct locations.

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

Inline images from Google Docs are discovered via `DiscoveredImage` (in `sources/base.py`) and processed by the source-agnostic `attachments.process_inline_images()`. The adapter populates `SourceFetchResult.inline_images` during fetch; the pipeline gates download behind `sync_attachments=True`. Canonical IDs use the format `gdoc-image:{docId}:{objectId}` to avoid cross-document collision. In markdown, images are referenced as `attachment-ref:{canonicalId}` and resolved by the same regex as Confluence attachment refs.

### Architectural Principles

**Import purity** — Modules may define behavior at import time, but must not resolve environment-dependent runtime state at import time. Filesystem access, config resolution, and index construction must be deferred to explicit startup/lifespan hooks.

**MCP runtime ownership** — `BrainRuntime` is the single owner of MCP process state (root path, area index, concurrency locks). Module-level variables in `mcp.py` must remain pure definitions (constants, helper functions, tool registrations). Any variable whose value depends on filesystem state, configuration, or runtime execution must live in `BrainRuntime`. Future contributors adding new runtime state (connections, caches, locks) must add it to `BrainRuntime`, not as a new module global.

### LLM Backend Abstraction

All LLM invocations go through `LlmBackend.invoke()` (protocol in `llm/base.py`). Two implementations:

- **`ClaudeCliBackend`** (`llm/claude_cli.py`) — Production backend. Spawns `claude --print` subprocess, parses NDJSON stream output, handles timeouts.
- **`FakeBackend`** (`llm/fake.py`) — Test backend. Deterministic output from prompt hash. Modes: `stable`, `rewrite`, `fail`, `timeout`, `malformed`, `partial-stream`, `large-output`.

Backend resolution: `get_backend()` checks `BRAIN_SYNC_LLM_BACKEND` env var (`fake` → `FakeBackend`, default → `ClaudeCliBackend`). Backend is resolved once at regen entry points (`regen_path`, `regen_all`) and threaded through the call chain as a `backend` parameter. No function below the entry point calls `get_backend()`.

For backward compatibility, `regen_single_folder` defaults to `_InvokeClaudeShim` when no backend is passed, routing through `invoke_claude()` so existing test patches continue to work. New tests should pass `FakeBackend` directly.

Telemetry recording (`_record_telemetry`) wraps `backend.invoke()` results — it is not part of the backend protocol.

Prompt capture: when `BRAIN_SYNC_CAPTURE_PROMPTS` env var is set to a directory path, both backends write each prompt to `{dir}/{timestamp}_{hash}.prompt.txt`.

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
- `SourceFetchResult` — full fetch result with markdown, comments, title, optional source HTML, inline images, and download headers
- `AuthProvider` — per-source auth (Confluence: config/env credentials; Google Docs: native OAuth2 via browser consent)

**Pipeline orchestration:** `pipeline.process_source()` is source-agnostic. It calls `get_adapter()`, gates behaviour on `capabilities`, and delegates fetch/check to the adapter. Attachment sync is gated by `supports_attachments`; child discovery by `supports_children`.

**Registry:** Lazy instantiation with no startup wiring. Adapters are created on first access and cached. `reset_registry()` available for testing.

---

## 2.5. State Authority Model

### Authority Hierarchy

The system uses a tiered authority model where filesystem artifacts are authoritative for intent and portable state, while SQLite serves as a disposable performance cache.

| State Class | Authoritative Location | Portable | Rebuildable |
|---|---|---|---|
| Source registration (intent) | `.brain-sync/sources/*.json` manifests | Yes (git) | From DB (migration only) |
| Source sync progress | `sync_cache` DB table | No | Loss triggers re-sync |
| Insight hashes | `insights/**/.regen-meta.json` sidecars (future) | Yes (git) | From DB (migration only) |
| Regen lifecycle | `regen_locks` DB table (future) | No | Reset to idle on startup |
| Document metadata | `documents` DB table | No | Re-discovered on sync |
| Relationships | `relationships` DB table | No | Re-discovered on sync |
| Token telemetry | `token_events` DB table | No | Historical loss accepted |

### Managed-File Identity

Synced files carry an embedded identity header that binds them to their source registration:

```markdown
<!-- brain-sync-source: confluence:123456 -->
<!-- brain-sync-managed: local edits may be overwritten -->
```

The `brain-sync-source` line is the primary identity binding — reconciliation reads this to map files to manifests without relying on filename conventions. The `brain-sync-managed` line is a human-readable warning.

Identity resolution chain (ordered by priority):
1. **Manifest `materialized_path`** — direct file path from `.brain-sync/sources/*.json`
2. **Embedded identity header** — `<!-- brain-sync-source: {canonical_id} -->` scan
3. **Canonical prefix fallback** — filename prefix match (e.g., `c12345-`) for legacy/migration

### Source Manifests

Each registered source has a JSON manifest at `.brain-sync/sources/{canonical_id_safe}.json`:

```json
{
  "manifest_version": 1,
  "canonical_id": "confluence:123456",
  "source_url": "https://acme.atlassian.net/wiki/spaces/ENG/pages/123456",
  "source_type": "confluence",
  "materialized_path": "engineering/architecture/c123456-some-page.md",
  "target_path": "engineering/architecture",
  "fetch_children": false,
  "sync_attachments": true,
  "child_path": null,
  "status": "active",
  "sync_hint": {
    "content_hash": "abc123...",
    "last_synced_utc": "2026-03-14T10:00:00+00:00"
  }
}
```

`target_path` preserves placement intent independently of `materialized_path`. When the DB is deleted, `target_path` ensures the first sync writes to the correct area. `materialized_path` is the relative file path within `knowledge/`; `target_path` is the containing directory. `target_path == ""` means knowledge root. `materialized_path == ""` means the source has not yet been synced to a file (unmaterialized).

### Brain Control Plane Directory

```
{brain_root}/
├── .brain-sync/
│   ├── version.json           # {"manifest_version": 1}
│   └── sources/               # one manifest per registered source
│       └── confluence-123456.json
├── .sync-state.sqlite         # disposable cache (gitignored)
├── knowledge/
└── insights/
```

### Architectural Invariants (Source Authority)

1. **Identity invariant** — A synced source is identified by its canonical ID, not by its filesystem path.
2. **Move invariant** — Moving a synced file relocates the materialization. No content is re-fetched.
3. **Delete invariant** — Deleting a synced file triggers two-stage deregistration via manifests (first reconcile marks missing, second reconcile deletes).
4. **Edit invariant** — Edits to synced files are overwritten by the next upstream sync.
5. **No auto-registration** — Files with identity headers but no manifest are ignored.
6. **No DB resurrection** — DB state must never recreate deleted filesystem content. UNCHANGED + missing file → skip.
7. **Manifest-first writes** — Commands write manifests before DB to ensure crash recovery favours disk truth.

### DB Table Justifications

Every remaining DB table must justify its existence. If deleted, the consequence column describes what happens on next startup.

| Table | Performance/Operational Problem Solved | If Deleted |
|---|---|---|
| `sources` | Caches sync progress (last_checked, content_hash, intervals) to avoid re-fetching; `load_state()` merges manifest intent + DB progress | Rebuilt from `.brain-sync/sources/*.json` manifests; `_seed_from_hint()` seeds timing from `sync_hint` so matching sources skip re-fetch; orphan DB rows (no manifest) are pruned during reconcile |
| `insight_state` | Caches content/summary/structure hashes to avoid recomputing on every regen check; holds regen lifecycle locks | Future: rebuilt from `.regen-meta.json` sidecars; all locks reset to idle; hashes recomputed on first regen |
| `documents` | Caches discovered page/attachment metadata to avoid redundant API calls during child/attachment discovery | Re-discovered on next sync cycle; no data loss, slight increase in API calls |
| `relationships` | Caches parent-child links between sources/documents for orphan cleanup and child discovery deduplication | Rebuilt from next fetch results; orphan detection delayed until rebuild completes |
| `token_events` | Append-only LLM cost telemetry for usage dashboards and budget monitoring | Historical telemetry lost; new events recorded normally; no operational impact |
| `daemon_status` | Single-row runtime state for `brain-sync status` CLI; detects stale daemon PIDs | Recreated on next daemon start; `status` command shows "unknown" until daemon writes |
| `meta` | Stores schema version for migration gating | DB recreated from scratch at current schema version; no migration needed |

### Startup Tree Walk

The startup reconciliation walk (reading manifests, scanning knowledge/ for moved files, reading sidecars) is a **correctness operation**, not cache warming. Its purpose is to detect offline filesystem changes (moves, deletes, additions) and bring the DB cache into agreement with disk truth. Skipping or short-circuiting this walk risks the DB containing stale paths, ghost sources, or missing hashes — all of which produce incorrect sync and regen behaviour.

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
- **LLM coupling** — `invoke_claude()` subprocess logic extracted to `llm/claude_cli.py` behind `LlmBackend` protocol; deterministic `FakeBackend` enables integration tests without subprocess overhead

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
2. Resolve a backend via `get_backend()` and call `backend.invoke()`, then record telemetry via `_record_telemetry()`
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

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
| Commands / CLI | `commands/`, `cli/` | User-facing operations (add, remove, list, move, init) |
| Sync pipeline | `pipeline`, `confluence_rest`, `converter`, `docx_converter`, `sources/` | Fetch, convert, and write knowledge files |
| Regen | `regen`, `regen_lifecycle`, `regen_queue` | Deterministic insight regeneration (leaf → ancestor) |
| State | `state` | SQLite WAL persistence (sources, documents, relationships, insight state) |
| MCP | `mcp` | FastMCP tool interface over stdio |
| Context | `context`, `context_index`, `link_rewriter`, `area_index` | Context discovery, area indexing, link rewriting |
| Utilities | `config`, `fileops`, `fs_utils`, `logging_config`, `retry`, `scheduler` | Shared helpers with no domain coupling |
| Watcher | `watcher` | Filesystem event monitoring, insight folder mirroring |

Dependency direction rules are defined in `CLAUDE.md`.

---

## 2. Module Responsibilities

**Utilities** — stateless helpers: path operations, logging setup, retry logic, scheduling. No domain knowledge. `config` is the canonical source for `CONFIG_DIR`, `CONFIG_FILE`, `load_config()`, and `save_config()` — all config access must go through this module.

**Core modules** — domain logic: sync pipeline fetches and converts sources; regen produces insights from knowledge; state persists all sync and regen metadata in SQLite. Journal entries are generated alongside summaries via structured XML output. Journal writing is independent of the summary similarity guard — temporal events are recorded even when the summary abstraction doesn't change. Controlled by `write_journal` config flag.

**Interfaces** — MCP server exposes brain operations as tools over stdio; watcher monitors the filesystem and queues regen work.

**Commands / CLI** — orchestrate core modules into user-facing operations. Commands are the public API consumed by both CLI handlers and MCP tools. Includes `commands/placement.py` for source classification, document placement suggestions, and filename helpers (used by both `brain_sync_add`/`brain_sync_suggest_placement` MCP tools and `brain-sync add` CLI command).

**Entry points** — `__main__` runs the daemon loop; `mcp` runs the FastMCP stdio server. Both wire together commands, scheduling, and interfaces.

### Architectural Principles

**Import purity** — Modules may define behavior at import time, but must not resolve environment-dependent runtime state at import time. Filesystem access, config resolution, and index construction must be deferred to explicit startup/lifespan hooks.

**MCP runtime ownership** — `BrainRuntime` is the single owner of MCP process state (root path, area index, concurrency locks). Module-level variables in `mcp.py` must remain pure definitions (constants, helper functions, tool registrations). Any variable whose value depends on filesystem state, configuration, or runtime execution must live in `BrainRuntime`. Future contributors adding new runtime state (connections, caches, locks) must add it to `BrainRuntime`, not as a new module global.

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

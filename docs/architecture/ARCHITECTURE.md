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
| Context | `context`, `context_index`, `link_rewriter` | Context discovery, area indexing, link rewriting |
| Utilities | `config`, `fileops`, `fs_utils`, `logging_config`, `retry`, `scheduler` | Shared helpers with no domain coupling |
| Watcher | `watcher` | Filesystem event monitoring, insight folder mirroring |

Dependency direction rules are defined in `CLAUDE.md`.

---

## 2. Module Responsibilities

**Utilities** — stateless helpers: path operations, logging setup, retry logic, scheduling. No domain knowledge. `config` is the canonical source for `CONFIG_DIR`, `CONFIG_FILE`, `load_config()`, and `save_config()` — all config access must go through this module.

**Core modules** — domain logic: sync pipeline fetches and converts sources; regen produces insights from knowledge; state persists all sync and regen metadata in SQLite.

**Interfaces** — MCP server exposes brain operations as tools over stdio; watcher monitors the filesystem and queues regen work.

**Commands / CLI** — orchestrate core modules into user-facing operations. Commands are the public API consumed by both CLI handlers and MCP tools.

**Entry points** — `__main__` runs the daemon loop; `mcp` runs the FastMCP stdio server. Both wire together commands, scheduling, and interfaces.

---

## 3. Known Technical Debt

**Private cross-module imports** — several modules access underscore-prefixed internals across module boundaries. See §5 for the full inventory.

**Path normalisation spread** — path cleaning and resolution logic is distributed across `fileops`, `fs_utils`, `pipeline`, and `watcher` rather than consolidated.

**State persistence coupling** — `state._connect` is called directly by command modules instead of going through a service boundary.

**Watcher edge cases** — Windows symlink handling and rapid sequential move events are not fully robust.

**Regen complexity** — `regen.py` is the largest module with many private helpers; candidates for extraction exist.

**Module-level side effects in `mcp.py`** — `resolve_root()` and `AreaIndex.build(_root)` execute at import time, coupling module loading to filesystem state.

### Resolved (2026-03)

- **Config duplication** — all config constants and I/O centralised in `config.py`; consumers import from there (Phase B)
- **Dependency direction violations** — `regen.py` no longer imports from `commands.context` (Phase B/C)
- **Dead v1 manifest system** — `manifest.py` and related test code removed; v2 uses SQLite state exclusively (Phase E)
- **Silent exception swallowing** — retry, pipeline, regen, and MCP modules now log at debug level instead of silently passing (Phase G)
- **Atomic file writes** — `fileops.atomic_write_bytes` uses `os.fsync()` and directory fsync for crash safety (Phase A)
- **Thread-safe config** — `config.py` uses `threading.Lock` for concurrent access from watcher thread (Phase A/B)

---

## 4. Hardening Roadmap

Planned architecture evolution, in order:

1. **Path consolidation** — unify path normalisation into a single module
2. **State modularisation** — expose state access through a public API, eliminating `_connect` imports
3. **Service layer introduction** — insert a service boundary between commands and core modules
4. **MCP modularisation** — move tool definitions out of `mcp.py`, defer side effects to startup
5. **Regen modularisation** — extract private helpers into focused sub-modules
6. **Watcher robustness** — harden filesystem event handling for platform edge cases

This roadmap is informational and guides future refactors.

---

## 5. Private Cross-Module Imports

### Production code

| Symbol | Consumer | Notes |
|---|---|---|
| `state._connect` | `commands/sources.py` | Top-level import |
| `state._connect` | `commands/init.py` | Deferred import inside function |
| `scheduler._scheduled_keys` | `__main__.py` | Attribute access, not import |
| `commands.context._require_root` | `commands/sources.py` | Intra-package (both in `commands/`) |

### Test code (acceptable)

| Symbol(s) | Consumer |
|---|---|
| `state._connect` | `test_commands`, `test_regen_queue`, `test_watcher_moves` |
| `regen._preprocess_content`, `_split_markdown_chunks`, `_build_chunk_prompt`, `_first_heading`, `_REGEN_INSTRUCTIONS` | `test_regen` |

Tests may access private helpers for direct validation.
Production modules should avoid this coupling — each entry above is a candidate for future refactoring.

---

## 6. Maintenance

This document should remain concise and focused on architectural structure.
It must not contain task plans or temporary refactoring instructions.

Agents must update this document whenever a change modifies module responsibilities, dependency direction, architectural phases, or structural constraints.

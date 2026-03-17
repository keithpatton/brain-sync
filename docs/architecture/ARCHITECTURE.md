# Architecture

This document explains the current brain-sync system architecture.

Use it for design intent, module responsibilities, state models, rationale,
and technical debt. For the normative portable contract, see
`docs/brain/` and the shared reference docs under `docs/`.

This document is explanatory, not the normative home for invariants or schema
detail. Exact guarantees, precedence rules, and contract-level constraints
belong in `docs/RULES.md`, `docs/brain/`, and `docs/runtime/`; architecture
should summarize those constraints only as needed to explain the design.

---

## 1. System Structure

All source lives under `src/brain_sync/`.

| Group | Modules | Purpose |
|---|---|---|
| Entry points | `__main__`, `mcp` | CLI/bootstrap entrypoint and legacy MCP shim |
| Application / interfaces | `application/`, `interfaces/`, legacy `cli/`, `mcp.py`, and `commands/` shims | Interface-neutral operations plus CLI and MCP transport adapters |
| Portable brain plane | `brain/`, legacy root shims such as `brain_repository`, `manifest`, `sidecar`, `fileops`, `fs_utils`, `layout` | Portable brain persistence, managed layout, manifests, sidecars, and tree semantics |
| Runtime plane | `runtime/`, legacy root shims such as `state`, `config`, `token_tracking`, `layout` | Machine-local config, DB, daemon status, and telemetry |
| Sync subsystem | `sync/`, legacy root shims such as `pipeline`, `reconcile`, `watcher`, `scheduler` | Daemon loop, polling, filesystem watching, and source materialization |
| Query subsystem | `query/`, legacy root shims such as `area_index` and `application/placement` | Read-model indexing and placement/search helpers over portable brain structure |
| Source adapters | `sources/base`, `sources/registry`, `sources/confluence/`, `sources/googledocs/`, `sources/conversion`, `sources/docx` | Per-source fetch logic, provider REST/auth flows, and source-format normalization |
| LLM abstraction | `llm/base`, `llm/claude_cli`, `llm/fake` | Backend protocol, production transport, deterministic fake |
| Regen subsystem | `regen/`, legacy root shims such as `regen_lifecycle`, `regen_queue` | Regeneration engine, lifecycle, queueing, and packaged prompt resources |
| Attachments | `sync/attachments`, `sources/confluence/attachments`, legacy `attachments` shim | Sync-owned attachment materialization plus provider-specific attachment discovery |
| Utilities | `util/`, legacy `logging_config` and `retry` shims | Shared helpers with no domain coupling |

---

## 2. Module Responsibilities

**Runtime helpers** are split between `runtime/config.py`, which owns config
file access, and `runtime/paths.py`, which owns machine-local runtime paths.
Legacy root `config.py` and `layout.py` remain compatibility shims only.

**Core modules** implement sync, reconciliation, and regeneration. `sync/`
owns the daemon loop, polling scheduler, watcher, reconcile path, and source
materialization workflow. `brain/repository.py` owns the portable-brain
mutation and resolution rules used by sync, reconcile, doctor, and
regen-adjacent cleanup. `regen/` owns regeneration, lifecycle, queueing, and
the packaged prompt/template resources used to rebuild derived meaning.

**Interfaces** expose the system to users and tools. `application/` owns the
interface-neutral operations consumed by the CLI and MCP layers. `interfaces/`
owns the CLI parser/handlers and the MCP transport surface. The legacy
`commands/`, `cli/`, and `mcp.py` paths remain as compatibility shims. The
watcher provides online change detection as an edge observer with direct
filesystem contact; reconciliation provides the equivalent correction path for
offline changes. Interface-owned packaged resources such as the installed
brain-sync skill now live under `interfaces/mcp/resources/`.

**Query helpers** live under `query/`. `query/area_index.py` owns the
read-optimized area index used by placement and MCP search, and
`query/placement.py` owns placement suggestions and related read-only
classification helpers.

**Entry points** wire everything together. `__main__.py` is now the CLI and
bootstrap surface while `sync/daemon.py` owns the long-running daemon loop.
`interfaces/mcp/server.py` exposes repository-safe tool access over stdio, with
`mcp.py` retained as a compatibility shim.

### Package Identity Docstrings

Canonical subsystem packages should carry a short `__init__.py` docstring that
states:

- the package's responsibility
- what kinds of code belong inside
- what kinds of code do not belong inside

Those docstrings are intentionally local and concise. They should help readers
and agents classify code at the package boundary without duplicating the fuller
explanatory material in this document or the repository workflow rules in
`AGENTS.md`.

### Dependency Direction

The package ontology is directional. The intended flow is:

- `interfaces -> application`
- `application -> brain / runtime / sync / regen / query / sources / llm / util`
- `sync -> brain / runtime / sources / util`
- `regen -> brain / runtime / llm / util`
- `query -> brain / util`
- `sources -> util`
- `llm -> util`
- `brain -> util`
- `runtime -> util`

Entry points may depend on `application`, `interfaces`, and `sync` for process
bootstrap, but lower-level packages must not import upward into entrypoints.

The inverse directions are architecturally invalid. In particular:

- `brain`, `runtime`, and `util` must not import upward into application or interface layers
- `sources` must not own portable-brain or runtime persistence semantics
- `query` must remain read-oriented rather than orchestrating sync or regen
- `regen` and `sync` are peer subsystems and should not collapse back into each other

When code needs to be shared, move it to the owning lower-level package or to
a truly neutral helper rather than introducing upward imports or vague
catch-all modules.

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

Because Brain Format `1.0` co-locates managed area state under `knowledge/<area>/.brain-sync/`,
folder moves carry summaries and attachment directories with them
automatically. The system repairs manifests and runtime state, but no longer
maintains a separate top-level insight mirror.

### Ownership Model

| Layer | Owner | Responsibility |
|---|---|---|
| `knowledge/` plus source manifests plus managed area artifacts | `brain/repository.py` used by sync / reconcile / doctor / regen, with watcher as edge observer | Durable portable-brain artifacts, document locations, and managed filesystem policy |
| `regen_locks` plus `sync_cache` plus daemon/runtime files | `runtime/repository.py` | Runtime coordination, progress cache, telemetry, and process state |
| `~/.brain-sync/` runtime DB and daemon status | runtime | Machine-local cache, telemetry, and process state |

The filesystem remains authoritative. Runtime state is disposable and must be
rebuildable from manifests and per-area insight state.

The legacy root `state.py` shim points at `runtime/repository.py`. The runtime
plane is not the owner of portable brain semantics or durable brain mutations.

`brain/manifest.py`, `brain/sidecar.py`, and `brain/fileops.py` remain
primitive storage / filesystem helpers beneath those seams. They are
implementation detail, not the approved semantic entry points for normal
runtime portable-state mutation.

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

This per-source directory isolation is a key simplification in the current
layout. Attachments
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

**Repository mutation contract**: `brain_repository.py` is the defensive
boundary for portable brain mutation. Discovery and idempotent cleanup methods
may return soft outcomes such as `None`, empty collections, or `False` when
absence is expected. Strict mutation methods must validate their own inputs
with repository/fileops rules and raise on invariant breaches rather than
assuming callers prevalidated correctly. Outer command/daemon boundaries should
catch, log, and surface those failures without making caller-side prechecks the
source of truth.

**Two persistence planes**: normal runtime code should treat
`brain_repository.py` as the portable-brain write boundary and `state.py` as
the runtime-state write boundary. Bootstrap, migration, and test/SUT code are
the only expected exceptions.

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

Provider-owned helpers now live with their provider or source-format package:
Confluence REST and attachment discovery live under `sources/confluence/`,
while generic markdown/docx conversion lives under `sources/conversion.py` and
`sources/docx.py`. Source-agnostic attachment materialization helpers live
under `sync/attachments.py`, with the root `attachments.py`,
`confluence_rest.py`, `converter.py`, and `docx_converter.py` paths retained
only as compatibility shims.

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

Portable state lives in the brain root. Runtime state lives in the
brain-sync runtime directory under the user config location and may be deleted
without invalidating the brain.

The durable/runtime split is also a write-discipline rule: runtime lifecycle
updates in `regen_locks` must not rewrite unchanged portable
`insight-state.json` files. Portable insight-state is rewritten only when its
durable manifest fields actually change.

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

Those resolution rules are centralized in `brain_repository.py` so doctor,
reconcile, and command flows do not drift into separate portable-brain logic.

### Source Manifests

Each synced source has a manifest at `.brain-sync/sources/<source_dir_id>.json`.

Current durable fields:

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

Current runtime DB tables:

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
| Global context cache | `knowledge/_core/` | `regen/engine.py` | invalidated on `_core` changes | Correctness-critical |
| AreaIndex | `knowledge/**/.brain-sync/insights/summary.md` plus `knowledge/` structure | `BrainRuntime` | staleness check before queries | Performance-only |

### Resolved (2026-03)

- Runtime config now lives under `runtime/config.py`, with machine-local path
  ownership split into `runtime/paths.py` and portable layout retained in
  `brain/layout.py`.
- Regen now lives under `regen/`, with the engine, queue, lifecycle, and
  prompt resources moved under one subsystem package.
- Sync runtime mechanics now live under `sync/`, with `sync/daemon.py`
  replacing `__main__.py` as the owner of the daemon loop.
- `regen.py` no longer imports from command-layer modules.
- Manifests are the authoritative durable registration layer in v23.
- Atomic file writes use fsync-based crash-safe behavior.
- MCP runtime state now lives in `interfaces/mcp/server.py` rather than a
  root entrypoint module.
- `AreaIndex` and placement logic now live under the `query/` subsystem.
- Confluence REST, conversion, docx conversion, and MCP skill resources now
  live under their owning `sources/` and `interfaces/` packages rather than
  root-level convenience locations.
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
| `scheduler._scheduled_keys` | `sync/daemon.py` | Attribute access, not import |
| `application.roots._require_root` | `application/sources.py` | Intra-package use |
| `sources.confluence.rest._request` | `sources/confluence/comments.py` | Reuses retry behavior |

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

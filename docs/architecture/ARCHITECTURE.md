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
| Entry points | `__main__`, `interfaces/mcp/server.py` | CLI/bootstrap entrypoint and MCP server entrypoint |
| Application / interfaces | `application/`, `interfaces/` | Interface-neutral operations plus CLI and MCP transport adapters |
| Portable brain plane | `brain/` | Portable brain persistence, managed layout, manifests, sidecars, and tree semantics |
| Runtime plane | `runtime/` | Machine-local config, DB, daemon status, and telemetry |
| Sync subsystem | `sync/` | Daemon loop, polling, filesystem watching, and source materialization |
| Query subsystem | `query/` | Read-model indexing and placement/search helpers over portable brain structure |
| Source adapters | `sources/base`, `sources/registry`, `sources/confluence/`, `sources/googledocs/`, `sources/conversion`, `sources/docx` | Per-source fetch logic, provider REST/auth flows, and source-format normalization |
| LLM abstraction | `llm/base`, `llm/claude_cli`, `llm/fake` | Backend protocol, production transport, deterministic fake |
| Regen subsystem | `regen/` | Regeneration engine, lifecycle, queueing, and packaged prompt resources |
| Attachments | `sync/attachments`, `sources/confluence/attachments` | Sync-owned attachment materialization plus provider-specific attachment discovery |
| Utilities | `util/` | Shared helpers with no domain coupling |

The root package is intentionally thin: `__init__.py`, `__main__.py`, and the
canonical subsystem packages above. Transitional root-module shims used during
the ontology migration have been removed, so canonical package paths are the
only supported import surface.

---

## 2. Canonical Subsystem Boundaries

Canonical ownership lives in the package homes below. These packages are the
conceptual owners for new work and the supported Python import homes.

| Package | Owns | Does not own |
|---|---|---|
| `application/` | interface-neutral use-case orchestration such as init, config, source admin, and doctor flows | CLI/MCP transport details, durable persistence primitives, provider protocol code |
| `interfaces/` | CLI parsing/handlers, MCP transport, interface-owned packaged resources | shareable application workflows, portable or runtime persistence logic |
| `brain/` | portable brain repository boundary, managed layout, manifests, sidecars, filesystem/tree semantics | runtime DB/config/daemon state, provider integration, LLM calls |
| `runtime/` | machine-local config, runtime paths, runtime repository, token telemetry | portable brain semantics or writes inside the brain root |
| `sync/` | daemon loop, scheduler, watcher, reconciliation, source materialization, source-agnostic attachment syncing | provider auth/REST behavior, query indexing, regen prompt policy |
| `regen/` | derived-meaning regeneration, lifecycle, queueing, prompt resources, template resources | source sync mechanics, transport adapters, portable storage primitives |
| `query/` | read-model indexing, placement suggestions, read-only classification helpers | durable writes, daemon orchestration, provider protocol logic |
| `sources/` | provider-specific adapters, auth, REST helpers, title resolution, source-format conversion | portable-brain ownership, runtime ownership, CLI/MCP orchestration |
| `llm/` | backend protocol and concrete backends | regen policy, token persistence, provider/source logic |
| `util/` | minimal neutral helpers such as logging and retry | anything that knows about brains, manifests, knowledge areas, or runtime rows |

### Dependency Shape

The package graph is intentionally directional:

- `interfaces` adapts transport and calls `application`
- `application` composes lower subsystems to complete user-visible work
- `brain` and `runtime` are the two persistence planes
- `sync`, `regen`, `query`, `sources`, and `llm` are peer subsystems beneath `application`
- `util` stays neutral and must not grow domain ownership

The exact allowed and forbidden dependency directions are normative in
`docs/RULES.md`. This document explains why those boundaries exist and how to
classify code when new feature work or refactoring crosses subsystem lines.

### Architecture Fitness Tests

`docs/RULES.md` is the normative package-boundary contract.
`tests/unit/test_architecture_boundaries.py` is the executable fitness
function that enforces:

- the normal package dependency graph
- the closed set of named orchestration surfaces
- the exact file-level exceptions listed in `docs/RULES.md`
- a small ratchet for transitional seams that are still debt

If a new orchestration surface or exception is intentional, the rules doc and
the fitness test should change together.

## 2.1. Responsibilities And Flows

**Runtime helpers** are split between `runtime/config.py`, which owns config
file access, and `runtime/paths.py`, which owns machine-local runtime paths.

**Core modules** implement sync, reconciliation, and regeneration. `sync/`
owns the daemon loop, polling scheduler, watcher, reconcile path, and source
materialization workflow. `brain/repository.py` owns the portable-brain
mutation and resolution rules used by sync, reconcile, doctor, and
regen-adjacent cleanup. `regen/` owns regeneration, lifecycle, queueing, and
the packaged prompt/template resources used to rebuild derived meaning.

**Interfaces** expose the system to users and tools. `application/` owns the
interface-neutral operations consumed by the CLI and MCP layers. `interfaces/`
owns the CLI parser/handlers and the MCP transport surface. The
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
`interfaces/mcp/server.py` exposes repository-safe tool access over stdio.

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

**Repository mutation contract**: `brain/repository.py` is the defensive
boundary for portable brain mutation. Discovery and idempotent cleanup methods
may return soft outcomes such as `None`, empty collections, or `False` when
absence is expected. Strict mutation methods must validate their own inputs
with repository/fileops rules and raise on invariant breaches rather than
assuming callers prevalidated correctly. Outer command/daemon boundaries should
catch, log, and surface those failures without making caller-side prechecks the
source of truth.

**Two persistence planes**: normal runtime code should treat
`brain/repository.py` as the portable-brain write boundary and
`runtime/repository.py` as the runtime-state write boundary. Bootstrap,
migration, and test/SUT code are the only expected exceptions.

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
under `sync/attachments.py`.

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

Those resolution rules are centralized in `brain/repository.py` so doctor,
reconcile, and application flows do not drift into separate portable-brain
logic.

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

### Transitional Boundary Debt

Some seams are still tolerated as transitional debt rather than part of the
normative package graph:

- `runtime/repository.py` still imports `brain/` helpers to project portable
  manifests and insight sidecars into runtime views. This is not a general
  `runtime -> brain` allowance; it is debt carried in one file.
- `sync/reconcile.py` and `sync/watcher.py` still reach into `regen/` for
  folder classification and cache invalidation helpers. This is not a general
  `sync -> regen` allowance; it is a bounded transitional seam.

These seams are ratcheted by the architecture fitness tests so they cannot
quietly spread to new files or wider imports without review.

**Watcher edge cases**: Windows symlink handling and rapid sequential move
events still need hardening.

**Regen complexity**: `regen/engine.py` remains one of the largest modules and is a
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
- regen engine code no longer imports from command-layer modules.
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
2. split `regen/engine.py` into smaller focused modules
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
| selected private `regen.engine` helpers | `tests/unit/test_regen.py` |

Tests may validate private helpers directly. Production code should avoid
growing new cross-module private coupling.

---

## 6. Maintenance

This document should remain concise and explanatory.

It should be updated whenever module responsibilities, authority models,
dependency direction, or major structural constraints change.

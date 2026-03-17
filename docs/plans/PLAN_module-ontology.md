# PLAN_module-ontology: Post-Repository-Correction Module and Package Restructuring

## Status

Planning artifact only. This document defines the post-repository-correction
target ontology and staged migration plan for the source tree under
`src/brain_sync/`.

Fixed assumptions for this plan:

- all portable brain writes are already mediated through `brain_repository.py`
- all runtime-state writes are already mediated through `state.py` or an
  equivalent runtime repository module
- primitive modules beneath those seams are already documented as lower-level
  dependencies
- observability is not yet implemented
- this pass is about structural clarity and ontology only, not behavioral
  redesign

This plan chooses one target structure and one migration direction. It is
intended to create incremental convergence toward a stable architecture that can
be enforced in code review, documentation, and future agent guidance.

## Objective

Define a package structure whose names predict membership and dependency
direction, so that the source tree explains the system rather than merely
containing it.

The target structure must separate:

- portable brain persistence and control
- runtime persistence and control
- regeneration as a distinct subsystem
- interface-neutral application orchestration
- source adapter and integration code
- interface adapters such as CLI and MCP
- truly neutral utilities only

This plan rejects convenience buckets such as `core`, `common`, `helpers`, and
`misc`, and it rejects package names whose meaning is only "things related to".

## 1. Target Ontology

### Canonical package map

Future steady state:

```text
src/brain_sync/
  __init__.py
  __main__.py                  # compatibility/bootstrap shim only

  application/
    __init__.py
    roots.py
    init.py
    config.py
    sources.py
    doctor.py

  interfaces/
    __init__.py
    cli/
      __init__.py
      parser.py
      handlers.py
      main.py
    mcp/
      __init__.py
      server.py
      runtime.py
      resources/
        brain_sync/
          SKILL.md

  brain/
    __init__.py
    repository.py
    fileops.py
    layout.py
    managed_markdown.py
    manifest.py
    sidecar.py
    tree.py

  runtime/
    __init__.py
    repository.py
    config.py
    token_tracking.py

  sync/
    __init__.py
    daemon.py
    pipeline.py
    reconcile.py
    scheduler.py
    watcher.py

  regen/
    __init__.py
    engine.py
    lifecycle.py
    queue.py
    resources/
      INSIGHT_INSTRUCTIONS.md
      templates/
        insights/
          summary.md
          status.md
          decisions.md
          glossary.md

  query/
    __init__.py
    area_index.py
    placement.py

  sources/
    __init__.py
    base.py
    registry.py
    title_resolution.py
    conversion.py
    docx.py
    confluence/
      __init__.py
      auth.py
      rest.py
      comments.py
      attachments.py
    googledocs/
      __init__.py
      auth.py
      rest.py
    test/
      __init__.py
      auth.py

  llm/
    __init__.py
    base.py
    claude_cli.py
    fake.py

  util/
    __init__.py
    logging.py
    retry.py
```

Normative rule: after convergence, no new conceptual top-level modules should
be added directly under `src/brain_sync/` other than package shims,
`__init__.py`, and `__main__.py`.

### Package definitions

#### `application`

Responsibility:
Interface-neutral orchestration of user-visible operations.

What belongs inside:

- operations such as initialize brain, configure credentials, register/remove
  sources, doctor/rebuild flows, resolve active root
- composition of lower subsystems into one use case
- policy that is specific to one user-facing operation but not to one
  interface

Out of scope:

- durable portable-brain persistence mechanics
- runtime persistence mechanics
- raw CLI parsing or MCP transport details
- source-provider protocol code
- regen internals and sync-loop machinery

#### `interfaces`

Responsibility:
Adapters that expose application capabilities to humans or external tools.

What belongs inside:

- CLI parser, handlers, and entrypoint glue
- MCP server, tool registration, request/response shaping, MCP-local runtime
- interface-owned packaged resources such as the skill file

Out of scope:

- business orchestration that should be shareable across CLI and MCP
- durable persistence logic
- source adapters
- regen or sync engine internals

#### `brain`

Responsibility:
Portable brain persistence and control.

What belongs inside:

- the repository seam for portable brain writes
- managed-file identity rules
- manifest and sidecar primitives
- knowledge-tree and managed-path filesystem rules
- portable layout and path semantics

Out of scope:

- machine-local runtime DB and daemon state
- CLI/MCP/application orchestration
- source-provider network logic
- LLM invocation

#### `runtime`

Responsibility:
Machine-local runtime persistence and control.

What belongs inside:

- runtime repository for `sync_cache`, `regen_locks`, daemon status, runtime DB
- runtime config and path resolution under the user config directory
- token usage telemetry storage

Out of scope:

- portable brain semantics
- managed filesystem mutation inside the brain root
- source-provider logic
- interface code

#### `sync`

Responsibility:
Continuous source-ingest and filesystem-convergence subsystem around the brain.

What belongs inside:

- daemon run loop
- source processing pipeline
- watcher and debounce logic
- startup reconciliation
- sync scheduling

Out of scope:

- persistent source-provider protocol implementations
- regen internals
- CLI/MCP handlers
- root-resolution and other application entry policies

#### `regen`

Responsibility:
Derived-meaning regeneration subsystem.

What belongs inside:

- regen engine and propagation logic
- regen queue and lifecycle coordination
- regen-owned prompt resources and templates
- LLM-facing summary generation logic

Out of scope:

- source sync loop
- CLI/MCP transport
- portable persistence primitives themselves
- search/query read-model code

#### `query`

Responsibility:
Read-models over portable brain structure and regen outputs.

What belongs inside:

- area indexing
- placement suggestion logic
- search helpers that interpret summaries and knowledge structure

Out of scope:

- durable writes
- sync or regen orchestration
- CLI/MCP transport
- provider integration

#### `sources`

Responsibility:
External source adapter and ingestion-integration layer.

What belongs inside:

- provider protocol abstractions and registry
- provider-specific auth, REST, attachment discovery, and title resolution
- content conversion logic that exists to normalize upstream source formats

Out of scope:

- persistent portable-brain writes
- runtime-state ownership
- CLI/MCP handlers
- regen logic

#### `llm`

Responsibility:
Model/backend integration boundary.

What belongs inside:

- backend protocol
- concrete production and fake backends
- backend resolution

Out of scope:

- regen policy
- token event persistence
- prompt templates as a general resource bucket

#### `util`

Responsibility:
Minimal neutral helpers with no domain ownership.

What belongs inside:

- logging setup
- retry helpers

Out of scope:

- anything that knows what a brain, runtime row, source, summary, area, or
  manifest is
- filesystem helpers specific to the brain root
- path rules for knowledge areas
- scheduling, because scheduler semantics belong to sync

### Ontological notes

- There is no separate `observability/` package in this plan because
  observability is explicitly not implemented yet.
- There is no long-lived top-level `skills/`, `instructions/`, `templates/`, or
  `schemas/` package in the target ontology. Those are resources owned by a
  subsystem, not conceptual peer subsystems.
- The root package should stop functioning as a flat map of unrelated files.

## 2. Dependency Direction Rules

### Allowed directions

Normative dependency directions:

- `interfaces` -> `application`
- `application` -> `brain`
- `application` -> `runtime`
- `application` -> `sync`
- `application` -> `regen`
- `application` -> `query`
- `application` -> `sources`
- `application` -> `llm` only when a use case truly owns backend selection
- `sync` -> `brain`
- `sync` -> `runtime`
- `sync` -> `sources`
- `sync` -> `util`
- `regen` -> `brain`
- `regen` -> `runtime`
- `regen` -> `llm`
- `regen` -> `util`
- `query` -> `brain`
- `query` -> `util`
- `sources` -> `util`
- `llm` -> `util`
- `brain` -> `util`
- `runtime` -> `util`

### Forbidden directions

These directions are architecturally invalid:

- `brain` -> `application`, `interfaces`, `sync`, `regen`, `query`, `sources`,
  `llm`
- `runtime` -> `application`, `interfaces`, `sync`, `regen`, `query`,
  `sources`, `llm`
- `sources` -> `brain`, `runtime`, `application`, `interfaces`, `sync`,
  `regen`, `query`
- `query` -> `application`, `interfaces`, `sync`, `regen`, `sources`, `llm`
- `regen` -> `application`, `interfaces`, `sync`, `query`, `sources`
- `sync` -> `application`, `interfaces`, `regen`, `query`, `llm`
- `llm` -> `brain`, `runtime`, `application`, `interfaces`, `sync`, `regen`,
  `query`, `sources`
- `util` -> any domain package

### Special rule for primitives beneath seams

Primitive modules inside `brain` and `runtime` may depend inward on lower-level
files in the same package, but callers outside those packages must treat the
package seam as the normal dependency surface.

### Temporary violations tolerated during migration

These temporary violations are expected and must be eliminated phase by phase:

- source adapter modules still type-reference runtime-layer types currently
  defined in `state.py`
- runtime code may still import portable layout helpers during transition
- MCP and CLI entrypoints will temporarily import legacy top-level modules while
  shims exist
- `commands/placement.py` is currently mixed query/application code
- `attachments.py` is currently mixed sync/source/repository-adjacent code

No new violations of these kinds may be introduced after this plan is adopted.

## 3. Module Classification

### Root modules

| Current location | Target package | Ontological justification |
|---|---|---|
| `src/brain_sync/__main__.py` | `interfaces.cli.main` plus `sync.daemon`; keep root shim | It currently mixes process bootstrap, CLI dispatch, and daemon orchestration. Those are interface and sync concerns, not one module concept. |
| `src/brain_sync/mcp.py` | `interfaces.mcp.server` | It is an MCP transport adapter and tool surface, not a core subsystem. |
| `src/brain_sync/brain_repository.py` | `brain.repository` | It is the portable-brain control seam by definition. |
| `src/brain_sync/state.py` | `runtime.repository` | It owns machine-local runtime persistence; the current name is too broad for its role. |
| `src/brain_sync/config.py` | `runtime.config` | It resolves user config and runtime paths under `~/.brain-sync/`. |
| `src/brain_sync/token_tracking.py` | `runtime.token_tracking` | It persists and queries runtime telemetry; this is runtime-plane state. |
| `src/brain_sync/pipeline.py` | `sync.pipeline` | It orchestrates source fetch/materialize behavior around the brain. |
| `src/brain_sync/reconcile.py` | `sync.reconcile` | It performs startup filesystem/runtime convergence. |
| `src/brain_sync/watcher.py` | `sync.watcher` | It is an online filesystem observer for the sync daemon. |
| `src/brain_sync/scheduler.py` | `sync.scheduler` | Its semantics belong to sync polling, not neutral utilities. |
| `src/brain_sync/regen.py` | `regen.engine` | It is the main regeneration subsystem engine. |
| `src/brain_sync/regen_lifecycle.py` | `regen.lifecycle` | It owns regen lifecycle coordination. |
| `src/brain_sync/regen_queue.py` | `regen.queue` | It queues and sequences regen work. |
| `src/brain_sync/area_index.py` | `query.area_index` | It is a read-model over summaries and knowledge structure. |
| `src/brain_sync/confluence_rest.py` | `sources.confluence.rest` | It is provider-specific integration code, not a root-level concept. |
| `src/brain_sync/converter.py` | `sources.conversion` | It converts upstream source content into markdown; this is ingestion integration, not a core architectural layer. |
| `src/brain_sync/docx_converter.py` | `sources.docx` | It converts imported document formats; this belongs with source-format integration. |
| `src/brain_sync/attachments.py` | split: `sources.confluence.attachments` and possibly `sync` helper | It currently mixes provider-specific attachment discovery with sync/materialization concerns. It should not survive unchanged as one top-level module. |
| `src/brain_sync/fileops.py` | `brain.fileops` | These helpers encode the correctness-critical brain-root filesystem boundary and are not neutral utilities. |
| `src/brain_sync/fs_utils.py` | `brain.tree` | These functions describe knowledge-tree semantics and content discovery, not generic filesystem behavior. |
| `src/brain_sync/layout.py` | `brain.layout` | It defines portable layout semantics and related runtime path constants; conceptually it is a structural map of the system's persistence surfaces. |
| `src/brain_sync/managed_markdown.py` | `brain.managed_markdown` | It is a portable-brain identity/managed-file primitive. |
| `src/brain_sync/manifest.py` | `brain.manifest` | It is a primitive durable manifest store under the portable seam. |
| `src/brain_sync/sidecar.py` | `brain.sidecar` | It is a primitive portable sidecar store under the portable seam. |
| `src/brain_sync/logging_config.py` | `util.logging` | It is a neutral process-level helper. |
| `src/brain_sync/retry.py` | `util.retry` | It is a neutral retry helper. |

### Current `commands/` package

| Current location | Target package | Ontological justification |
|---|---|---|
| `src/brain_sync/commands/__init__.py` | `application/__init__.py`; keep `commands` as temporary shim package | It re-exports interface-neutral operations consumed by more than the CLI. |
| `src/brain_sync/commands/context.py` | `application.roots` | It resolves operational brain context from config and validates root selection. |
| `src/brain_sync/commands/init.py` | `application.init` | It is an interface-neutral initialize-brain use case. |
| `src/brain_sync/commands/config.py` | `application.config` | It orchestrates credential configuration; it is not a CLI-only command. |
| `src/brain_sync/commands/sources.py` | `application.sources` | It orchestrates source registration, movement, update, and migration across persistence seams. |
| `src/brain_sync/commands/doctor.py` | `application.doctor` | It is a high-level diagnostic use case spanning brain and runtime state. |
| `src/brain_sync/commands/placement.py` | `query.placement` after extraction of mixed helpers; transitional home may remain `application` | Its main purpose is placement/read-model logic, but it currently also contains file/url classification helpers. It is mixed today. |

### Current `cli/` package

| Current location | Target package | Ontological justification |
|---|---|---|
| `src/brain_sync/cli/__init__.py` | `interfaces.cli.parser` or `interfaces.cli.__init__` | It defines CLI parsing, which is an interface concern. |
| `src/brain_sync/cli/handlers.py` | `interfaces.cli.handlers` | It is transport adapter code that translates parsed args into application calls. |

### Current `llm/` package

| Current location | Target package | Ontological justification |
|---|---|---|
| `src/brain_sync/llm/__init__.py` | `llm.__init__` | Stable backend-resolution API. |
| `src/brain_sync/llm/base.py` | `llm.base` | Backend protocol definition. |
| `src/brain_sync/llm/claude_cli.py` | `llm.claude_cli` | Concrete backend integration. |
| `src/brain_sync/llm/fake.py` | `llm.fake` | Deterministic backend for tests. |

### Current `sources/` package

| Current location | Target package | Ontological justification |
|---|---|---|
| `src/brain_sync/sources/__init__.py` | `sources.__init__` | Public source-type API. |
| `src/brain_sync/sources/base.py` | `sources.base` | Adapter protocol and common result types. |
| `src/brain_sync/sources/registry.py` | `sources.registry` | Adapter resolution belongs to the adapter layer. |
| `src/brain_sync/sources/title_resolution.py` | `sources.title_resolution` | It resolves upstream titles and belongs to source integration. |
| `src/brain_sync/sources/confluence/__init__.py` | `sources.confluence.__init__` | Provider package boundary. |
| `src/brain_sync/sources/confluence/auth.py` | `sources.confluence.auth` | Provider-specific auth. |
| `src/brain_sync/sources/confluence/comments.py` | `sources.confluence.comments` | Provider-specific comment integration. |
| `src/brain_sync/sources/googledocs/__init__.py` | `sources.googledocs.__init__` | Provider package boundary. |
| `src/brain_sync/sources/googledocs/auth.py` | `sources.googledocs.auth` | Provider-specific auth. |
| `src/brain_sync/sources/googledocs/rest.py` | `sources.googledocs.rest` | Provider-specific REST integration. |
| `src/brain_sync/sources/test/__init__.py` | `sources.test.__init__` | Test adapter package boundary. |
| `src/brain_sync/sources/test/auth.py` | `sources.test.auth` | Test adapter auth/helper. |

### Resource directories

| Current location | Target package | Ontological justification |
|---|---|---|
| `src/brain_sync/instructions/INSIGHT_INSTRUCTIONS.md` | `regen/resources/INSIGHT_INSTRUCTIONS.md` | It is regen-owned prompt material, not a top-level subsystem. |
| `src/brain_sync/templates/insights/*` | `regen/resources/templates/insights/*` | These are regen-owned output templates. |
| `src/brain_sync/skills/brain_sync/SKILL.md` | `interfaces/mcp/resources/brain_sync/SKILL.md` | The skill describes an integration surface for tool/agent access, not a core domain subsystem. |
| `src/brain_sync/schemas/` | remove unless a real package-owned schema emerges | An empty or generic `schemas/` package has no explanatory power. Schema resources should live under the owning subsystem. |

### Modules that are ambiguous or incorrectly placed today

- `__main__.py`: incorrect today because it conflates interface bootstrap and
  sync daemon orchestration.
- `mcp.py`: correct as an interface, but incorrectly placed at the root and too
  large for a single transport module.
- `commands/`: incorrect name and misleading location because it is already
  consumed as an application API by both CLI and MCP.
- `attachments.py`: ambiguous and mixed. It crosses source-provider specifics,
  sync/materialization concerns, and repository-adjacent helpers.
- `commands/placement.py`: ambiguous because its dominant identity is query,
  but it carries some import/source helper logic.
- `fileops.py` and `fs_utils.py`: incorrectly treated as generic helpers today;
  they encode brain-root semantics and should move under `brain/`.
- `scheduler.py`: incorrectly treated as utility; it belongs to sync.
- `instructions/`, `templates/`, `skills/`, `schemas/`: incorrectly presented
  as peer top-level concepts.

## 4. Naming Corrections

### `commands/` -> `application/`

Recommendation:
Rename `commands/` to `application/`.

Justification:

- The package is already an interface-neutral API consumed by both CLI and MCP.
- "commands" falsely suggests transport-specific command handlers.
- `application` names what the package is: orchestration of user-visible
  operations across underlying subsystems.

Why not `usecases/`:

- `usecases` would be acceptable, but it implies a finer-grained style where
  each file is a single use case object or narrow flow.
- The current modules are grouped operational surfaces such as source admin,
  doctor, and init, which are better described as application services than as
  narrowly isolated use case objects.
- `application` therefore has better explanatory power for the actual codebase.

### `state.py` -> `runtime/repository.py`

Recommendation:
Rename the semantic concept, not merely the filename. The steady-state home
should be `runtime/repository.py`, with a temporary top-level `state.py` shim
if needed.

Justification:

- `state.py` is ontologically weak because every subsystem has state.
- The actual concept is runtime persistence and control.
- A top-level `runtime_repository.py` would be clearer than `state.py`, but the
  stronger end state is a `runtime/` package whose public repository module is
  unambiguously scoped.

### `regen` as a first-class package

Recommendation:
Yes. Elevate regen to a first-class package.

Justification:

- regen already has internal structure: engine, lifecycle, queue, prompt
  resources, templates
- regen already presents a stable conceptual boundary distinct from sync,
  application, and persistence primitives
- the existing single file plus sibling helpers is evidence of a subsystem that
  has outgrown module status

### Additional naming corrections

| Current name | Recommended name | Reason |
|---|---|---|
| `confluence_rest.py` | `sources/confluence/rest.py` | Provider-specific integration should live inside its provider package. |
| `converter.py` | `sources/conversion.py` | The concept is source-content conversion, not a generic converter bucket. |
| `docx_converter.py` | `sources/docx.py` | Same reasoning; name the format/domain, not the tool shape. |
| `area_index.py` | `query/area_index.py` | The concept is query/indexing, not a root-level utility. |
| `commands/context.py` | `application/roots.py` | The concept is operational root resolution, not generic context. |
| `logging_config.py` | `util/logging.py` | Names the capability more directly. |

## 5. Transitional Structure

### Temporary structure during migration

During migration, the tree may temporarily contain both:

- the new target packages
- legacy top-level modules or packages that exist only as import shims

This is tolerated only when the legacy path forwards directly to the new path.

### Immediately required boundaries

These boundaries must be respected as soon as migration begins:

- no new substantive modules may be added at the root of `src/brain_sync/`
- no new code may be added to `commands/` once `application/` exists, except
  shim re-exports
- no new code may be added to top-level `mcp.py`, `brain_repository.py`,
  `state.py`, `pipeline.py`, `reconcile.py`, `watcher.py`, or `regen.py` once
  their package homes exist, except shim imports or clearly marked temporary
  compatibility glue
- no new resources may be added to top-level `instructions/`, `templates/`,
  `skills/`, or `schemas/`

### Inconsistencies temporarily allowed

- old and new import paths may coexist while call sites are being updated
- `state.py` may remain as a top-level shim re-exporting `runtime.repository`
- `brain_repository.py` may remain as a top-level shim re-exporting
  `brain.repository`
- `commands/` may remain as a package shim re-exporting `application`
- `mcp.py` may remain as a root shim forwarding to `interfaces.mcp.server`
- `__main__.py` may remain as a bootstrap shim

### Inconsistencies explicitly forbidden

- introducing new domain logic into shim modules
- creating a generic `core/`, `common/`, `helpers/`, or `shared/` package to
  avoid making a classification decision
- allowing both a legacy package and its replacement package to evolve in
  parallel as if they were peers
- treating resource directories as conceptual subsystems

### Single-file to package promotion rule

When promoting a file module into a package with the same conceptual name, the
promotion must happen in one contained phase for that subsystem. Do not leave
two active homes competing for ownership of one concept.

## 6. Migration Plan

### Phase 1: Establish semantic boundaries with minimal behavior movement

Moves:

- create `brain/`, `runtime/`, and `application/`
- move portable-brain primitives and seams into `brain/`
- move runtime config/repository/telemetry into `runtime/`
- move `commands/*` into `application/*`
- leave explicit shim modules/packages behind at legacy paths

Does not move yet:

- regen subsystem promotion
- sync subsystem promotion
- MCP and CLI package relocation
- attachment/module splitting
- query package promotion if it would force mixed-code extraction immediately

Expected impact:

- high import churn, but mostly mechanical
- low behavioral risk if shims are added immediately
- test updates primarily around imports and private-helper paths

### Phase 2: Promote regen and sync to first-class subsystems

Moves:

- create `regen/` package and move `regen.py`, `regen_queue.py`,
  `regen_lifecycle.py`
- colocate regen instructions and templates under `regen/resources/`
- create `sync/` package and move `pipeline.py`, `reconcile.py`, `watcher.py`,
  `scheduler.py`
- extract daemon loop from legacy `__main__.py` into `sync.daemon`

Does not move yet:

- `mcp.py` into `interfaces/mcp/`
- `attachments.py` split
- provider-level file relocations such as `confluence_rest.py`

Expected impact:

- medium to high import churn
- daemon and regen tests will need targeted updates
- resource-loading paths must be updated carefully

### Phase 3: Normalize interface and query layers

Moves:

- create `interfaces/` package
- move CLI parser/handlers into `interfaces/cli/`
- move MCP server into `interfaces/mcp/server.py`
- create `query/` package
- move `area_index.py` into `query/area_index.py`
- move placement logic into `query/placement.py`, leaving only minimal
  application glue where needed

Does not move yet:

- final split of `attachments.py` if deeper extraction is still needed
- optional cleanup of transitional helper names inside modules

Expected impact:

- medium import churn
- MCP tool tests and CLI subprocess tests will need path updates
- lower behavioral risk than Phase 2 if shims are kept small

### Phase 4: Provider alignment and top-level cleanup

Moves:

- move `confluence_rest.py` into `sources/confluence/rest.py`
- move conversion helpers into `sources/`
- split `attachments.py` into provider-specific and sync-specific homes
- remove empty or non-conceptual top-level packages such as `schemas/`
- relocate skill resource under interface-owned resources
- remove legacy root shims once no in-repo imports remain

Does not move yet:

- behavioral redesign of attachments, placement heuristics, or regen algorithms

Expected impact:

- targeted churn rather than broad churn
- highest risk is hidden import coupling in tests and private imports
- by the end of this phase the root package should be almost entirely shims and
  package directories

## 7. Compatibility and Shim Strategy

### Allowed shim forms

- top-level module re-export, for example `brain_repository.py` importing and
  re-exporting from `brain.repository`
- package shim re-export, for example `commands/__init__.py` re-exporting from
  `application`
- root bootstrap shim in `__main__.py`

### Shim rules

- shims must contain no new domain logic
- shims must be thin and explicit
- shims must not chain through multiple layers of re-export
- shims should prefer explicit symbol re-export over wildcard export unless the
  package surface is already explicitly curated

### Deprecation approach

- update all in-repo imports to the new package path in the same phase that
  creates the new package
- keep legacy shims only long enough to avoid unnecessary breakage for tests,
  scripts, or external automation
- remove a shim once there are no remaining in-repo imports and one full phase
  has passed without the shim gaining new logic

Long-lived indirection is explicitly rejected.

## 8. Test and Refactor Impact

### Import breakage surface

High. This repository imports directly from many root modules today, and a
number of tests import private helpers.

Highest breakage surfaces:

- `tests/unit/test_regen.py` and other regen-focused tests
- tests reaching into `state._connect` or other runtime internals
- CLI subprocess tests relying on current entrypoint locations
- MCP tests importing the current root `mcp.py` module

### Test updates required

- update direct imports to new package locations
- preserve temporary compatibility for subprocess entrypoints via shims
- update monkeypatch targets where module paths move
- update resource-loading tests when `instructions/` and `templates/` relocate
- update any tests that reach private helpers by old module path

### Risk areas

- `regen.py` currently exposes many helpers that tests may target directly
- `__main__.py` is currently both bootstrap and operational code
- `attachments.py` is mixed and may hide incidental dependencies
- source adapters currently reference runtime-layer types
- resource loading by `importlib.resources` can break if package paths change

## 9. Governance Rules

The following rules should be added to `AGENTS.md` and reflected in
`docs/architecture/ARCHITECTURE.md` once migration begins.

### Placement rules

- New modules must be added to the owning subsystem package, not to the root of
  `src/brain_sync/`.
- New top-level root files are forbidden except `__init__.py`, `__main__.py`,
  and temporary migration shims.
- A new package is valid only if its name denotes a real subsystem boundary
  whose membership can be stated positively and whose dependencies are
  directional.

### Boundary rules

- `brain` is the portable-brain persistence boundary.
- `runtime` is the machine-local persistence boundary.
- `application` orchestrates use cases but does not own durable persistence
  primitives.
- `interfaces` adapt transport and presentation only.
- `sources` contains source-specific integration only.
- `query` is read-only over portable state and regen outputs.
- `util` must remain minimal and domain-neutral.

### Legacy-structure rules

- Legacy root modules and `commands/` may exist only as compatibility shims once
  their new homes exist.
- No new logic may be added to legacy locations.
- New code must import from the target package path, not from a shim path.

### Resource rules

- Packaged resources must live under the subsystem that owns them.
- Top-level `instructions/`, `templates/`, `skills/`, and `schemas/` must not
  grow as peer architecture areas.

### Review rules

- Every new package introduction must state responsibility, membership, and
  forbidden contents in its module docstring or nearby architecture docs.
- Any proposal for a new package named `core`, `common`, `helpers`, `shared`,
  or `utils` beyond the existing minimal `util` package should be rejected by
  default.

## 10. Explicit Non-goals

This pass does not include:

- behavioral refactors of sync, regen, query, or source logic
- redesign of core algorithms
- changes to Brain Format or runtime DB contract
- observability implementation
- redesign of MCP tool surface or CLI UX
- new abstraction layers beyond the minimum packages needed to express real
  subsystem boundaries
- speculative extraction of reusable frameworks or plugin APIs

## Acceptance Criteria

The restructuring plan should be considered successfully executed only when all
of the following are true:

1. The source tree names real subsystems rather than convenience buckets.
2. The root package is no longer a flat map of unrelated implementation files.
3. `brain` and `runtime` exist as explicit persistence-plane packages.
4. `regen` exists as a first-class subsystem package.
5. `application` replaces `commands` as the interface-neutral orchestration
   layer.
6. `interfaces` isolates CLI and MCP transport concerns.
7. `sync` isolates ingest/watch/reconcile mechanics.
8. `query` isolates read-model logic such as indexing and placement.
9. Top-level resource directories have been absorbed by their owning
   subsystems or removed.
10. Legacy paths survive only as temporary shims with no new logic.

## Reviewer Focus

The reviewer should concentrate on these questions:

1. Do the proposed package names describe real system concepts rather than
   convenience groupings?
2. Are dependency directions explicit, one-way, and enforceable?
3. Does the plan keep `brain` and `runtime` as separate persistence planes?
4. Is `application` the right name and scope for the current `commands/`
   package?
5. Does the plan correctly treat regen as a first-class subsystem?
6. Are mixed modules such as `attachments.py` and `commands/placement.py`
   handled honestly rather than hidden inside vague package names?
7. Does the phased migration minimize long-lived shims and conceptual drift?

## Next Step After Review

If review identifies issues, the planner should create a revised plan artifact
rather than editing this file.

If the plan is acceptable, the next required action is a separate approval
artifact under the `docs/plans/` workflow. This file is not approval and does
not authorize implementation by itself.

# Rules

This document defines the system invariants and behavioural guarantees
for brain-sync. These rules describe the cross-cutting ontology and
state-mutation rules that must always hold for a valid
[brain](GLOSSARY.md#brain) and its associated [runtime state](GLOSSARY.md#runtime-state).

Implementations may change internally, but these rules define the
external behaviour of the system.

This is the normative home for cross-cutting invariants, guarantees, and
precedence rules. For design rationale, module ownership, and tradeoffs, see
`docs/architecture/ARCHITECTURE.md`.

Terminology used here is defined in [GLOSSARY.md](GLOSSARY.md).

---

## Brain Contract

A brain is a filesystem-backed knowledge system.

**What the brain guarantees:**

- [User knowledge](GLOSSARY.md#user-knowledge) is never modified or
  deleted by the system except for managed identity
  [frontmatter](GLOSSARY.md#frontmatter) in
  [synced source](GLOSSARY.md#synced-source) files.
- [Generated meaning](GLOSSARY.md#generated-meaning) is always
  produced from user knowledge.
- Deleting [runtime state](GLOSSARY.md#runtime-state) never damages the
  brain.

**What the system guarantees:**

- The filesystem is authoritative. The system adapts to what it finds on
  disk.
- All durable state required to reconstruct the brain exists inside the
  [brain root](GLOSSARY.md#brain-root) as portable files.
- Every file the system owns lives under a `.brain-sync/` directory.

**What users may freely do:**

- Create, edit, move, rename, and delete their own files and folders
  anywhere in the [knowledge tree](GLOSSARY.md#knowledge-tree).
- The system will detect these changes and adjust its state accordingly
  — either in real time via the [watcher](GLOSSARY.md#watcher) or at
  next startup via [reconciliation](GLOSSARY.md#reconciliation).

---

## Brain State Invariants

### Filesystem Authority

The filesystem is the authoritative representation of brain state.

The system must be able to reconstruct its runtime state entirely from:

- [user knowledge](GLOSSARY.md#user-knowledge)
- [manifests](GLOSSARY.md#manifest)
- [generated meaning](GLOSSARY.md#generated-meaning)

Deleting runtime artifacts must never destroy durable knowledge.

### Durable Brain State

Brain state consists of:

- the [knowledge tree](GLOSSARY.md#knowledge-tree)
- [brain managed files](GLOSSARY.md#brain-managed-files) inside the
  [brain root](GLOSSARY.md#brain-root)

Brain state is the durable state of the entire
[brain root](GLOSSARY.md#brain-root), not only the `knowledge/` subtree.
It is portable and must be fully reconstructable on another machine.

Portable managed files must only be rewritten when their durable serialized
content actually changes. Runtime-only coordination changes must remain in
[runtime state](GLOSSARY.md#runtime-state) and must not churn unchanged
portable files inside the brain root.

### Runtime State

[Runtime state](GLOSSARY.md#runtime-state) is machine-local and not part
of the brain contract.

Examples:

- the [brain-sync runtime directory](GLOSSARY.md#brain-sync-runtime-directory)
  (database, configuration, logs, daemon status)

Deleting runtime state must not damage brain state.

On process start or brain re-attachment, persisted runtime state must be
treated as non-authoritative cached local history. It may inform local
recovery, scheduling, and coordination, but it must not by itself assert
current brain state or authorize lifecycle actions until it has been
reconciled against the currently attached portable brain and fresh local
observation.

Portable brains must remain valid across process restarts, runtime rebuilds,
and later attachment by a different runtime instance over time.

brain-sync supports at most one active daemon per runtime config directory at a
time. In the current single-brain runtime model, that also means at most one
active daemon attachment to the attached brain. A second daemon start against
the same config dir must be refused at startup rather than allowed to coexist
opportunistically. `daemon.json` is runtime status only; durable startup
exclusion must come from the config-dir daemon guard itself.

### REGEN Observability Contract

REGEN diagnostics must stay within the approved runtime surfaces:

- `operational_events` is the durable semantic decision trail
- `token_events` is the durable per-call cost and duration trail
- `regen_locks` is runtime coordination only and must not become an analytics
  or historical-diagnostics surface

For REGEN specifically:

- semantic reasons for why a path ran, skipped, failed, or propagated belong
  in `operational_events`
- prompt-planning details such as prompt-budget class, component token
  breakdown, deferred files, and omitted child summaries belong in
  `operational_events` details for the relevant REGEN session
- invocation-level token, duration, success, and chunk-versus-final-call facts
  belong in `token_events`
- aggregated REGEN reports must be derived from those existing surfaces rather
  than by introducing a new runtime table unless a later approved change
  explicitly authorizes one

Loss, duplication, or pruning of REGEN diagnostics must not change lifecycle
authority or portable-brain semantics.

### Managed Namespace

The folder name `.brain-sync` is reserved at every level of the brain.

Brain managed files may exist in:

- `.brain-sync/` (root)
- `knowledge/**/.brain-sync/`

The system may create, update, or delete managed files at any time.
User knowledge must not depend on managed files for correctness.
Regenerability depends on the managed-content kind. Generated meaning is
typically regenerable; manifests, journals, and other durable managed artifacts
follow their owning rules.

---

## Code Boundary Rules

These rules are normative for future feature work and refactoring. For
explanatory rationale and subsystem discussion, see
`docs/architecture/ARCHITECTURE.md`.

Architecture fitness tests in `tests/unit/test_architecture_boundaries.py`
enforce these package-boundary rules, the closed orchestration-surface set,
and the exact file-level exceptions listed below.

### Canonical Package Owners

The canonical subsystem packages are:

- `application`
- `interfaces`
- `brain`
- `runtime`
- `sync`
- `regen`
- `query`
- `sources`
- `llm`
- `util`

New substantive code must be added to the owning subsystem package, not to the
root of `src/brain_sync/`.

Canonical package paths are the supported Python import surface. Transitional
root-module and legacy package aliases from the module-ontology migration are
not part of the supported compatibility contract.

### Persistence Plane Ownership

Portable brain semantics belong to `brain/`.
Machine-local runtime semantics belong to `runtime/`.

Portable layout helpers belong to `brain.layout`.
Machine-local runtime path helpers belong to `runtime.paths` or
`runtime.config`.

Normal runtime code must treat `brain.repository` as the portable-brain write
boundary and `runtime.repository` as the runtime-state write boundary.

### Dependency Direction

For normal subsystem modules, the allowed package directions are:

- `interfaces -> application`
- `application -> brain / runtime / sync / regen / query / sources / llm / util`
- `sync -> brain / runtime / regen / sources / util`
- `regen -> brain / runtime / llm / util`
- `query -> brain / util`
- `sources -> util`
- `llm -> util`
- `brain -> util`
- `runtime -> util`

Lower-level packages must not import upward into entrypoints, `application`, or
transport layers unless explicitly listed below.

### Closed Orchestration Surfaces

The following files are the only named orchestration / entrypoint surfaces:

- `src/brain_sync/__main__.py`
- `src/brain_sync/interfaces/cli/handlers.py`
- `src/brain_sync/interfaces/mcp/server.py`
- `src/brain_sync/sync/daemon.py`

These files are allowed to compose multiple lower subsystems because bootstrap,
transport adaptation, and long-running process wiring are their explicit job.
This status belongs to the named file, not to the containing package.

No new orchestration surface may be added without updating this document and
the architecture fitness tests.

### Exact Allowed Exceptions

The following off-graph imports are intentionally allowed today:

| File | Allowed non-graph imports | Why |
|---|---|---|
| `src/brain_sync/query/placement.py` | `brain_sync.sources.docx` | Local `.docx` excerpt extraction for placement heuristics |
| `src/brain_sync/sources/confluence/attachments.py` | `brain_sync.brain.repository`, `brain_sync.sync.attachments` | Provider-specific attachment discovery bridging to sync-owned materialization |
| `src/brain_sync/sources/confluence/auth.py` | `brain_sync.runtime.config` | Provider auth may read and write machine-local config |
| `src/brain_sync/sources/confluence/rest.py` | `brain_sync.runtime.config` | Provider REST auth loading needs machine-local config |
| `src/brain_sync/sources/googledocs/auth.py` | `brain_sync.runtime.config` | OAuth token loading and persistence are machine-local |
| `src/brain_sync/sources/test/__init__.py` | `brain_sync.runtime.config` | Test adapter subprocesses may resolve the configured brain root |

These exceptions are exact and closed. Do not generalize them into package-wide
allowances without an intentional architecture decision.

### Package Ownership Constraints

`sources/` owns provider-specific behavior only. Shared code must not grow
source-type conditionals when an adapter capability can express the behavior.

`query/` is read-oriented and must not take ownership of durable writes or
daemon orchestration.

`sync/` and `regen/` are peer subsystems. One must not quietly absorb the
other's ownership.

`util/` must remain minimal and domain-neutral. If a helper knows what a
brain, manifest, source, area, or runtime row is, it does not belong in
`util/`.

### Shim Discipline

Compatibility shims are exceptional and temporary. None are currently part of
the supported import surface.

If a future shim is introduced, it must:

- have an explicit compatibility rationale
- avoid new domain logic
- be documented in `docs/COMPATIBILITY.md`
- have a planned removal path

---

## Top-Level Layout

A valid [brain root](GLOSSARY.md#brain-root) contains exactly two
top-level entries:

```
{brain_root}/
├── .brain-sync/                   # global managed namespace
│   ├── brain.json                 # brain manifest
│   └── sources/                   # one manifest per synced source
│       ├── c987654.json
│       └── g1zo3...U.json
└── knowledge/                     # the durable brain
    ├── _core/                     # optional core knowledge
    │   ├── mission.md
    │   └── .brain-sync/
    ├── teams/
    │   └── platform/
    │       ├── c987654-attachment-handling.md
    │       ├── platform-notes.md
    │       └── .brain-sync/
    └── .brain-sync/               # root area managed state
```

### Root `.brain-sync/`

Root `.brain-sync/` is the global managed namespace. It contains:

- `brain.json` — brain [manifest](GLOSSARY.md#manifest)
- `sources/*.json` — one source manifest per registered synced source

It does not contain durable user knowledge or runtime state. The
[brain-sync database](GLOSSARY.md#brain-sync-database) lives in the
[brain-sync runtime directory](GLOSSARY.md#brain-sync-runtime-directory), not
here. This means the entire brain root is portable and committable to
git with no `.gitignore` exceptions needed.

### `knowledge/`

`knowledge/` is the durable brain. It contains:

- user-authored documents
- [synced source](GLOSSARY.md#synced-source) materialized documents
- per-area `.brain-sync/` managed subtrees

If `knowledge/` does not exist, `brain-sync init` creates it.

---

## Knowledge Areas

A [knowledge area](GLOSSARY.md#knowledge-area) is any directory under
`knowledge/` that participates in regeneration.

A directory is a knowledge area if it:

- contains readable files, or
- has descendant [knowledge areas](GLOSSARY.md#knowledge-area)

This means the regen topology follows the semantic area tree, not the raw
filesystem tree.

Areas are the unit of [generated meaning](GLOSSARY.md#generated-meaning).
Each area may have a managed subtree:

```
knowledge/<area>/.brain-sync/
├── insights/
│   ├── summary.md
│   └── insight-state.json
├── journal/
│   └── YYYY-MM/
│       └── YYYY-MM-DD.md
└── attachments/
    └── <source_dir_id>/
        └── a<attachment_id>-<slug>.<ext>
```

`knowledge/` itself is a valid area. The root area participates in
regeneration and reconciliation like any other area, except it is the
top of the wave topology and has no parent to propagate to.

Directories under `knowledge/` that contain neither readable files nor
descendant knowledge areas are not knowledge areas. They may exist in the
filesystem for structural organisation, but they are not part of the semantic
regen tree.

### Area Lifecycle

An area comes into existence when a directory under `knowledge/` first
either contains readable content or has descendant knowledge areas. It gets a
`.brain-sync/` subtree when
brain-sync first generates meaning for it.

An area ceases to exist when its directory is deleted or when it contains
neither readable content nor descendant knowledge areas. When this happens,
the system cleans up the area's managed state (insights and insight state) but preserves
[journals](GLOSSARY.md#journal) which are durable.

### Regen Propagation

[Regeneration](GLOSSARY.md#regeneration) uses a **wave topology** —
depth-ordered, deepest-first:

1. All areas at the deepest level are processed first (from their own
   content).
2. Their parents are processed next (from child summaries, not raw child
   content).
3. Each wave propagates upward only when at least one child changed.
4. Each area is processed at most once per regen cycle.

See [GLOSSARY.md — Regeneration](GLOSSARY.md#regeneration).

### Core Knowledge

`knowledge/_core/` is optional raw core knowledge created by
`brain-sync init`. During regeneration, raw `_core` files are loaded
only when brain-sync is regenerating `_core` itself. Other areas receive
global context via `_core`'s generated summary when it exists.
Deterministic query/search does not implicitly inject raw `_core` files;
there `_core` behaves like any other area through its generated meaning
and indexed artifacts. If deleted, brain-sync continues by assuming no
global context. See
[GLOSSARY.md — Core Knowledge](GLOSSARY.md#core-knowledge).

---

## User Operations

The brain is designed for user flexibility. The system adapts to
filesystem changes through two mechanisms:

- **Online** (daemon running): the [watcher](GLOSSARY.md#watcher)
  detects changes in real time and queues affected areas for processing.
- **Offline** (daemon not running):
  [reconciliation](GLOSSARY.md#reconciliation) at next startup detects
  all changes that occurred while the daemon was down.

Both mechanisms produce the same eventual result. The system is
eventually consistent.

### User-Authored Files

| Operation | Online | Offline |
|---|---|---|
| Create file | Area queued for regen (30s debounce) | Area queued at reconciliation |
| Edit file | Area queued for regen | Area queued at reconciliation |
| Delete file | Area queued for regen | Area queued at reconciliation |
| Rename file | Area queued for regen | Area queued at reconciliation |
| Move file to another area | Both old and new areas queued for regen | Both areas queued at reconciliation |

User-authored files are never modified by the system. The user has full
control.

### Synced Source Files

| Operation | Online | Offline |
|---|---|---|
| Edit file | Edits preserved until next sync, then **overwritten** by remote content | Same |
| Delete file | Watcher/reconcile writes portable `knowledge_state = missing`, records machine-local missing confirmation, and removes the source from active polling | Same |
| Explicit finalize missing source | Dedicated finalization entrypoint removes the manifest last after revalidation and cleanup | Same |
| Rename file | Reconciliation rediscovers by identity and writes updated `knowledge_path` plus `knowledge_state = stale` | Same |
| Move to another area | Watcher/reconcile writes updated `knowledge_path` plus `knowledge_state = stale` as early as possible | Same |

**Key behaviour:** When a user deletes a synced source file, the system
treats the user as authoritative. The source will not reappear — the
user must explicitly re-add it. The two-stage missing protocol provides
a grace period against accidental deletions or transient filesystem
states.

**Compromise:** User edits to synced source files are overwritten on
next sync. This is by design — the remote source is authoritative for
synced content. Users who want to annotate should create a separate
user-authored file in the same area.

Explicit source removal is destructive to synced source material:

- remove source: source registration, managed markdown, and source-owned
  attachments are deleted together
- user-driven filesystem deletion is the softer path that enters the missing
  lifecycle first and only leaves the registry through explicit finalization if
  the source is still absent

Explicit source moves are source-scoped:

- move source may relocate only source-owned artifacts for the addressed
  source
- colocated user-authored files and unrelated synced sources in the same area
  must remain in place

### Folders

| Operation | Online | Offline |
|---|---|---|
| Create folder with content | New area detected, queued for regen | New area detected at reconciliation |
| Rename folder | Manifests update `knowledge_path`; materialized/stale sources become `stale`; insights move with the folder | Reconciliation detects new path, updates manifests and DB |
| Move folder | Same as rename | Same as rename |
| Delete folder | All contained synced sources enter missing protocol; area insights cleaned up; journals preserved if possible | Reconciliation handles each contained source individually |
| Delete empty folder | No action (was not an area) | No action |

Because generated meaning lives under `knowledge/<area>/.brain-sync/`,
folder moves automatically carry insights with them. No separate mirror
operation is needed.

### Attachments

| Operation | Online | Offline |
|---|---|---|
| Source deregistered | Attachments under `.brain-sync/attachments/<source_dir_id>/` cleaned up | Same at reconciliation |
| Source moved to another area | Attachments move with the folder (co-located under `.brain-sync/`) | Same |
| User deletes attachment file | System may re-download on next sync if source still active | Same |
| User deletes attachment directory | System may re-download on next sync | Same |

Attachments are stored per-source under
`.brain-sync/attachments/<source_dir_id>/` in the area where the source
lives. Each source's attachments are physically isolated, so no
cross-source reference counting is needed. Deleting a source's
attachments is a simple `rmtree` of its directory.

### Managed Files (`.brain-sync/`)

Users should not modify `.brain-sync/` directories. If they do:

| Operation | System response |
|---|---|
| Delete `insights/summary.md` | Regenerated on next regen cycle |
| Delete `insights/insight-state.json` | Regenerated on next regen cycle (full regen, no hash comparison possible) |
| Delete `insights/` directory | Regenerated on next regen cycle |
| Delete `journal/` directory | **Permanent loss** — journals are not regenerable |
| Delete area `.brain-sync/` entirely | Insights regenerated; journals permanently lost |
| Delete source manifest | Source deregistered — will not sync or reappear |
| Edit source manifest | System uses edited values; invalid edits may cause errors detected by doctor |
| Delete root `.brain-sync/` | Brain identity lost; `brain-sync init` or doctor required to restore |
| Delete `brain.json` | Doctor can recreate |
| Delete database (in `~/.brain-sync/`) | Rebuilt from manifests and insight state on next startup |

**Compromise:** Journals are the one class of managed file that cannot
be recovered if deleted. This is inherent — they capture point-in-time
observations that cannot be regenerated from current knowledge.

If a user places their own files inside `.brain-sync/`, doctor reports
this as [DRIFT](GLOSSARY.md#doctor). `doctor --fix` may clean stale
managed artifacts there, but it must never move or delete user-authored
content from the managed namespace.

---

## Identity Rules

A [synced source](GLOSSARY.md#synced-source) has exactly one
[canonical ID](GLOSSARY.md#canonical-id).

### Identity Resolution Chain

When the system needs to locate a synced source file, it uses three-tier
resolution (ordered by priority):

1. **Manifest `knowledge_path`** — direct file path check.
2. **Frontmatter identity scan** — search `knowledge/` for a file
   containing the matching `brain_sync_canonical_id`.
3. **Canonical prefix glob** — filename prefix match
   (e.g. `c12345-*.md`).

### Identity Stability

Moving or renaming a synced source file must not change its identity.

Identity survives:

- file rename (slug change)
- file move to another area
- folder rename of the containing area

Identity is lost if the user removes both the frontmatter header and
renames the file to remove the canonical prefix. This is the one
scenario where reconciliation cannot recover the association. Doctor
reports this as DRIFT.

### Identity Uniqueness

At most one materialized markdown file may carry a given
`brain_sync_canonical_id` within the `knowledge/` tree.

If multiple files carry the same canonical ID, the brain is in
DRIFT. Repair must collapse those duplicates back to a
single surviving materialized file and update source tracking to point
to that file.

Filename prefixes remain derived hints, not independent identities. A
title change may change the filename slug, but it must not produce a
second file with the same canonical ID.

---

## Materialization Rules

[Materialization](GLOSSARY.md#materialization) converts a remote source
into a markdown document.

Materialization must:

- embed authoritative identity [frontmatter](GLOSSARY.md#frontmatter)
- merge with any existing YAML frontmatter by updating only the
  `brain_sync_*` keys and preserving all other keys
- write the file to the knowledge tree under the source's current anchored
  `knowledge_path` parent
- update `knowledge_path`, `knowledge_state = materialized`, `content_hash`,
  `remote_fingerprint`, and `materialized_utc` in the source manifest
- preserve the [canonical ID](GLOSSARY.md#canonical-id)

Materialization must not modify unrelated user knowledge.

When synced attachments are materialized into the same area, markdown may
link to them via relative paths under
`.brain-sync/attachments/<source_dir_id>/`. Because the attachments live
inside the same area subtree as the document, folder moves preserve link
validity automatically.

---

## Reconciliation Rules

[Reconciliation](GLOSSARY.md#reconciliation) aligns system state with
filesystem truth. It runs at daemon startup and can be triggered
manually.

Reconciliation must:

- detect file moves (via three-tier identity resolution)
- detect file deletions (two-stage missing protocol)
- detect new or changed content (hash comparison)
- repair stale manifest paths
- prune orphan database rows

Filesystem truth always overrides stale runtime state.

### Two-Stage Missing Protocol

When a synced source file cannot be found:

1. **Observation / confirmation:** source manifest is updated to
   `knowledge_state = missing`, the source remains registered, and the runtime
   `source_lifecycle_runtime` row records local missing confirmation history.
2. **Explicit finalization:** destructive cleanup may happen only through the
   dedicated finalization lifecycle entrypoint after fresh revalidation against
   the current portable brain and current filesystem state.

This provides a grace period for temporary filesystem states (e.g. file
being moved by an external tool, cloud sync in progress).

Watcher-driven reconcile is non-finalizing. While the daemon is running, the
watcher may write first-stage `missing` or repair rediscovered paths, but it
must not perform destructive finalization. Startup reconcile and explicit
reconcile are also non-destructive with respect to missing-source cleanup.

A source in `knowledge_state = missing` is still registered during that grace
period. Duplicate add attempts must fail until the source is either
rediscovered or explicitly finalized.

Explicit finalization is a single-source operation. CLI and MCP finalization
entrypoints must accept exactly one registered source canonical ID and must
reject URLs, filesystem paths, helper IDs, and bulk target syntax.

Inherited runtime history is not sufficient by itself to authorize destructive
finalization. Finalization may proceed only when all of the following are
true:

- the source manifest still exists
- the durable `knowledge_state` is still `missing`
- no conflicting active source-level lifecycle lease exists
- the runtime row retains at least two missing confirmations
- the most recent retained missing confirmation was recorded by the current
  lifecycle session after fresh revalidation

If any of those conditions are not met, explicit finalization must remain
non-destructive and return a pending-confirmation style outcome after writing a
fresh local missing confirmation for the current lifecycle session.

### Same-Source Lifecycle Serialization

For a single registered source, lifecycle-owning entrypoints must serialize
destructive or path-mutating work through source-level runtime leases.

Lease-taking lifecycle entrypoints include:

- explicit finalization
- explicit source removal
- explicit source move
- root-backed materialization for a registered source

If one of those entrypoints encounters an active conflicting lease, it must not
silently proceed. Command surfaces should return a handled lease-conflict
outcome rather than mutating portable or runtime state for that source.

Watcher and reconcile paths are intentionally softer. If they encounter an
active conflicting lease for a source they were about to repair, rediscover,
mark missing, or clean up, they must revalidate current state and skip that
source rather than overwriting lifecycle-owned coordination.

For explanatory synced-source lifecycle models, event matrices, and state
diagrams, see [sync/README.md](sync/README.md).

---

## Regeneration Rules

[Regeneration](GLOSSARY.md#regeneration) produces
[generated meaning](GLOSSARY.md#generated-meaning) from user knowledge.

### Wave Topology

Regeneration processes areas depth-first:

1. Deepest areas regenerate from their own readable files.
2. Parent areas regenerate from child summaries only (not raw child
   content).
3. Dirty propagation: a parent is only processed when at least one child
   produced a different result.
4. Each area is processed at most once per cycle.

### Change Detection

[Change detection](GLOSSARY.md#change-detection) determines whether an
area needs regeneration:

| Hash | Inputs | Changed means |
|---|---|---|
| content hash | SHA-256 of readable file contents + child summaries | Semantic input changed — regeneration needed |
| structure hash | SHA-256 of child directory names + filenames | Structural change only (e.g. rename) — update metadata, no LLM call |
| summary hash | SHA-256 of the generated summary text | Used for stability guard comparison |

**Content hash computation** is deterministic and rename-tolerant:
file hashes are sorted by their SHA-256 values (not filenames), so
renaming a file without changing its content produces the same content
hash.

**Structure hash computation** captures directory and file names to
detect structural reorganisation.

### Regen Lifecycle

Each area goes through a classification before any LLM invocation:

1. **No content** — area has no readable files and no child summaries.
   Clean up stale insights. Skip.
2. **Unchanged** — content hash matches previous. No work needed. Stop
   propagation.
3. **Rename only** — content hash unchanged, structure hash changed.
   Update structure hash in insight state. Propagate (parent may need to
   update references).
4. **Content changed** — invoke LLM to regenerate summary.
5. **Similarity guard** — if new summary is >0.97 similar to existing,
   discard rewrite. Treat as unchanged for propagation.
6. **Regenerated** — new summary written, insight state updated,
   optional journal entry appended.

### Regen Queue

The watcher feeds filesystem events into a regen queue with:

- **Debounce** (30s default) — batch rapid changes before processing.
- **Cooldown** (5min default) — prevent re-processing an area too
  quickly after a regen.
- **Rate limit** (20/hour default) — cap total regen throughput.
- **Retry** — failed regens retry with backoff (30s, 60s, 120s) up to
  3 attempts.

Debounce is also the online reconciliation boundary. The watcher is a
signal mechanism, not a transaction processor: it may batch filesystem
events during the debounce window, but before regeneration starts for
any ready area the system must apply pending manifest and path updates so
durable state reflects filesystem truth.

Walk-up: when a single area is regenerated (e.g. from a watcher event),
the system walks up toward the root, regenerating each parent. Walk-up
stops when the shared propagation matrix says no parent-visible input
changed. In queue processing this remains a bounded special case only when
exactly one ready seed is in the current debounce snapshot; otherwise queue
processing must use one explicit wave batch for the ready set.

### Stability Guard

The [stability guard](GLOSSARY.md#stability-guard) prevents unnecessary
churn.

When a regenerated summary is >0.97 similar (by `SequenceMatcher` after
whitespace normalisation) to the existing summary, the rewrite is
discarded. This prevents minor upstream wording changes from cascading
through the entire knowledge tree.

### Regen Context Assembly

When regenerating an area, the prompt includes:

1. **Instructions** — regen directives and templates bundled with the
   brain-sync package.
2. **Global context** — `_core`'s generated summary for non-`_core`
   areas, or raw [core knowledge](GLOSSARY.md#core-knowledge) files from
   `knowledge/_core/` when regenerating `_core` itself.
3. **Area files** — readable files in the area (for leaf areas).
4. **Child summaries** — summaries from child areas (for parent areas).
5. **Existing summary** — current summary for stability comparison.

Token budget is managed by greedy packing (largest files first) with
chunking for oversized files. Files that don't fit are deferred to
separate chunks processed in sequence.

### Journal Entries

[Journals](GLOSSARY.md#journal) are appended during regeneration when
the LLM determines a meaningful event has occurred (decision, milestone,
risk, status change).

Journals are:

- append-only (entries are never modified or deleted by the system)
- durable (survive all automated cleanup including orphan detection)
- not regenerable (point-in-time observations cannot be reconstructed)
- organised by day: `journal/YYYY-MM/YYYY-MM-DD.md`

---

## Schema Authority

This document does not restate field-by-field schema tables. Authoritative
persisted shapes live in:

- [`docs/brain/SCHEMAS.md`](brain/SCHEMAS.md) — portable manifests and synced
  source frontmatter
- [`docs/runtime/SCHEMAS.md`](runtime/SCHEMAS.md) — machine-local runtime
  files and runtime DB tables

The cross-cutting schema rules that matter here are:

- portable schema artifacts live inside the [brain root](GLOSSARY.md#brain-root)
  at `.brain-sync/brain.json`,
  `.brain-sync/sources/<source_dir_id>.json` (where `source_dir_id` is the
  [source directory ID](GLOSSARY.md#source-directory-id)), and
  `knowledge/<area>/.brain-sync/insights/insight-state.json`
- runtime schema artifacts live in the
  [brain-sync runtime directory](GLOSSARY.md#brain-sync-runtime-directory),
  including `config.json`, `daemon.json`, and `db/brain-sync.sqlite`
- every durable manifest is self-versioned using a `version` field
- `meta.schema_version` is authoritative only for interpreting the runtime DB
- `knowledge_path` is the durable source path anchor
- `brain_sync_*` frontmatter is the authoritative document-level identity
  binding for materialized synced documents
- `fetch_children` and `child_path` are operational inputs, not durable
  portable manifest fields
- machine-local missing-observation timestamps and explicit-finalization leases
  live in runtime schema `v29`, not in portable manifests

### Packaged Regen Resources

Regen templates (summary layout, journal format, etc.) are internal to
the brain-sync package. They are bundled in the source code and loaded
at runtime — not deployed to the brain root.

Users who want to influence regen behaviour should add instructions to
[core knowledge](GLOSSARY.md#core-knowledge) (`knowledge/_core/`).

---

## Recovery Guarantees

The system must remain usable if runtime artifacts are lost.

### Doctor

[Doctor](GLOSSARY.md#doctor) validates invariants and repairs drift:

**Must validate:**

- required root structure (`knowledge/`, `.brain-sync/`)
- reserved folder misuse
- malformed manifests
- missing managed files where invariants require them
- broken source registration references
- broken attachment references
- stale insight state (hashes don't match disk content)

**May safely repair:**

- create missing root directories
- recreate missing database from manifests and insight state
- repair stale manifest paths
- recreate `brain.json`

**Must not:**

- silently invent semantic content
- delete user knowledge
- delete journals

### Backup

The durable backup unit is the brain root.

Because [runtime state](GLOSSARY.md#runtime-state) lives entirely in
the [brain-sync runtime directory](GLOSSARY.md#brain-sync-runtime-directory)
(outside the brain root), no `.gitignore` is needed. The entire brain
root — including all `.brain-sync/` directories — is portable and
committable.

---

## Manifest Versioning

Every durable brain-sync manifest is self-versioned. The field name is
always `version`.

Files that carry a `version` field:

- `brain.json`
- source manifests (`.brain-sync/sources/*.json`)
- insight state manifests (`knowledge/<area>/.brain-sync/insights/insight-state.json`)

---

## Structural Simplifications

This section summarises the current structural model behind the Brain
Format 1.2 rules.

### Co-located insights move with their area

Insights live under `knowledge/<area>/.brain-sync/`. When a user moves
or renames a folder, the managed insight state travels with it
automatically. The watcher only needs to update manifest paths and DB
state rather than coordinate a second mirrored tree.

### Directory-based attachment isolation

Attachments live at
`knowledge/<area>/.brain-sync/attachments/<source_dir_id>/`. Each
source's attachments are physically isolated, so cleanup is a simple
`rmtree` of that source's directory and does not require cross-source
reference counting.

### Single reserved namespace

`.brain-sync/` is the single reserved namespace at every level. All
managed state lives under it. The dot-prefix provides automatic
exclusion from content discovery, regen scanning, and filesystem
watching.

### Operational flags stay out of manifests

`fetch_children` and `child_path` are one-shot operational commands, not
durable source state. Brain Format 1.2 treats them as command
parameters consumed at execution time, keeping manifests focused on
durable registration intent. `child_path` only has meaning while there is an
active pending child-discovery request; it must not persist as latent durable
or runtime configuration once `fetch_children` is no longer pending.

---

## Summary

The brain-sync architecture follows a simple model:

**user knowledge** → **regeneration** → **generated meaning**

The filesystem stores both the input and the output. Runtime systems
coordinate this process but are not authoritative. The system adapts to
whatever the user does to the filesystem, with the single compromise
that synced source content is overwritten by remote truth on next sync.

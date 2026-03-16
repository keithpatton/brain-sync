# Brain Format v1 — Glossary

This glossary defines the canonical terms used when describing the
brain-sync Brain Format 1.0 filesystem contract. Terms are alphabetised.

---

## Attachment

An **attachment** is a binary file associated with a [synced source](#synced-source)
and managed by brain-sync.

Attachments are stored under the [knowledge area's](#knowledge-area)
[managed files](#brain-managed-files) at
`.brain-sync/attachments/<source_dir_id>/`.

Example: `knowledge/teams/platform/.brain-sync/attachments/c987654/a4736286723-architecture-diagram.png`

## Brain

A **brain** is the portable filesystem knowledge base used by brain-sync.

A brain is created by `brain-sync init` which registers the
[brain root](#brain-root) and creates the initial directory structure.

By default a freshly initialised brain will be empty save for a
`[_core](#core-knowledge)` folder which allows the user to provide initial
knowledge that can be distilled into [global context](#global-context) for
regeneration and can be loaded explicitly by context-oriented tools.

---

## Brain Root

The **brain root** is the top-level directory of a [brain](#brain). It can
be named anything (e.g. `acme-brain/`, `my-brain/`).

The brain root is registered during `brain-sync init` in
[brain-sync runtime directory](#brain-sync-runtime-directory). This registration
can be changed.

The brain root contains exactly two top-level entries:

- `knowledge/` — the [knowledge tree](#knowledge-tree)
- `.brain-sync/` — the root [managed files](#brain-managed-files)

---

## Brain State

**Brain state** is the persistent state of a [brain](#brain) stored on
disk — the set of files that should be backed up and are portable across
machines.

Brain state is the persistent state of the [brain root](#brain-root), not just
the [knowledge tree](#knowledge-tree).

It consists of:

- [user knowledge](#user-knowledge)
- [brain managed files](#brain-managed-files) inside the
  [brain root](#brain-root)

It excludes [runtime state](#runtime-state).

A brain-state entry changes only when its durable on-disk identity or
bytes change. Rewriting an unchanged managed file does not create a new class
of brain state.

---

## Brain-Sync Runtime Directory

The **brain-sync runtime directory** is the machine-local directory at
`~/.brain-sync/` (overridable via `BRAIN_SYNC_CONFIG_DIR` environment
variable) that holds all per-machine application state.

Earlier docs may refer to this as the **brain-sync user directory**. The
preferred term is **brain-sync runtime directory** because this directory holds
runtime state, not brain state.

It contains:

- `config.json` — brain root registration, source authentication
credentials, feature flags
- `db/brain-sync.sqlite` — the [brain-sync database](#brain-sync-database)
- `logs/` — rotating log files
- `daemon.json` — daemon PID and status

This directory is **not** inside the brain root. Nothing in it is part
of [brain state](#brain-state). Everything in it is
[runtime state](#runtime-state) — rebuildable or recreatable without
loss of [user knowledge](#user-knowledge) or
[generated meaning](#generated-meaning).

## Brain-Sync Database

The **brain-sync database** is a machine-local SQLite database used for
runtime coordination and caching. It is not authoritative — the brain
can be fully reconstructed if it is deleted.

Path: `~/.brain-sync/db/brain-sync.sqlite` (inside the
[brain-sync runtime directory](#brain-sync-runtime-directory))

The database is **not** inside the brain root. It is
[runtime state](#runtime-state).

Current tables:


| Table          | Purpose                                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------------- |
| `meta`         | Schema version for migration                                                                            |
| `sync_cache`   | Machine-local polling schedule state                                                                    |
| `regen_locks`  | Cross-process regen coordination                                                                        |
| `token_events` | Append-only LLM cost telemetry persisted for local observability; not part of core brain-state recovery |


## Brain Managed Files

**Brain managed files** are files inside `.brain-sync/` folders
within the [brain root](#brain-root).

Earlier docs may refer to these as **brain-sync managed files**. The preferred
term is **brain managed files** because the key boundary is that these files
are managed within the Brain and are part of brain state.

This includes:

- root `.brain-sync/` — source [manifests](#manifest), `brain.json`
- per-area `knowledge/**/.brain-sync/` — insights, [journals](#journal),
[attachments](#attachment), [insight state](#insight-state)

Managed files are part of the durable [brain state](#brain-state) and
are portable across machines. Users should not edit them directly —
brain-sync owns these files and may create, update, or delete them at
any time.

The `.brain-sync` directory name is reserved at every level of the
[knowledge tree](#knowledge-tree).

Note: brain-sync also manages files in the
[brain-sync runtime directory](#brain-sync-runtime-directory)
(`~/.brain-sync/`), but those are [runtime state](#runtime-state), not
brain state. In this glossary, **brain managed files** means the
managed files inside the [brain root](#brain-root), not runtime-managed files
under `~/.brain-sync/`.

---

## Canonical ID

A **canonical ID** is a durable, provider-specific identity string used
throughout brain-sync to identify [synced sources](#synced-source),
attachments, and inline images.

Format: `<type>:<provider_id>`


| Type                    | Canonical ID                       | Filename prefix      |
| ----------------------- | ---------------------------------- | -------------------- |
| Confluence page         | `confluence:987654`                | `c987654-`           |
| Google Doc              | `gdoc:1zo3CY...`                   | `g1zo3CY...-`        |
| Confluence attachment   | `confluence-attachment:4736286723` | `a4736286723-`       |
| Google Doc inline image | `gdoc-image:1zo3CY:objectId`       | `gi1zo3CY-objectId-` |


The canonical ID appears in:

- source [manifests](#manifest) (`canonical_id` field)
- synced source [frontmatter](#frontmatter) (`brain_sync_canonical_id` field)
- filename prefixes (discovery and repair hint, not authoritative)
- attachment directory names (the `source_dir_id`, the deterministic
filesystem-safe derivative used for manifest filenames and per-source
attachment directories, e.g. `c987654`)

Brain Format 1.0 standardises the canonical ID as the single identity primitive across
all source types and contexts. The filename prefix is always derived
deterministically from the canonical ID.

---

## Change Detection

**Change detection** is the mechanism brain-sync uses to decide whether a
[knowledge area](#knowledge-area) needs [regeneration](#regeneration).

Two hashes are computed for each area:

- **content hash** — SHA-256 of the area's readable files and child area
summaries. A changed content hash means the semantic input has changed
and regeneration is needed.
- **structure hash** — SHA-256 of the area's child directory names only.
A changed structure hash with an unchanged content hash indicates a
structural move (e.g. folder rename) that does not require a full
regeneration.

These hashes are stored in the [insight state](#insight-state) manifest
and compared on each regen cycle to classify changes as: no change,
rename-only, or content change.

---

## Core Knowledge

**Core knowledge** is the raw foundational material stored in
`knowledge/_core/`.

It is the place for foundational information that applies across the entire
brain — mission, organisational structure, key people, conventions. Core
knowledge is created by `brain-sync init` and treated as a
[knowledge area](#knowledge-area) (it gets its own insights and journal).

Core knowledge is the canonical source for `_core`'s
[generated meaning](#generated-meaning). During regeneration, raw `_core`
files are inlined only when brain-sync is regenerating `_core` itself.
For every other area, brain-sync uses [global context](#global-context)
derived from `_core` instead of injecting raw `_core` files.

Deterministic query/search does not implicitly inject raw `_core` files.
Instead, `_core` participates there like any other area through its generated
meaning and other indexed artifacts unless a tool explicitly asks to load
global context.

If `_core/` is deleted, brain-sync continues by assuming there is no global
context.

---

## Daemon

The **daemon** is the long-running background process started by
`brain-sync run`. It is the runtime heart of brain-sync, tying together
[sync](#sync), [watching](#watcher), and [regeneration](#regeneration) into
a continuous loop.

The daemon loop:

1. [Reconciles](#reconciliation) offline filesystem changes on startup
2. Polls registered [synced sources](#synced-source) on adaptive schedules
3. Receives filesystem change events from the [watcher](#watcher)
4. Queues and processes [regeneration](#regeneration) with debounce,
  cooldown, and rate limiting

The daemon is optional — all operations can also be triggered manually via
CLI commands or MCP tools.

---

## Doctor

The **doctor** is brain-sync's consistency checker and repair tool, invoked
via `brain-sync doctor`.

Doctor validates the [brain](#brain) against its invariants and reports
findings at graduated severity levels:

- **OK** — healthy
- **DRIFT** — minor inconsistency (e.g. stale layout, missing managed file)
- **CORRUPTION** — unrecoverable inconsistency requiring manual intervention

`doctor --fix` can safely repair DRIFT-level findings: creating missing
directories, rebuilding the [database](#brain-sync-database) from
[manifests](#manifest), and migrating stale artifact layouts.

User-authored files found inside `.brain-sync/` are also DRIFT: the
brain may still function, but the content is at risk because the managed
namespace can be rewritten or cleaned by brain-sync operations. Doctor
reports this but does not move or delete that user content.

Doctor will not silently invent semantic content.

---

## Frontmatter

**Frontmatter** is a YAML block embedded at the top of a markdown document,
delimited by `---` markers.

In brain-sync, frontmatter is used to embed [synced source](#synced-source)
identity inside materialized markdown files. It is defined by the synced
source frontmatter [schema](#schema) and is the **authoritative identity**
of a synced document.

Example:

```yaml
---
brain_sync_source: confluence
brain_sync_canonical_id: confluence:987654
brain_sync_source_url: https://acme.atlassian.net/wiki/spaces/PT/pages/987654
---
```

See also: [manifest](#manifest) (the other way a schema can be instantiated).

During transition and repair, readers may still accept legacy HTML
comment identity markers as a fallback. New writes use YAML
frontmatter only.

---

## Generated Meaning

**Generated meaning** is any AI-summarised or AI-authored content that is
built from [user knowledge](#user-knowledge).

Generated meaning currently includes:

- **insights** — regenerable semantic summaries (`summary.md`) that
represent the current understanding of a [knowledge area](#knowledge-area)
- **[journal](#journal) entries** — append-only temporal records of
decisions, milestones, and status changes

Generated meaning will extend to additional [template](#template) types in
the future (e.g. status reports, decision logs, theme analyses).

All generated meaning lives under
`[.brain-sync/](#brain-managed-files)` within a knowledge area.
Insights live under `.brain-sync/insights/`, journals under
`.brain-sync/journal/`.

---

## Global Context

**Global context** is the cross-cutting context assembled from `_core` for
use by regeneration and explicit context-loading tools.

For non-`_core` regeneration, global context is `_core`'s distilled meaning:
`knowledge/_core/.brain-sync/insights/summary.md` when that file exists.

When regenerating `_core` itself, brain-sync does not inject that summary
back into the prompt. Instead it inlines raw files from
`knowledge/_core/` so `_core` can be regenerated from its canonical source
material.

This distinction keeps prompt shape and token use more deterministic:

- **[core knowledge](#core-knowledge)** is the raw source
- **[global context](#global-context)** is the prompt-ready context assembled
  from `_core`
- **[generated meaning](#generated-meaning)** is the distilled output brain-sync
  writes and maintains

If `_core` has no managed summary yet, non-`_core` regeneration proceeds
without global context.

---

## Insight State

**Insight state** is the [manifest](#manifest) that tracks the
[regeneration](#regeneration) state for a
[knowledge area's](#knowledge-area) insights. It records content hashes,
summary hashes, and timestamps to determine when regeneration is needed.

Path: `knowledge/<area>/.brain-sync/insights/insight-state.json`

See [SCHEMAS.md](SCHEMAS.md) for field definitions.

---

## Journal

A **journal** is a durable append-only temporal record for a
[knowledge area](#knowledge-area), and a form of
[generated meaning](#generated-meaning).

Journal files are organized by day (`YYYY-MM/YYYY-MM-DD.md`) and contain
timestamped entries. Journals are **not regenerable** — they survive all
automated cleanup operations.

---

## Knowledge Area

A **knowledge area** is a directory under `knowledge/` that participates in
[regeneration](#regeneration).

A directory is a knowledge area if it:

- contains [readable files](#readable-file), or
- has descendant [knowledge areas](#knowledge-area)

Areas are the unit of [generated meaning](#generated-meaning). Each area
can have its own insights, journal entries, and
[brain managed files](#brain-managed-files) under `.brain-sync/`.

Examples:

- `knowledge/` (the **root area**)
- `knowledge/_core/` ([core knowledge](#core-knowledge))
- `knowledge/teams/platform/`

The root area participates in regeneration and reconciliation as the top
of the area topology. It is valid even when it derives meaning only from
child area summaries.

Example:

```text
knowledge/
  teams/
    platform/
      architecture.md
```

Derived knowledge areas:

- `knowledge/`
- `knowledge/teams/`
- `knowledge/teams/platform/`

A directory under `knowledge/` that contains neither readable files nor
descendant knowledge areas is not a knowledge area and does not participate in
regeneration.

---

## Knowledge Tree

The **knowledge tree** is the `knowledge/` directory and everything inside
it.

It holds:

- [user knowledge](#user-knowledge) — user-authored notes,
[synced source](#synced-source) documents, and [attachments](#attachment)
- [brain managed files](#brain-managed-files) — the per-area
`.brain-sync/` directories

The knowledge tree is the durable core of the [brain](#brain).

---

## Manifest

A **manifest** is a standalone JSON file that instantiates a
[schema](#schema).

Manifests are durable, machine-readable, and used to reconstruct or validate
brain-sync-managed state.

Examples:

- `.brain-sync/sources/c987654.json` (synced source manifest)
- `knowledge/teams/platform/.brain-sync/insights/insight-state.json`
([insight state](#insight-state) manifest)

See also: [frontmatter](#frontmatter) (the other way a schema can be
instantiated, embedded inside a markdown document).

---

## Materialization

**Materialization** is the process of writing a [synced source's](#synced-source)
remote content to a local markdown file in the
[knowledge tree](#knowledge-tree).

During materialization, brain-sync:

1. Fetches the source content from the remote provider
2. Converts it to markdown
3. Embeds [frontmatter](#frontmatter) identity at the top of the file
4. Writes the file to the path specified by `materialized_path` in the
  source [manifest](#manifest)

The resulting file is called a **materialized document**. Its
`materialized_path` (relative to `knowledge/`) is recorded in the source
manifest and used as the primary path for
[reconciliation](#reconciliation).

---

## Regeneration

**Regeneration** (regen) is the process that recomputes brain-sync-owned
[generated meaning](#generated-meaning) from
[user knowledge](#user-knowledge) and child area summaries.

Regen uses a **wave topology**: all [knowledge areas](#knowledge-area) at
the deepest level are processed first, then their parents, and so on toward
the root. Dirty propagation ensures parents are only processed when at least
one child actually changed. Each area is processed at most once per regen
cycle.

Typical outputs:

- updated `summary.md`
- updated [insight state](#insight-state) manifest
- optional [journal](#journal) entry

---

## Reconciliation

**Reconciliation** is the startup process that detects offline filesystem
changes (moves, deletes, additions) and brings the system into agreement
with disk truth.

Reconciliation is what makes the "filesystem is authoritative" principle
work in practice. When the [daemon](#daemon) starts, it:

1. Walks all source [manifests](#manifest) and uses **three-tier file
  resolution** to locate each source's file:
  - tier 1: `materialized_path` (direct path check)
  - tier 2: [frontmatter](#frontmatter) identity scan
  - tier 3: [canonical ID](#canonical-id) prefix glob
2. Updates manifests to reflect any detected moves
3. Applies a **two-stage missing protocol**: a source marked `missing` on
  the first reconcile pass is deleted only if still missing on the next
   pass (grace period for temporary filesystem states)
4. Prunes orphan database rows that no longer correspond to disk state

Reconciliation can also be triggered manually via `brain-sync reconcile`.

---

## Readable File

A **readable file** is a user-knowledge file under `knowledge/` that
participates in semantic input: content discovery, content hashing,
regeneration, and doctor validation.

Readable files include human-authored markdown and synced markdown
documents. Readable files do **not** include:

- anything under `.brain-sync/`
- attachment binaries under `.brain-sync/attachments/`
- journals, summaries, and insight state
- directories or other managed artifacts

The exact parser or extension support is an implementation detail. The
invariant is that the same inclusion rule must be used consistently
across discovery, hashing, regeneration, and reconciliation.

---

## Runtime State

**Runtime state** is machine-local state that supports brain-sync while
running but is **not** part of the portable [brain state](#brain-state).

All runtime state lives in the
[brain-sync runtime directory](#brain-sync-runtime-directory)
(`~/.brain-sync/`):

- `config.json` — brain root registration and credentials
- `db/brain-sync.sqlite` — the [brain-sync database](#brain-sync-database)
- `logs/` — rotating log files
- `daemon.json` — daemon PID and status

Runtime state can be rebuilt or recreated without loss of
[user knowledge](#user-knowledge) or
[generated meaning](#generated-meaning). Nothing inside the
[brain root](#brain-root) is runtime state.

---

## Schema

A **schema** defines the structure and meaning of a class of document.

Schemas define fields, required structure, and interpretation rules.
A schema is instantiated as either a [manifest](#manifest) (standalone JSON)
or as [frontmatter](#frontmatter) (YAML embedded in markdown).

Schemas defined in Brain Format 1.0:

- synced source schema → synced source manifest
- brain schema → brain manifest
- insight state schema → [insight state](#insight-state) manifest
- synced source frontmatter schema → synced source frontmatter

See [SCHEMAS.md](SCHEMAS.md) for full definitions.

---

## Synced Source

A **synced source** is an external document or page tracked by brain-sync
and materialized into the [knowledge tree](#knowledge-tree).

Examples: a Confluence page, a Google Doc.

Each synced source has:

- a [manifest](#manifest) at `.brain-sync/sources/<id>.json`
- a materialized markdown file in `knowledge/` with
[frontmatter](#frontmatter) identity
- optionally, [attachments](#attachment) under the area's `.brain-sync/`

---

## Stability Guard

The **stability guard** prevents unnecessary churn in
[generated meaning](#generated-meaning) by discarding rewrites that are
too similar to the existing content.

When [regeneration](#regeneration) produces a new summary, brain-sync
computes a text similarity score against the existing summary. If the
similarity exceeds a threshold (default >0.97), the rewrite is discarded
and the existing summary is kept. This ensures that minor upstream wording
changes do not cascade through the entire [knowledge tree](#knowledge-tree).

The stability guard applies only to regenerable insights (e.g. `summary.md`),
not to [journals](#journal) which are append-only.

---

## Sync

**Sync** (synchronisation) is the process of fetching remote content from
registered [synced sources](#synced-source) and
[materializing](#materialization) it into the
[knowledge tree](#knowledge-tree).

During a sync cycle, brain-sync:

1. Checks each registered source against its remote provider
2. Compares content hashes to detect upstream changes
3. [Materializes](#materialization) changed content to the local file
4. Updates the source [manifest's](#manifest) `sync_hint`
5. Queues affected [knowledge areas](#knowledge-area) for
  [regeneration](#regeneration)

Sync runs on adaptive schedules — sources that change frequently are
checked more often; stable sources back off to longer intervals (up to
24 hours). The [daemon](#daemon) manages these schedules automatically.

---

## Template

A **template** defines the layout of generated content — a form of
[generated meaning](#generated-meaning).

Templates describe the shape of [generated meaning](#generated-meaning)
rather than state fields.

Templates defined in Brain Format 1.0:

- summary — area summary (`summary.md`)
- journal — daily temporal record

See [TEMPLATES.md](TEMPLATES.md) for full definitions.

---

## User Knowledge

**User knowledge** is the content within the [knowledge tree](#knowledge-tree)
that represents the user's curated information.

It includes:

- user-authored notes and documents (markdown, text)
- [synced source](#synced-source) materialized documents
- [attachments](#attachment) associated with synced sources

User knowledge is the input to [regeneration](#regeneration). It is distinct
from [generated meaning](#generated-meaning), which is brain-sync's output.

---

## Watcher

The **watcher** monitors the [knowledge tree](#knowledge-tree) for
filesystem changes (file creates, edits, deletes, moves) and queues
affected [knowledge areas](#knowledge-area) for
[regeneration](#regeneration).

The watcher is started by the [daemon](#daemon) after
[reconciliation](#reconciliation) completes (to avoid processing spurious
events from startup state repair). It uses debouncing (default 30 seconds)
to batch rapid changes before triggering regeneration.

When a knowledge folder is moved, the watcher updates source
[manifests](#manifest) and database state to maintain consistency.
Because [managed files](#brain-managed-files) are co-located under
each area's `.brain-sync/`, they move automatically with the folder.

---

## Example Document Relationships

### Schema → Manifest

A [schema](#schema) defines the structure of a [manifest](#manifest).

Example: the synced source schema defines the structure of
`.brain-sync/sources/c987654.json` — a concrete synced source manifest.

### Schema → Frontmatter

A [schema](#schema) may be instantiated as [frontmatter](#frontmatter)
embedded inside a markdown document.

Example: the synced source frontmatter schema is instantiated as the YAML
header inside `c987654-attachment-handling.md`, binding that file to its
upstream Confluence page.

### Template → Generated Meaning

A [template](#template) defines the layout of
[generated meaning](#generated-meaning).

Example: the summary template defines the shape of a generated area
insight — an instance like
`knowledge/teams/platform/.brain-sync/insights/summary.md`.

---

## Summary of the Model

- **[user knowledge](#user-knowledge)** is the input
- **[regeneration](#regeneration)** is the process
- **[generated meaning](#generated-meaning)** is the output
- **[schemas](#schema)** define document structure
- **[manifests](#manifest)** are standalone JSON files instantiating schemas
- **[frontmatter](#frontmatter)** is schema-defined YAML embedded in
markdown
- **[templates](#template)** define generated content layouts

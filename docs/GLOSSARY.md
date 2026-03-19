# Glossary

This glossary defines the canonical terms used when describing the
brain-sync brain, runtime, and compatibility model.

It is primarily an agent-first reference: an agent should be able to predict
what is authoritative, what is portable, and what changes when the filesystem
or a synced source changes. Terms are alphabetised. The opening map provides
the shortest route to the core model; later entries provide the precise
definitions.

---

## Agent-First Model

brain-sync behavior is easiest to predict by separating portable
[brain state](#brain-state) from machine-local [runtime state](#runtime-state),
then splitting portable managed state into its semantic classes.

| State Class | Portable | Primary Question | Typical Artifacts |
|---|---|---|---|
| [User knowledge](#user-knowledge) | yes | What knowledge is the user preserving directly? | user-authored notes, materialized synced documents |
| [Brain normative state](#brain-normative-state) | yes | What does the brain currently claim is true? | `canonical_id`, `knowledge_path`, `knowledge_state` |
| [Brain reconciliation baseline](#brain-reconciliation-baseline) | yes | What settled observations must a future machine inherit? | `content_hash`, `remote_fingerprint`, insight hashes |
| [Generated meaning](#generated-meaning) | yes | What understanding has brain-sync produced? | `summary.md`, journal entries |
| [Managed knowledge dependencies](#managed-knowledge-dependencies) | yes | What supporting managed artifacts must travel with the brain? | synced attachment binaries |
| [Runtime state](#runtime-state) | no | What does this machine need in order to operate? | DB rows, daemon status, logs, schedules |

When predicting behavior, inspect in this order:

1. [Filesystem authority](#filesystem-authority): what exists on disk now?
2. [Brain normative state](#brain-normative-state): what does the brain assert
   exists, where, and in what lifecycle state?
3. [Brain reconciliation baseline](#brain-reconciliation-baseline): what
   settled observations are recorded for future decisions?
4. [Change detection](#change-detection) and [reconciliation](#reconciliation):
   what durable updates follow from current disk truth?
5. [Regeneration](#regeneration) and the [stability guard](#stability-guard):
   does meaning need to be recomputed, and does the rewrite materially matter?
6. [Runtime state](#runtime-state): what coordination or telemetry supports
   execution without changing portable meaning?

---

## Attachment

An **attachment** is a binary file associated with a [synced source](#synced-source)
and managed by brain-sync.

Attachments are stored under the [knowledge area's](#knowledge-area)
[brain managed files](#brain-managed-files) as
[managed knowledge dependencies](#managed-knowledge-dependencies) at
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

Within [brain managed files](#brain-managed-files), brain-sync distinguishes:

- [brain normative state](#brain-normative-state)
- [brain reconciliation baseline](#brain-reconciliation-baseline)
- [generated meaning](#generated-meaning)
- [managed knowledge dependencies](#managed-knowledge-dependencies)

Brain state does not include runtime-local operational state or
runtime-local observation history. Those remain part of
[runtime state](#runtime-state), not portable brain state.

---

## Brain-Sync Database

The **brain-sync database** is a machine-local SQLite database used for
runtime coordination and caching. It is not authoritative — the brain
can be fully reconstructed if it is deleted.

Path: `~/.brain-sync/db/brain-sync.sqlite` (inside the
[brain-sync runtime directory](#brain-sync-runtime-directory))

The database is **not** inside the brain root. It is
[runtime state](#runtime-state).

Its concrete runtime schema, including current tables, is defined in
[runtime/SCHEMAS.md](runtime/SCHEMAS.md).


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

---

## Brain Manifest

The **brain manifest** is the root portable [manifest](#manifest) at
`.brain-sync/brain.json`.

It records portable brain-format metadata for the whole
[brain root](#brain-root).

The current schema is intentionally minimal; see the
[Brain Manifest Schema](brain/SCHEMAS.md#brain-manifest-schema).

---

## Brain Managed Files

**Brain managed files** are files inside `.brain-sync/` folders
within the [brain root](#brain-root).

Earlier docs may refer to these as **brain-sync managed files**. The preferred
term is **brain managed files** because the key boundary is that these files
are managed within the Brain and are part of [brain state](#brain-state).

This includes:

- root `.brain-sync/` — source [manifests](#manifest), `brain.json`
- per-area `knowledge/**/.brain-sync/` — insights, [journals](#journal),
[attachments](#attachment), [insight state](#insight-state)

Brain managed files are portable. Users should not edit them directly:
brain-sync owns these files and may create, update, or delete them at
any time.

Brain managed files carry four kinds of managed content:

- [brain normative state](#brain-normative-state) — state that defines
current asserted brain truth
- [brain reconciliation baseline](#brain-reconciliation-baseline) — last
known settled facts needed for future machines to make correct decisions
- [generated meaning](#generated-meaning) — brain-sync-authored output such
as insights and journals
- [managed knowledge dependencies](#managed-knowledge-dependencies) —
managed artifacts that preserve the usable form of knowledge but are not
themselves state assertions

Examples from fields defined by the
[Source Manifest Schema](brain/SCHEMAS.md#source-manifest-schema) and
instantiated in synced source [manifests](#manifest):

- [brain normative state](#brain-normative-state): `canonical_id`,
`source_url`, `source_type`, `sync_attachments`, `knowledge_path`,
`knowledge_state`
- [brain reconciliation baseline](#brain-reconciliation-baseline):
`content_hash`, `remote_fingerprint`, `materialized_utc`,
`insight-state.json` fields such as `content_hash`, `structure_hash`,
`summary_hash`, `last_regen_utc`
- [generated meaning](#generated-meaning): `summary.md`, journal entries
- [managed knowledge dependencies](#managed-knowledge-dependencies):
attachment binaries under `.brain-sync/attachments/<source_dir_id>/`

Managed stores may also carry schema metadata such as manifest `version` and
`brain.json.version`. That metadata governs how the managed store is
interpreted; it is not itself one of the four managed-content kinds.

The `.brain-sync` directory name is reserved at every level of the
[knowledge tree](#knowledge-tree).

Note: brain-sync also manages files in the
[brain-sync runtime directory](#brain-sync-runtime-directory)
(`~/.brain-sync/`), but those are [runtime state](#runtime-state), not
brain state. In this glossary, **brain managed files** means the
managed files inside the [brain root](#brain-root), not runtime-managed files
under `~/.brain-sync/`.

---

## Brain Normative State

**Brain normative state** is the part of [brain managed files](#brain-managed-files)
that defines the current asserted truth of the brain.

This state is:

- authoritative
- portable across machines
- required for another machine to understand what the brain currently claims
is true

Examples from fields defined by the
[Source Manifest Schema](brain/SCHEMAS.md#source-manifest-schema) and
instantiated in synced source [manifests](#manifest):

- `canonical_id`
- `source_url`
- `source_type`
- `sync_attachments`
- `knowledge_path`
- `knowledge_state`

Brain normative state is distinct from
[brain reconciliation baseline](#brain-reconciliation-baseline), which stores
the last settled baseline facts needed for future decisions.

---

## Brain Reconciliation Baseline

**Brain reconciliation baseline** is the part of
[brain managed files](#brain-managed-files) that records the last known settled
facts required for future machines to interpret and evolve the same brain
correctly.

These facts are observational in origin, but they have been stabilized into
portable truth because another machine must inherit them.

Examples from fields defined by the
[Source Manifest Schema](brain/SCHEMAS.md#source-manifest-schema) and
instantiated in synced source [manifests](#manifest):

- `content_hash`
- `remote_fingerprint`
- `materialized_utc`

Examples from fields defined by the
[Insight State Schema](brain/SCHEMAS.md#insight-state-schema) and
instantiated in [insight state](#insight-state) manifests:

- `content_hash`
- `structure_hash`
- `summary_hash`
- `last_regen_utc`

Brain reconciliation baseline is distinct from:

- [brain normative state](#brain-normative-state), which defines current
asserted brain truth
- runtime-local observation history, which reflects how one runtime
  encountered the world over time

This pattern is not limited to fields defined by the
[Source Manifest Schema](brain/SCHEMAS.md#source-manifest-schema). It also
appears in other portable managed artifacts, such as per-area
[insight state](#insight-state), wherever the system preserves the last
settled facts needed for future decisions.

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

Brain Format `1.x` uses the canonical ID as the single identity primitive
across all source types and contexts. The filename prefix is always derived
deterministically from the canonical ID.

---

## Change Detection

**Change detection** is the mechanism brain-sync uses to decide whether a
[knowledge area](#knowledge-area) needs [regeneration](#regeneration).

Two hashes are computed for each area:

- **content hash** — SHA-256 of the area's readable files and child area
summaries. A changed content hash means the semantic input has changed
and regeneration is needed.
- **structure hash** — SHA-256 of the area's structural layout
  (directory and filename shape). A changed structure hash with an unchanged
  content hash indicates a structural move or rename that does not require a
  full regeneration.

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

## Filesystem Authority

**Filesystem authority** is the governing principle that disk truth wins over
stale runtime understanding.

This means:

- [runtime state](#runtime-state) must adapt to the filesystem
- [reconciliation](#reconciliation) repairs portable managed state to match
  current disk truth
- the system must tolerate online and offline user changes to the
  [knowledge tree](#knowledge-tree)

When runtime belief and disk reality differ, the filesystem wins.

---

## Generated Meaning

**Generated meaning** is brain-sync-authored content produced from
[user knowledge](#user-knowledge).

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

Insight state is part of
[brain reconciliation baseline](#brain-reconciliation-baseline), not
[generated meaning](#generated-meaning). It records the settled baseline used
to decide whether generated insights must be recomputed.

See [brain/SCHEMAS.md](brain/SCHEMAS.md) for field definitions.

---

## Insight-State Manifest

An **insight-state manifest** is the portable per-area [manifest](#manifest)
at `knowledge/<area>/.brain-sync/insights/insight-state.json`.

It stores [brain reconciliation baseline](#brain-reconciliation-baseline) for
generated insights, not the insight text itself.

See also: [insight state](#insight-state).

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
[synced source](#synced-source) documents
- [brain managed files](#brain-managed-files) — the per-area
`.brain-sync/` directories

The knowledge tree is the durable core of the [brain](#brain).

---

## Managed Knowledge Dependencies

**Managed knowledge dependencies** are the part of
[brain managed files](#brain-managed-files) that preserve the usable form of
knowledge content without themselves being portable state assertions.

These are non-primary managed artifacts referenced by knowledge documents and
co-moved with them.

These dependencies are:

- portable
- managed by brain-sync
- required to preserve the usable form of some knowledge content
- not themselves [brain normative state](#brain-normative-state) or
[brain reconciliation baseline](#brain-reconciliation-baseline)

Currently this class consists only of synced attachment binaries.

Example:

- attachment binaries under `.brain-sync/attachments/<source_dir_id>/`

Managed knowledge dependencies are distinct from
[user knowledge](#user-knowledge): the dependency bytes are managed system
artifacts, while user-authored references to them remain part of user
knowledge.

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
4. Writes the file to the path anchored by `knowledge_path` in the
  source [manifest](#manifest)

The resulting file is called a **materialized document**. Its
`knowledge_path` (relative to `knowledge/`) is recorded in the source
manifest and used as the primary path anchor for
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
  - tier 1: `knowledge_path` (direct path check)
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

**Runtime state** is machine-local state used by brain-sync to observe,
coordinate, schedule, cache, and execute work against a brain.

Runtime state is not part of the portable [brain state](#brain-state).

Runtime state may contain both:

- operational execution state
- local observation history about how one runtime encountered the world
  relative to the brain

Observation-history-like runtime state:

- reflects timing, sequencing, or accumulation of observations
- depends on runtime execution history
- is not required for another machine to correctly interpret and evolve the
  current brain state

Operational runtime state:

- supports scheduling, polling, retries, coordination, telemetry, and other
  execution-supporting behaviour
- is safe to discard and rebuild
- changes how the system operates, not what the brain means

A single runtime artifact may contain both kinds of runtime-local state.

All runtime state lives in the
[brain-sync runtime directory](#brain-sync-runtime-directory)
(`~/.brain-sync/`):

- `config.json` — brain root registration and credentials
- `db/brain-sync.sqlite` — the [brain-sync database](#brain-sync-database)
- `logs/` — rotating log files
- `daemon.json` — daemon PID and status

Runtime-managed stores may also contain schema metadata such as runtime DB
schema version markers. That metadata governs interpretation of runtime state;
it is not itself operational state or observation history.

Runtime state can be rebuilt or recreated without loss of
[user knowledge](#user-knowledge) or
[generated meaning](#generated-meaning). Nothing inside the
[brain root](#brain-root) is runtime state, except for the known unreleased
portable anomaly `missing_since_utc`, which remains in the
[Source Manifest Schema](brain/SCHEMAS.md#source-manifest-schema) pending
planned removal.

---

## Schema

A **schema** defines the structure and meaning of a class of persisted
artifact.

Schemas define fields, required structure, and interpretation rules.
Schemas may govern portable file artifacts or runtime persisted structures.

Examples of schema-governed persisted artifacts include
[manifests](#manifest), [frontmatter](#frontmatter), and runtime database
tables.

Portable brain schemas:

- [Source Manifest Schema](brain/SCHEMAS.md#source-manifest-schema) → synced
  source manifest
- [Brain Manifest Schema](brain/SCHEMAS.md#brain-manifest-schema) → brain
  manifest
- [Insight State Schema](brain/SCHEMAS.md#insight-state-schema) →
[insight state](#insight-state) manifest
- [Synced Source Frontmatter Schema](brain/SCHEMAS.md#synced-source-frontmatter-schema)
  → synced source frontmatter

Runtime schemas and schema-shaped runtime artifacts are documented in
[runtime/SCHEMAS.md](runtime/SCHEMAS.md), including database tables and
other machine-local persisted structures.

See [brain/SCHEMAS.md](brain/SCHEMAS.md) for full definitions and
[runtime/SCHEMAS.md](runtime/SCHEMAS.md) for machine-local runtime schemas.

---

## Source Directory ID

A **source directory ID** is the deterministic filesystem-safe derivative of a
[canonical ID](#canonical-id).

It is used for:

- synced source manifest filenames
- per-source attachment directories
- canonical filename prefixes

Example:

- canonical ID: `confluence:987654`
- source directory ID: `c987654`

The source directory ID is a filesystem derivative of identity, not a separate
identity primitive.

---

## Source Manifest

A **source manifest** is the portable [manifest](#manifest) for a
[synced source](#synced-source).

Path pattern: `.brain-sync/sources/<source_dir_id>.json`

A source manifest stores:

- [brain normative state](#brain-normative-state) for the source
- [brain reconciliation baseline](#brain-reconciliation-baseline) for the
  source
- schema metadata such as `version`

See the [Source Manifest Schema](brain/SCHEMAS.md#source-manifest-schema) for
the concrete field contract.

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

## Synced Source

A **synced source** is an external document or page tracked by brain-sync
and materialized into the [knowledge tree](#knowledge-tree).

Examples: a Confluence page, a Google Doc.

Each synced source has:

- a [canonical ID](#canonical-id)
- a [source manifest](#source-manifest)
- a materialized markdown file in `knowledge/` with
[frontmatter](#frontmatter) identity
- optionally, [attachments](#attachment) under the area's `.brain-sync/`

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
4. Updates the source [manifest's](#manifest) lifecycle and
  last-successful fields
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

Brain templates:

- summary — area summary (`summary.md`)
- journal — daily temporal record

See [brain/TEMPLATES.md](brain/TEMPLATES.md) for full definitions.

---

## User Knowledge

**User knowledge** is the content within the [knowledge tree](#knowledge-tree)
that represents the user's curated information.

It includes:

- user-authored notes and documents (markdown, text)
- [synced source](#synced-source) materialized documents

User knowledge is the input to [regeneration](#regeneration). It is distinct
from [generated meaning](#generated-meaning), which is brain-sync's output.

User knowledge may depend on [managed knowledge dependencies](#managed-knowledge-dependencies)
such as synced attachments, but those dependency files are [brain managed files](#brain-managed-files),
not user knowledge.

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

Example: the
[Source Manifest Schema](brain/SCHEMAS.md#source-manifest-schema)
defines the structure of `.brain-sync/sources/c987654.json` — a concrete
synced source manifest.

### Schema → Frontmatter

A [schema](#schema) may be instantiated as [frontmatter](#frontmatter)
embedded inside a markdown document.

Example: the
[Synced Source Frontmatter Schema](brain/SCHEMAS.md#synced-source-frontmatter-schema)
is instantiated as the YAML header inside
`c987654-attachment-handling.md`, binding that file to its upstream
Confluence page.

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

# Brain Format v1 — Schemas

This document describes the schema-defined filesystem documents used by
brain-sync. Each schema may be instantiated as a
[manifest](GLOSSARY.md#manifest) (standalone JSON file) or as
[frontmatter](GLOSSARY.md#frontmatter) (YAML embedded in a markdown
document). See [GLOSSARY.md](GLOSSARY.md) for all term definitions.

> **Status**: Aspirational v23 target. Current-vs-proposed differences are
> noted inline.

---

## Synced Source Schema

The synced source schema defines the durable registration record for a
synced source.

It tells brain-sync:

- what remote source is being tracked
- what kind of source it is
- where its local materialized file currently lives
- how it should be synced

**Path pattern**

```text
.brain-sync/sources/<source_dir_id>.json
```

Examples:

- `.brain-sync/sources/c987654.json`
- `.brain-sync/sources/g1zo3CY98lXDGsagjHUHRciomGysWHdzgt5BAXfljhzvU.json`

`source_dir_id` is the deterministic filesystem-safe derivative of the
source's canonical ID. It is normative in v23 and is used consistently
for:

- source manifest filenames
- per-source attachment directory names
- repair and rediscovery of source-owned managed artifacts

Examples:

- `confluence:987654` -> `c987654`
- `gdoc:1zo3CY98lXDGsagjHUHRciomGysWHdzgt5BAXfljhzvU` ->
  `g1zo3CY98lXDGsagjHUHRciomGysWHdzgt5BAXfljhzvU`

**Field definitions**

| Field | Type | Description |
|---|---|---|
| `version` | integer | Schema version of this manifest file |
| `canonical_id` | string | Durable provider-specific source identity |
| `source_url` | string | Canonical remote URL |
| `source_type` | string | Source provider/type (`confluence`, `google_doc`) |
| `materialized_path` | string | Relative path from `knowledge/` to the materialized file (empty until first sync) |
| `sync_attachments` | boolean | Whether attachments should be synced |
| `target_path` | string | Intended placement area inside `knowledge/` |
| `status` | string | Lifecycle state (`active`, `missing`) |
| `missing_since_utc` | string or null | Timestamp when file first detected missing (only when status=`missing`) |
| `sync_hint` | object or null | Advisory freshness hint (not authoritative) |

### `sync_hint`

| Field | Type | Description |
|---|---|---|
| `content_hash` | string | Hash of the last synced source body |
| `last_synced_utc` | string | UTC time of the last successful sync |

`sync_hint` is advisory — used to avoid unnecessary work, not as a source
of truth.

**Synced source manifest example**

See [brain-example c987654.json](../../brain-example/.brain-sync/sources/c987654.json)
for a live instance. Inline:

```json
{
  "version": 1,
  "canonical_id": "confluence:987654",
  "source_url": "https://acme.atlassian.net/wiki/spaces/PT/pages/987654/Attachment+Handling",
  "source_type": "confluence",
  "materialized_path": "teams/platform/c987654-attachment-handling.md",
  "sync_attachments": true,
  "target_path": "teams/platform",
  "status": "active",
  "sync_hint": {
    "content_hash": "sha256:9de917e9...",
    "last_synced_utc": "2026-03-15T08:42:00Z"
  }
}
```

> **v21 current**: Source manifests use `manifest_version` instead of
> `version` and include `fetch_children` and `child_path` as persisted
> flags. v23 standardises the version field name and removes
> `fetch_children` and `child_path` (they become command parameters
> consumed at execution time rather than durable manifest state).
> See [RULES.md — Schema Evaluation](RULES.md#schema-evaluation).

**Current implementation**:
[manifest.py](../../src/brain_sync/manifest.py),
[pipeline.py](../../src/brain_sync/pipeline.py)

---

## Brain Schema

The brain schema identifies the brain root and carries global brain-level
configuration.

**Path pattern**

```text
.brain-sync/brain.json
```

**Field definitions**

| Field | Type | Description |
|---|---|---|
| `version` | integer | Brain schema version |

This is intentionally minimal. Future versions may add brain-level
configuration (e.g. default regen settings, journal enable/disable).

**Brain manifest example**

See [brain-example brain.json](../../brain-example/.brain-sync/brain.json)
for a live instance. Inline:

```json
{
  "version": 1
}
```

> **v21 current**: The equivalent file is `.brain-sync/version.json` with
> `{"manifest_version": 1}`. v23 renames to `brain.json` with `version`.

**New in v23** — no v21 equivalent exists under this name.

---

## Insight State Schema

The insight state schema tracks the regeneration state for a knowledge
area's insights. It exists to answer:

- what knowledge content hash was last summarized
- what structural shape was last seen
- what summary text hash was produced
- when regeneration last completed

**Path pattern**

```text
knowledge/<area>/.brain-sync/insights/insight-state.json
```

Examples:

- `knowledge/_core/.brain-sync/insights/insight-state.json`
- `knowledge/teams/platform/.brain-sync/insights/insight-state.json`
- `knowledge/.brain-sync/insights/insight-state.json` (root area)

**Field definitions**

| Field | Type | Description |
|---|---|---|
| `version` | integer | Schema version of this manifest file |
| `content_hash` | string | Hash of the semantic inputs to the area summary |
| `structure_hash` | string | Hash of the structural layout of the area |
| `summary_hash` | string | Hash of the generated summary content |
| `last_regen_utc` | string | UTC time of the last successful regeneration |

**Insight state manifest example**

See [brain-example platform insight-state.json](../../brain-example/knowledge/teams/platform/.brain-sync/insights/insight-state.json)
for a live instance. Inline:

```json
{
  "version": 1,
  "content_hash": "sha256:445b826d...",
  "structure_hash": "sha256:5ecbd245...",
  "summary_hash": "sha256:6041664d...",
  "last_regen_utc": "2026-03-15T08:46:00Z"
}
```

> **v21 current**: Regen state lives at `insights/<area>/.regen-meta.json`
> (a separate top-level `insights/` directory mirroring `knowledge/`).
> The file uses the same fields but is named `.regen-meta.json`. v23
> moves this to `knowledge/<area>/.brain-sync/insights/insight-state.json`.

**Current implementation**:
[sidecar.py](../../src/brain_sync/sidecar.py),
[regen.py](../../src/brain_sync/regen.py)

---

## Synced Source Frontmatter Schema

The synced source frontmatter schema embeds durable source identity inside a
materialized markdown document.

This schema is instantiated as **frontmatter** (YAML embedded at the top of
the markdown file) rather than as a standalone manifest.

It is the **authoritative identity** of a synced markdown document.

**Path pattern**

```text
knowledge/**/*.md
```

Only markdown files materialized from synced sources carry this frontmatter.
Human-authored files do not.

If a materialized markdown file already has YAML frontmatter, brain-sync
must merge rather than replace it: preserve existing keys and upsert
only `brain_sync_source`, `brain_sync_canonical_id`, and
`brain_sync_source_url`.

**Field definitions**

| Field | Type | Description |
|---|---|---|
| `brain_sync_source` | string | Provider/type name (`confluence`, `google_doc`) |
| `brain_sync_canonical_id` | string | Authoritative synced-source identity |
| `brain_sync_source_url` | string | Canonical remote URL |

**Synced source frontmatter example**

See [brain-example c987654-attachment-handling.md](../../brain-example/knowledge/teams/platform/c987654-attachment-handling.md)
for a live instance. Inline:

```md
---
brain_sync_source: confluence
brain_sync_canonical_id: confluence:987654
brain_sync_source_url: https://acme.atlassian.net/wiki/spaces/PT/pages/987654/Attachment+Handling
---

# Attachment Handling
```

> **v21 current**: Identity is embedded as HTML comments rather than YAML
> frontmatter:
> ```html
> <!-- brain-sync-source: confluence:987654 -->
> <!-- brain-sync-managed: local edits may be overwritten -->
> ```
> v23 proposes YAML frontmatter for cleaner parsing and standard tooling
> compatibility.
>
> During transition and repair, readers may still accept legacy HTML
> comment identity markers as a fallback. New writes use YAML
> frontmatter only.

**Current implementation**:
[pipeline.py](../../src/brain_sync/pipeline.py),
[fileops.py](../../src/brain_sync/fileops.py)

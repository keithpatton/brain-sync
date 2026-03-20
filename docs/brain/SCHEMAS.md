# Brain Schemas

This document defines the portable Brain Format `1.2` schema surfaces owned by
the brain root.

Agent-first reading model:

- first identify the portable artifact path
- then read the **Authority Class** column to see whether a field is schema
  metadata, [brain normative state](../GLOSSARY.md#brain-normative-state), or
  [brain reconciliation baseline](../GLOSSARY.md#brain-reconciliation-baseline)
- use [`../RULES.md`](../RULES.md) and [`../GLOSSARY.md`](../GLOSSARY.md) for
  lifecycle behavior; this document stays focused on persisted shape

Implementation references point at canonical owners, not compatibility shims.

---

## Source Manifest Schema

The source manifest is the portable authority for synced-source identity,
placement, lifecycle, and last-settled source baseline.

Each synced source has one durable manifest at:

```text
.brain-sync/sources/<source_dir_id>.json
```

`source_dir_id` is the filesystem-safe derivative of the canonical ID and is
also reused for per-source attachment directories.

### Fields

| Field | Type | Required | Authority Class | Meaning |
|---|---|---|---|---|
| `version` | integer | yes | schema metadata | Source manifest schema version. Current value: `3`. |
| `canonical_id` | string | yes | brain normative state | Durable provider-specific identity. |
| `source_url` | string | yes | brain normative state | Canonical source URL. |
| `source_type` | string | yes | brain normative state | Durable source type (`confluence`, `google_doc`, `test`). |
| `sync_attachments` | boolean | yes | brain normative state | Durable attachment-sync setting. |
| `knowledge_path` | string | yes | brain normative state | Durable knowledge-file anchor, relative to `knowledge/`. |
| `knowledge_state` | string | yes | brain normative state | Durable lifecycle state for the knowledge file. |
| `content_hash` | string or null | conditional | brain reconciliation baseline | Last successful materialized content hash. |
| `remote_fingerprint` | string or null | conditional | brain reconciliation baseline | Last successful adapter-owned freshness token. |
| `materialized_utc` | string or null | conditional | brain reconciliation baseline | UTC time when the current materialized source baseline was accepted into portable brain state after successful full materialization. |

Retired fields from Brain Format `1.0` are intentionally absent:

- `materialized_path`
- `target_path`
- `status`
- `sync_hint`

### `knowledge_state`

Allowed values:

- `awaiting`
- `materialized`
- `stale`
- `missing`

### State Matrix

| `knowledge_state` | File expectation | `content_hash` | `remote_fingerprint` | `materialized_utc` |
|---|---|---|---|---|
| `awaiting` | file not yet expected | null | null | null |
| `materialized` | file must exist at `knowledge_path` | set | set | set |
| `stale` | file may exist, but must be rematerialized | set | set | set |
| `missing` | file should not currently be treated as present, but the source remains registered | may stay set | may stay set | may stay set |

### Path Semantics

`knowledge_path` is always the durable anchor for the source's knowledge file:

- registration writes a deterministic provisional path derived from the
  requested area plus the source-dir ID
- successful materialization may replace that provisional filename with the
  final materialized filename
- rediscovery or folder moves update `knowledge_path` immediately

The parent of `knowledge_path` is the effective area path.

### Example

```json
{
  "version": 2,
  "canonical_id": "confluence:987654",
  "source_url": "https://acme.atlassian.net/wiki/spaces/PT/pages/987654/Attachment+Handling",
  "source_type": "confluence",
  "sync_attachments": true,
  "knowledge_path": "teams/platform/c987654-attachment-handling.md",
  "knowledge_state": "materialized",
  "content_hash": "sha256:9de917e9...",
  "remote_fingerprint": "rev-42",
  "materialized_utc": "2026-03-19T08:42:00+00:00"
}
```

Canonical owners:
`src/brain_sync/brain/manifest.py`,
`src/brain_sync/brain/repository.py`

---

## Brain Manifest Schema

The brain manifest carries portable format metadata for the whole brain. It
does not carry per-source or per-area state.

The portable brain manifest lives at:

```text
.brain-sync/brain.json
```

Fields:

| Field | Type | Required | Authority Class | Meaning |
|---|---|---|---|---|
| `version` | integer | yes | schema metadata | Portable brain-format major version. Current on-disk value: `1`. |

Brain Format `1.2` keeps the same on-disk brain manifest number because the
portable compatibility line is still within major format `1`.

---

## Insight State Schema

The insight-state manifest is the portable baseline for regeneration decisions
for one knowledge area. It does not store runtime lifecycle or the summary
text itself.

Per-area portable regen state lives at:

```text
knowledge/<area>/.brain-sync/insights/insight-state.json
```

Fields:

| Field | Type | Required | Authority Class | Meaning |
|---|---|---|---|---|
| `version` | integer | yes | schema metadata | Insight-state schema version. |
| `content_hash` | string | yes | brain reconciliation baseline | Hash of semantic inputs for the summary. |
| `structure_hash` | string | yes | brain reconciliation baseline | Hash of structural layout. |
| `summary_hash` | string | yes | brain reconciliation baseline | Hash of generated summary text. |
| `last_regen_utc` | string | yes | brain reconciliation baseline | UTC time when the current generated-insight baseline was accepted into portable brain state after successful regeneration. |

Canonical owner:
`src/brain_sync/brain/sidecar.py`

---

## Synced Source Frontmatter Schema

Materialized synced markdown files embed authoritative identity frontmatter.
Frontmatter binds the document to its synced-source identity; lifecycle and
freshness stay in the source manifest.

Fields:

| Field | Type | Meaning |
|---|---|---|
| `brain_sync_source` | string | Durable provider/type name. |
| `brain_sync_canonical_id` | string | Authoritative synced-source identity. |
| `brain_sync_source_url` | string | Canonical remote URL. |

New writes use YAML frontmatter only. Readers may still tolerate legacy HTML
comment markers during repair or migration.

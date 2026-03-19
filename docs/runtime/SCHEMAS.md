# Runtime Schemas

This document defines machine-local runtime artifacts for the supported
Brain Format `1.1` / runtime schema `v26` release.

Runtime artifacts live outside the portable brain and are rebuildable unless
explicitly noted otherwise.

---

## Runtime Directory

Default location:

```text
~/.brain-sync/
```

If `BRAIN_SYNC_CONFIG_DIR` is set, that directory is used instead.

Current runtime artifacts:

- `config.json`
- `daemon.json`
- `db/brain-sync.sqlite`
- `logs/`

---

## Runtime DB Schema

Runtime DB path:

```text
~/.brain-sync/db/brain-sync.sqlite
```

The current schema version is `26`, stored in `meta.schema_version`.

Supported earlier runtime schemas such as `v23`, `v24`, and `v25` migrate in
place to `v26`. Unsupported or provisional DB shapes are rebuilt.

### `meta`

| Field | Type | Meaning |
|---|---|---|
| `key` | text | Metadata key. |
| `value` | text | Metadata value. |

Required row:

- `schema_version`

### `sync_polling`

`sync_polling` is the narrowed runtime source-state table. It owns only
machine-local polling and scheduling facts.

| Field | Type | Meaning |
|---|---|---|
| `canonical_id` | text | Source canonical ID; primary key. |
| `last_checked_utc` | text or null | UTC time of the last poll. |
| `current_interval_secs` | integer | Active backoff/poll interval. |
| `next_check_utc` | text or null | Next scheduled poll time. |
| `interval_seconds` | integer or null | Persisted scheduler interval. |

Portable source truth does not live here. Durable source lifecycle, path,
freshness, and last-successful materialization facts live in the portable
source manifest.

### `regen_locks`

| Field | Type | Meaning |
|---|---|---|
| `knowledge_path` | text | Knowledge path; primary key. |
| `regen_status` | text | Regen lifecycle state. |
| `regen_started_utc` | text or null | UTC time the current regen began. |
| `owner_id` | text or null | Runtime owner/session identifier. |
| `error_reason` | text or null | Failure reason for failed state. |

### `child_discovery_requests`

| Field | Type | Meaning |
|---|---|---|
| `canonical_id` | text | Source canonical ID; primary key. |
| `fetch_children` | integer | Boolean stored as `0` or `1`. |
| `child_path` | text or null | Runtime-only placement hint for discovered children. |
| `updated_utc` | text | UTC timestamp of the last request update. |

### `operational_events`

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | Row ID; primary key. |
| `event_type` | text | Stable event family/type. |
| `created_utc` | text | UTC timestamp of event creation. |
| `session_id` | text or null | Runtime session identifier. |
| `owner_id` | text or null | Ownership/session identifier. |
| `canonical_id` | text or null | Source canonical ID when applicable. |
| `knowledge_path` | text or null | Knowledge path when applicable. |
| `outcome` | text or null | Stable outcome label. |
| `duration_ms` | integer or null | Optional duration in milliseconds. |
| `details_json` | text or null | Optional JSON payload. |

### `token_events`

| Field | Type | Meaning |
|---|---|---|
| `id` | integer | Row ID; primary key. |
| `session_id` | text | Session identifier. |
| `operation_type` | text | Operation category. |
| `resource_type` | text or null | Resource category. |
| `resource_id` | text or null | Resource identifier. |
| `is_chunk` | integer | Boolean stored as `0` or `1`. |
| `model` | text or null | Model name. |
| `input_tokens` | integer or null | Input tokens. |
| `output_tokens` | integer or null | Output tokens. |
| `total_tokens` | integer or null | Total tokens. |
| `duration_ms` | integer or null | Invocation duration. |
| `num_turns` | integer or null | Number of turns. |
| `success` | integer | Boolean stored as `0` or `1`. |
| `created_utc` | text | UTC timestamp of event creation. |

Current implementation:
`src/brain_sync/runtime/repository.py`

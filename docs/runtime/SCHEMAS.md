# Runtime Schemas

This document defines machine-local runtime artifacts for the supported
Brain Format `1.2` / runtime schema `v28` release.

Runtime artifacts live outside the portable brain. They support execution,
coordination, and observability; they do not define portable brain meaning.

Agent-first reading model:

- if runtime state and portable brain state disagree, the filesystem plus
  portable manifests win
- `meta` is authoritative only for interpreting the runtime DB itself
- all other runtime artifacts are machine-local helpers or history, not
  portable truth

Startup and re-attachment rule:

- persisted runtime artifacts are non-authoritative cached local history
- when a process starts, or when a runtime attaches to a brain root, existing
  runtime rows must be reconciled against the currently attached portable
  brain before they drive lifecycle behavior
- a runtime row may inform local recovery or scheduling, but it must not by
  itself assert current source state, preserve cross-process lifecycle
  eligibility, or authorize destructive mutation

---

## Runtime Directory

Default location:

```text
~/.brain-sync/
```

If `BRAIN_SYNC_CONFIG_DIR` is set, that directory is used instead.

Current runtime artifacts:

| Artifact | Role |
|---|---|
| `config.json` | machine-local config, active-brain selection, credentials, and local defaults |
| `daemon.json` | current daemon lifecycle snapshot |
| `db/brain-sync.sqlite` | runtime coordination, scheduling, and telemetry store |
| `logs/` | rotating local logs |

---

## `config.json`

`config.json` is the machine-local runtime config file. It is not versioned as
a separate schema family, so this section documents the keys currently
consumed by brain-sync.

Current top-level keys:

| Key | Type | Meaning |
|---|---|---|
| `brains` | array[string] | Registered brain roots. Only the first entry is treated as active in the current single-brain runtime model. |
| `regen` | object | Optional defaults for regeneration behavior. |
| `confluence` | object | Optional Confluence credentials. |
| `google` | object | Optional Google OAuth token cache. |
| `token_events` | object | Optional local token-telemetry retention settings. |
| `log_level` | string | Optional default CLI/MCP log level. |

Current nested shapes used by brain-sync:

- `regen`: `model` (string), `effort` (string), `timeout` (integer seconds),
  `max_turns` (integer), `similarity_threshold` (number)
- `confluence`: `domain` (string), `email` (string), `token` (string)
- `google`: `token` (object; Google authorized-user credentials payload)
- `token_events`: `retention_days` (integer)

Unknown keys may exist for forward compatibility; readers should ignore keys
they do not understand.

---

## `daemon.json`

`daemon.json` is the current daemon lifecycle snapshot written in the runtime
directory.

| Field | Type | Meaning |
|---|---|---|
| `pid` | integer | Process ID of the daemon instance that wrote the file. |
| `started_at` | string or null | UTC time when the current daemon session started. |
| `status` | string | Current daemon status. Typical values: `starting`, `ready`, `stopped`. |

---

## Runtime DB Schema

Runtime DB path:

```text
~/.brain-sync/db/brain-sync.sqlite
```

The current schema version is `28`, stored in `meta.schema_version`.

Supported earlier runtime schemas `v23`, `v24`, `v25`, `v26`, and `v27`
migrate in place to `v28`. Unsupported or provisional DB shapes are rebuilt.

SQLite conventions used here:

- UTC timestamps are stored as text
- booleans are stored as `0` or `1`

Current table roles:

| Table | Role |
|---|---|
| `meta` | runtime DB schema metadata |
| `sync_polling` | polling schedule and source-check timing cache for actively polled sources |
| `source_lifecycle_runtime` | machine-local missing/finalization coordination for registered sources |
| `regen_locks` | regen ownership and lifecycle coordination by knowledge path |
| `child_discovery_requests` | one-shot runtime requests for discovered children |
| `operational_events` | append-only local operational event trail |
| `token_events` | append-only local LLM usage telemetry |

### `meta`

`meta` is authoritative only for interpreting the runtime DB itself.

| Field | Type | Meaning |
|---|---|---|
| `key` | text | Metadata key. |
| `value` | text | Metadata value. |

Required row:

- `schema_version`

Current known optional rows:

- `lifecycle_session_id` - current lifecycle-session identifier for the
  attached lifecycle-owning process
- `lifecycle_session_owner_kind` - lifecycle-session owner kind such as
  `cli`, `daemon`, or `mcp`

Those lifecycle-session rows are machine-local runtime hints only. They may be
replaced by later process attachment and must not become portable lifecycle
authority.

### `sync_polling`

`sync_polling` is the narrowed runtime source-state table. It owns only
machine-local polling, scheduling, and related runtime tracking facts.

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

Persisted `sync_polling` rows are reusable only as machine-local polling
history. After process start or brain re-attachment, they must not be treated
as proof that the currently attached brain still has the same active-source
set or schedule assumptions as when the prior process exited.

Missing registered sources leave `sync_polling`. They remain represented only
by portable manifests plus `source_lifecycle_runtime` until rediscovery,
successful rematerialization, or explicit finalization.

### `source_lifecycle_runtime`

`source_lifecycle_runtime` is a machine-local coordination table for registered
sources that are missing, are being explicitly finalized, or currently need a
source-level lifecycle lease.

| Field | Type | Meaning |
|---|---|---|
| `canonical_id` | text | Source canonical ID; primary key. |
| `local_missing_first_observed_utc` | text or null | UTC timestamp of the first local missing observation retained in this row. |
| `local_missing_last_confirmed_utc` | text or null | UTC timestamp of the most recent local missing confirmation retained in this row. |
| `missing_confirmation_count` | integer | Count of local missing confirmations retained in this row. |
| `last_missing_confirmation_session_id` | text or null | Lifecycle session that wrote the most recent retained missing confirmation. |
| `lease_owner` | text or null | Source-level lifecycle lease owner when one is active. |
| `lease_expires_utc` | text or null | UTC expiry time for the current source-level lifecycle lease. |

Rows are cached local history, not portable truth. After process start or
brain re-attachment, an existing row may inform revalidation, but it must not
by itself assert current source state, preserve cross-process finalization
eligibility, or authorize destructive mutation.

Explicit finalization eligibility depends on fresh local revalidation in the
current lifecycle session. In practice that means inherited confirmation counts
alone are insufficient: the latest retained missing confirmation must have been
recorded by the current lifecycle session before destructive finalization may
proceed.

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

Operational events are append-only diagnostics only. They are not a replay
source, may be missing or duplicated, and must not become lifecycle
authority.

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

Canonical owner:
`src/brain_sync/runtime/repository.py`

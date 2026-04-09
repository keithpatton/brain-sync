# Runtime Schemas

This document defines machine-local runtime artifacts for the supported
Brain Format `1.2` / runtime schema `v30` release.

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
| `daemon.lock` | durable config-dir daemon startup guard plus best-effort lock metadata |
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
| `brains` | array[string] | Registered brain roots. Only the first entry is treated as active in the current single-brain runtime model. `attach-root` rewrites the selected root to index `0` and preserves any other registered roots after it in deduplicated order for compatibility only. |
| `regen` | object | Optional defaults for regeneration behavior. |
| `confluence` | object | Optional Confluence credentials. |
| `google` | object | Optional Google OAuth client config and token cache. |
| `operational_events` | object | Optional local operational-event retention settings. |
| `token_events` | object | Optional local token-telemetry retention settings. |
| `log_level` | string | Optional default CLI/MCP log level. |

Current nested shapes used by brain-sync:

- `regen`: `model` (string), `effort` (string), `timeout` (integer seconds),
  `max_turns` (integer), `similarity_threshold` (number)
- `confluence`: `domain` (string), `email` (string), `token` (string)
- `google`: `oauth_client.installed.client_id` (string), `oauth_client.installed.client_secret` (string), `oauth_client.installed.project_id` (string, optional), `token` (object; Google authorized-user credentials payload)
- `operational_events`: `retention_days` (integer)
- `token_events`: `retention_days` (integer)

Unknown keys may exist for forward compatibility; readers should ignore keys
they do not understand.

---

## `daemon.json`

`daemon.json` is the current daemon lifecycle snapshot written in the runtime
directory. It is descriptive status, not the durable startup lock. The current
runtime model enforces daemon exclusivity per config directory via
`daemon.lock`.

| Field | Type | Meaning |
|---|---|---|
| `pid` | integer | Process ID of the daemon instance that wrote the file. |
| `started_at` | string or null | UTC time when the current daemon session started. |
| `updated_at` | string | UTC time when this snapshot was last rewritten. |
| `stopped_at` | string or null | UTC time when the current daemon session last wrote a stopped snapshot. |
| `daemon_id` | string | Runtime-unique daemon session identifier for this process start. |
| `brain_root` | string | Normalized attached brain-root path for the daemon that wrote the snapshot. |
| `status` | string | Current daemon status. Typical values: `starting`, `ready`, `stopped`. |
| `controller_kind` | string | Current daemon controller kind. Supported v1 values are `terminal-foreground`, `launcher-background`, and `unknown`. |

`daemon.json` is the fast runtime snapshot used by setup/admin status and
daemon-adoption checks. It does not replace `daemon.lock`, which remains the
durable startup-exclusion mechanism for the runtime config directory.

## Runtime DB Schema

Runtime DB path:

```text
~/.brain-sync/db/brain-sync.sqlite
```

The current schema version is `30`, stored in `meta.schema_version`.

Supported earlier runtime schemas `v23`, `v24`, `v25`, `v26`, `v27`, and
`v29` migrate in place to `v30`. The unreleased interim `v28` developer
schema also migrates in place to `v30` when encountered. Unsupported or
provisional DB shapes are rebuilt.

The `v29 -> v30` migration is intentionally machine-local:

- add `remote_last_changed_utc` to `sync_polling`
- delete all rows from `sync_polling`
- preserve other runtime tables such as `source_lifecycle_runtime`,
  `regen_locks`, `operational_events`, and `token_events`

That reset prevents pre-`v30` poll timings derived from portable
`materialized_utc` from surviving into the new runtime-freshness model.

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
| `remote_last_changed_utc` | text or null | Adapter-confirmed upstream freshness timestamp for the most recent synchronized-content change known to this machine. |
| `current_interval_secs` | integer | Active backoff/poll interval. |
| `next_check_utc` | text or null | Next scheduled poll time. |
| `interval_seconds` | integer or null | Persisted scheduler interval. |

Portable source truth does not live here. Durable source lifecycle, path,
freshness, and last-successful materialization facts live in the portable
source manifest.

`remote_last_changed_utc` is not a generic provider last-modified field. It is
the adapter's best timestamp for a change that affects synchronized content
semantics for that source on this machine. Providers may reuse raw upstream
timestamps only when the adapter treats them as trustworthy synchronized-
content freshness. Portable `materialized_utc` remains the authoritative local
materialization timestamp, and existing `last_changed_utc` read models remain
tied to that portable field rather than to `remote_last_changed_utc`.

Persisted `sync_polling` rows are reusable only as machine-local polling
history. After process start or brain re-attachment, they must not be treated
as proof that the currently attached brain still has the same active-source
set or schedule assumptions as when the prior process exited.

Backoff computation prefers `remote_last_changed_utc` when present and falls
back to portable `materialized_utc` only until the current machine has
re-established runtime upstream freshness. That means different machines may
temporarily schedule the same portable brain differently until each runtime has
rebuilt its own `sync_polling` freshness hints.

After the `v29 -> v30` reset, active non-missing sources start with no
`sync_polling` row and are therefore scheduled immediately by the existing
no-row path. Missing registered sources remain excluded because active-source
projection still filters them out before polling.

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
| `local_missing_last_confirmed_utc` | text or null | UTC timestamp of the most recent local missing observation retained in this row. |
| `lease_owner` | text or null | Source-level lifecycle lease owner when one is active. |
| `lease_expires_utc` | text or null | UTC expiry time for the current source-level lifecycle lease. |

Rows are cached local history, not portable truth. After process start or
brain re-attachment, an existing row may inform revalidation, but it must not
by itself assert current source state or authorize destructive mutation.

In `v30`, the retained missing-observation timestamps are diagnostic and
re-attachment aids only. They describe the first and latest local missing
observations seen on this machine, but they do not preserve cross-process
finalization eligibility. Explicit finalization is authorized only by current
local revalidation plus source-level lease ownership.

### `regen_locks`

| Field | Type | Meaning |
|---|---|---|
| `knowledge_path` | text | Knowledge path; primary key. |
| `regen_status` | text | Regen lifecycle state. |
| `regen_started_utc` | text or null | UTC time the current regen began. |
| `owner_id` | text or null | Runtime owner/session identifier. |
| `error_reason` | text or null | Failure reason for failed state. |

`regen_locks` is coordination-only runtime state. It is not the durable REGEN
analytics surface and must not be treated as historical decision or cost
telemetry.

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

For current REGEN diagnostics, `operational_events` is the semantic trail:

- `regen.started` carries the run reason, evaluation outcome, and planner
  details such as prompt-budget class, component token breakdown, deferred
  files, and omitted child summaries
- `regen.completed` carries the terminal reason, propagation decision, and
  summary/journal write facts
- `regen.failed` carries the terminal error, typed reason, and failure phase

Current production event-type names are centralized in
`src/brain_sync/runtime/operational_events.py`. Runtime persistence remains
owned only by `src/brain_sync/runtime/repository.py`.

Retention is machine-local via `config.json`:

- `operational_events.retention_days` controls local retention and defaults to
  `90` when unset
- daemon startup prunes old `operational_events` rows before loading active
  sync state
- prune failure is non-fatal; loss or staleness of this history does not alter
  portable or runtime lifecycle authority

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

For current REGEN diagnostics, `token_events` is the per-call cost surface:

- each row represents one backend invocation rather than one high-level regen
  path decision
- chunk summarization calls and final merge calls are recorded as separate rows
  through `is_chunk`
- prompt-component sizes, skip reasons, and propagation reasons do not live in
  this table; those belong to `operational_events`

# Runtime Schemas

This document describes the schema-defined machine-local runtime artifacts used
by brain-sync. These artifacts live in the
[brain-sync runtime directory](../GLOSSARY.md#brain-sync-runtime-directory),
not inside the portable brain.

Runtime versioning is defined in [../VERSIONING.md](../VERSIONING.md).

Supported runtime schema versions should migrate in place during normal app
upgrades. Rebuild is the fallback for missing, corrupt, or unsupported runtime
state.

The current runtime architecture is single-brain per config directory. Runtime
artifacts under `~/.brain-sync/` belong to the active brain for that config
directory, not to an arbitrary caller-supplied root.

Implementation references in this document point at canonical package owners,
not compatibility shims.

---

## Runtime Directory

The runtime directory path is:

```text
~/.brain-sync/
```

If `BRAIN_SYNC_CONFIG_DIR` is set, brain-sync uses that directory instead.

Current runtime artifacts:

- `config.json`
- `daemon.json`
- `db/brain-sync.sqlite`
- `logs/` (implementation-managed log files; no stable schema defined here)

---

## Config Schema

`config.json` stores machine-local application configuration.

**Path pattern**

```text
~/.brain-sync/config.json
```

The file is currently versionless. Unknown keys are implementation-defined.

**Current top-level keys used by the implementation**

| Key | Type | Description |
|---|---|---|
| `brains` | array of string | Registered brain root paths; the first entry is the active brain for this config directory |
| `regen` | object | Regen-related runtime options |
| `confluence` | object | Confluence credentials |
| `google` | object | Google OAuth token payload |
| `token_events` | object | Token telemetry retention settings |
| `log_level` | string | Default runtime log level |

### `brains`

| Field | Type | Description |
|---|---|---|
| `<item>` | string | Absolute or user-expandable path to a registered brain root |

Only the first array entry is active in the current single-brain runtime
architecture. Additional entries may still appear as compatibility leftovers,
but they are not concurrent runtime-isolation boundaries.

### `regen`

| Field | Type | Description |
|---|---|---|
| `model` | string | Optional default model selection for regeneration |

### `confluence`

| Field | Type | Description |
|---|---|---|
| `domain` | string | Confluence domain |
| `email` | string | Confluence account email |
| `token` | string | Confluence API token |

### `google`

| Field | Type | Description |
|---|---|---|
| `token` | object | OAuth credential payload persisted from Google client libraries |

### `token_events`

| Field | Type | Description |
|---|---|---|
| `retention_days` | integer | Retention window for runtime telemetry rows |

**Example**

```json
{
  "brains": [
    "/home/alice/my-brain"
  ],
  "regen": {
    "model": "example-model"
  },
  "confluence": {
    "domain": "acme.atlassian.net",
    "email": "you@example.com",
    "token": "redacted"
  },
  "google": {
    "token": {
      "token": "redacted",
      "refresh_token": "redacted"
    }
  },
  "token_events": {
    "retention_days": 90
  },
  "log_level": "INFO"
}
```

**Current implementation**:
[runtime/config.py](../../src/brain_sync/runtime/config.py),
[application/config.py](../../src/brain_sync/application/config.py),
[application/init.py](../../src/brain_sync/application/init.py),
[sources/googledocs/auth.py](../../src/brain_sync/sources/googledocs/auth.py)

---

## Daemon Status Schema

`daemon.json` stores daemon lifecycle status for the current machine.

**Path pattern**

```text
~/.brain-sync/daemon.json
```

The file is currently versionless.

**Field definitions**

| Field | Type | Description |
|---|---|---|
| `pid` | integer | Process ID of the daemon instance that last wrote the file |
| `started_at` | string or null | UTC timestamp recorded when daemon startup begins |
| `status` | string | Lifecycle status (`starting`, `ready`, `stopped`) |

**Example**

```json
{
  "pid": 12345,
  "started_at": "2026-03-17T08:15:00+00:00",
  "status": "ready"
}
```

**Current implementation**:
[runtime/repository.py](../../src/brain_sync/runtime/repository.py)

---

## Runtime DB Schema

The runtime database stores machine-local cache, coordination, and telemetry
state.

**Path pattern**

```text
~/.brain-sync/db/brain-sync.sqlite
```

The runtime DB schema version is recorded in the `meta` table as
`schema_version`. The current schema version is `25`.

### `meta`

| Field | Type | Description |
|---|---|---|
| `key` | text | Metadata key |
| `value` | text | Metadata value |

Required row:

- `schema_version` -> runtime DB schema integer

### `sync_cache`

Machine-local polling and freshness cache for registered sources.

| Field | Type | Description |
|---|---|---|
| `canonical_id` | text | Source canonical ID; primary key |
| `last_checked_utc` | text or null | UTC time of last poll |
| `last_changed_utc` | text or null | UTC time source was last observed changed |
| `current_interval_secs` | integer | Active backoff/poll interval |
| `content_hash` | text or null | Last observed content hash |
| `metadata_fingerprint` | text or null | Last observed metadata fingerprint |
| `next_check_utc` | text or null | Next scheduled poll time |
| `interval_seconds` | integer or null | Persisted scheduler interval |

### `regen_locks`

Cross-process runtime lifecycle state for regeneration ownership.

| Field | Type | Description |
|---|---|---|
| `knowledge_path` | text | Knowledge path; primary key |
| `regen_status` | text | Lifecycle status for the area |
| `regen_started_utc` | text or null | UTC time current regen began |
| `owner_id` | text or null | Regen session owner identifier |
| `error_reason` | text or null | Last failure reason for failed state |

### `child_discovery_requests`

Machine-local one-shot child-discovery request state for registered sources.

| Field | Type | Description |
|---|---|---|
| `canonical_id` | text | Source canonical ID; primary key |
| `fetch_children` | integer | Boolean flag encoded as `0` or `1` |
| `child_path` | text or null | Runtime-only placement hint for discovered children |
| `updated_utc` | text | UTC timestamp of the last request update |

### `token_events`

Append-only LLM invocation telemetry.

| Field | Type | Description |
|---|---|---|
| `id` | integer | Row ID; primary key |
| `session_id` | text | Session identifier |
| `operation_type` | text | Operation category (`regen`, `query`, `classify`) |
| `resource_type` | text or null | Resource category |
| `resource_id` | text or null | Resource identifier |
| `is_chunk` | integer | Boolean flag encoded as `0` or `1` |
| `model` | text or null | Model name |
| `input_tokens` | integer or null | Input token count |
| `output_tokens` | integer or null | Output token count |
| `total_tokens` | integer or null | Total token count |
| `duration_ms` | integer or null | Invocation duration in milliseconds |
| `num_turns` | integer or null | Number of turns used |
| `success` | integer | Boolean flag encoded as `0` or `1` |
| `created_utc` | text | UTC timestamp of event creation |

**Current implementation**:
[runtime/repository.py](../../src/brain_sync/runtime/repository.py)

### `dirty_knowledge_paths`

Runtime-owned invalidation set for knowledge areas that need reclassification
or downstream refresh.

| Field | Type | Description |
|---|---|---|
| `knowledge_path` | text | Knowledge path; primary key |
| `reason` | text or null | Last invalidation reason |
| `updated_utc` | text | UTC timestamp of the latest invalidation |

### `path_observations`

Runtime snapshot of observed directory mtimes used to narrow startup
reconcile classification candidates without classifying every tracked area.

| Field | Type | Description |
|---|---|---|
| `knowledge_path` | text | Knowledge path; primary key |
| `observed_mtime_ns` | integer | Last observed directory mtime in nanoseconds |
| `observed_utc` | text | UTC timestamp of when the observation was recorded |

### `invalidation_tokens`

Runtime-owned invalidation generations for derived read models.

| Field | Type | Description |
|---|---|---|
| `scope` | text | Invalidated view name; primary key |
| `generation` | integer | Monotonic generation counter |
| `dirty` | integer | Boolean flag encoded as `0` or `1` |
| `updated_utc` | text | UTC timestamp of the latest invalidation change |

Current scope used by the implementation:

- `area_index`

### `operational_events`

Append-only machine-local operational event trail for ownership transitions,
reconcile outcomes, watcher move handling, regen lifecycle, and query/index
lifecycle.

| Field | Type | Description |
|---|---|---|
| `id` | integer | Row ID; primary key |
| `event_type` | text | Stable event family/type |
| `created_utc` | text | UTC timestamp of event creation |
| `session_id` | text or null | Runtime session identifier |
| `owner_id` | text or null | Ownership/session lock identifier |
| `canonical_id` | text or null | Source canonical ID when applicable |
| `knowledge_path` | text or null | Knowledge path when applicable |
| `outcome` | text or null | Stable outcome label |
| `duration_ms` | integer or null | Optional duration in milliseconds |
| `details_json` | text or null | Optional JSON payload for machine-local details |

Writes are append-only and non-fatal. Event persistence failure must not abort
the user-visible operation that emitted the event.

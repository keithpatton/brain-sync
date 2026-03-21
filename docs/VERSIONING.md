# Versioning

This document defines the version model for brain-sync.

brain-sync uses three version domains:


| Domain            | Meaning                        | Current value |
| ----------------- | ------------------------------ | ------------- |
| Brain Format      | Portable filesystem contract   | `1.2`         |
| Runtime DB schema | Machine-local runtime DB shape | `v29`         |
| App version       | Packaged application version   | `0.7.0.0`     |


These versions must not be conflated.

---

## Brain Format

The Brain Format version governs portable filesystem state, including:

- source manifest fields and invariants
- frontmatter identity rules
- reserved managed namespaces
- the portable/runtime ownership split

The current Brain Format is `1.2`.

Brain Format `1.2` intentionally changes the portable source-state contract by:

- removing portable `missing_since_utc`
- keeping `knowledge_path` plus `knowledge_state` as the durable source path
and lifecycle contract
- keeping durable freshness ownership in `remote_fingerprint`

The on-disk `brain.json` file remains:

```json
{
  "version": 1
}
```

The major on-disk number stays `1` because this is still the first major
portable format family. The normative portable schema details live in
[docs/brain/SCHEMAS.md](brain/SCHEMAS.md).

### When to bump Brain Format version

Increase the Brain Format version when a change affects the portable
brain contract, for example:

- directory layout changes
- manifest filename or field contract changes
- frontmatter identity contract changes
- reserved namespace changes
- changes in what is considered portable vs runtime state

Do not bump the Brain Format version for:

- internal refactors with unchanged on-disk behavior
- runtime DB schema changes only
- changes to retry logic, scheduling, or batching defaults
- implementation-only prompt/template updates that do not alter durable
filesystem state

---

## Runtime DB Schema

The runtime DB schema version governs only machine-local runtime state.

The current runtime DB schema is:

- label: `v29`
- integer value in `meta.schema_version`: `29`

Schema `v29` keeps `sync_polling` polling-only and keeps
`source_lifecycle_runtime` for machine-local missing-observation timestamps and
source-level lifecycle leases. Explicit finalization is now single-call for an
already-missing source: it depends on current revalidation and lease ownership,
not on lifecycle-session freshness or persisted confirmation counts.

Supported earlier runtime schemas migrate in place during normal upgrades.
Rebuild remains the fallback for missing, corrupt, unsupported, or provisional
runtime DB state. The unreleased intermediate `v28` schema is not the shipped
`0.7` contract; when encountered it migrates forward to `v29`.

---

## App Version

The current app version is `0.7.0.0`.

This is the current release identifier for the Brain Format `1.2` /
runtime schema `v29` row.

The canonical source is `pyproject.toml`.

---

## Compatibility Expression

Compatibility statements should use this form:

`brain-sync <app version> supports Brain Format <format version> with runtime DB schema <db version>`

Current statement:

`brain-sync 0.7.0.0 supports Brain Format 1.2 with runtime DB schema v29`

See [docs/COMPATIBILITY.md](COMPATIBILITY.md) for the supported rows and
transition guarantees.

---

## Testing Implications

Compatibility and migration tests should explicitly cover:

- fresh Brain Format `1.2` init
- `0.5.0` / Brain Format `1.0` / runtime schema `v23` ->
  `0.7.0.0` / Brain Format `1.2` / runtime schema `v29` guided migration behavior
- runtime DB `v23/v24/v25/v26/v27 -> v29` in-place migration
- unreleased runtime DB `v28 -> v29` in-place migration when encountered
- runtime DB rebuild without changing durable source truth

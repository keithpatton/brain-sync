# Versioning

This document defines the version model for brain-sync.

brain-sync uses three version domains:


| Domain            | Meaning                        | Current value |
| ----------------- | ------------------------------ | ------------- |
| Brain Format      | Portable filesystem contract   | `1.2`         |
| Runtime DB schema | Machine-local runtime DB shape | `v30`         |
| App version       | Packaged application version   | See [`pyproject.toml`](../pyproject.toml) |


These versions must not be conflated.

---

## Brain Format

The Brain Format version governs the portable brain contract on disk. In
practice, that means the durable filesystem/schema surfaces that another
runtime or another machine must interpret consistently, including:

- portable directory and path layout inside the brain root
- portable manifest and sidecar filenames, fields, and invariants
- synced-document frontmatter identity fields and rules
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
[docs/brain/SCHEMAS.md](brain/SCHEMAS.md), with the higher-level portable
scope summarized in [docs/brain/README.md](brain/README.md).

### When to bump Brain Format version

Increase the Brain Format version when a change affects the portable
brain contract, for example:

- directory layout changes
- durable manifest or sidecar filename changes
- durable manifest, sidecar, or frontmatter field contract changes
- durable generated artifact contract changes when they change the portable
  on-disk shape or meaning compatibility surface
- reserved namespace changes
- changes in what is considered portable vs runtime state

Do not bump the Brain Format version for:

- internal refactors with unchanged on-disk behavior
- runtime DB schema changes only
- changes to retry logic, scheduling, or batching defaults
- implementation-only prompt changes
- packaged regen instruction/template updates, including runtime-fed resources,
  that do not alter the portable on-disk contract

---

## Runtime DB Schema

The runtime DB schema version governs only machine-local runtime state.

The current runtime DB schema is:

- label: `v30`
- integer value in `meta.schema_version`: `30`

Schema `v30` keeps `sync_polling` polling-only and keeps
`source_lifecycle_runtime` for machine-local missing-observation timestamps and
source-level lifecycle leases. Explicit finalization is now single-call for an
already-missing source: it depends on current revalidation and lease ownership,
not on lifecycle-session freshness or persisted confirmation counts.

`v30` also adds runtime-only `remote_last_changed_utc` to `sync_polling`.
That field is the adapter-confirmed upstream freshness hint used for poll
backoff. It does not change Brain Format `1.2`, does not alter portable
`materialized_utc`, and does not retarget existing `last_changed_utc`
read-model semantics away from local materialization time.

Supported earlier runtime schemas migrate in place during normal upgrades.
Rebuild remains the fallback for missing, corrupt, unsupported, or provisional
runtime DB state. The unreleased intermediate `v28` schema is not the shipped
`0.7` contract; when encountered it migrates forward to `v30`. The
`v29 -> v30` migration clears `sync_polling` rows after adding
`remote_last_changed_utc` so each machine intentionally rebuilds its own
runtime freshness and schedule assumptions.

---

## App Version

The app version is the packaged release identifier.

The canonical source is [`pyproject.toml`](../pyproject.toml).

The current release row is defined in [COMPATIBILITY.md](COMPATIBILITY.md).

---

## Compatibility Expression

Compatibility statements should use this form:

`brain-sync <app version> supports Brain Format <format version> with runtime DB schema <db version>`

See [docs/COMPATIBILITY.md](COMPATIBILITY.md) for the supported rows and
transition guarantees.

---

## Testing Implications

Compatibility and migration tests should explicitly cover:

- fresh Brain Format `1.2` init
- `0.5.0` / Brain Format `1.0` / runtime schema `v23` ->
current `1.2` / `v30` app row guided migration behavior
- runtime DB `v23/v24/v25/v26/v27/v29 -> v30` in-place migration
- unreleased runtime DB `v28 -> v30` in-place migration when encountered
- `v29 -> v30` migration-time `sync_polling` reset with
  `remote_last_changed_utc` added
- runtime DB rebuild without changing durable source truth

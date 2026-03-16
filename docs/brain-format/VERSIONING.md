# Brain Format v1 — Versioning

This document defines the version model for brain-sync going forward.
It separates three different kinds of version so compatibility and tests
can reason about them cleanly.

---

## Version Types

brain-sync uses three distinct version domains:

| Domain | Purpose | Example |
|---|---|---|
| Brain Format version | Portable filesystem contract for a brain | `1.0` |
| Runtime DB schema version | Machine-local cache/runtime schema | `v23` |
| App version | Version of the brain-sync application | `0.5.0` |

These versions must not be conflated.

---

## Brain Format Version

The **Brain Format version** is the version of the portable on-disk
brain structure defined by the `docs/brain-format/` spec set.

It governs:

- required filesystem layout
- manifest shapes
- frontmatter identity rules
- managed namespace semantics
- what counts as brain state

For the first supportable release:

- human-readable version: `1.0`
- on-disk representation: `.brain-sync/brain.json`

```json
{
  "version": 1
}
```

The on-disk `version` field is currently the major format version only.
Minor or patch clarifications to the spec do not require a new on-disk
number unless the portable filesystem contract changes.

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

## Runtime DB Schema Version

The **runtime DB schema version** is an internal implementation detail
for machine-local runtime state. It is not the user-facing compatibility
contract.

For the first supportable release:

- runtime schema label: `v23`
- runtime schema integer in code / `meta.schema_version`: `23`

This runtime schema governs:

- `sync_cache`
- `regen_locks`
- `token_events`
- DB-local metadata used to create or rebuild those tables

The runtime DB may be deleted and rebuilt without invalidating a valid
brain. DB schema versioning therefore remains important for engineering,
but it must not be used as the public definition of "what version of
brain this is".

Although the `v23` runtime schema is a clean break from earlier migration
history, the numeric schema value is still `23` rather than resetting to
`1`. This keeps the implementation constant aligned with the supported
compatibility row and avoids ambiguity between the public `v23` label and
the integer stored in the database.

---

## App Version

The **app version** is the version of the brain-sync application itself.
It should follow semantic versioning.

For the first supportable release:

- canonical app version: `0.5.0`

Until packaged binaries/installers exist, the canonical app version
should be stamped in Python package metadata, specifically
`pyproject.toml` under `[project].version`.

If a future packaging tool requires a four-part installer version such as
`0.5.0.0`, treat that as a packaging-derived form of the canonical app
version rather than as the primary version identifier in the spec.

---

## Compatibility Expression

Compatibility should always be stated in the form:

`brain-sync <app version> supports Brain Format <format version> with runtime DB schema <db version>`

For the first supportable release:

`brain-sync 0.5.0 supports Brain Format 1.0 with runtime DB schema v23`

This means:

- the app can create and operate on Brain Format 1.0 brains
- repair/rebuild flows apply to Brain Format 1.0 brains
- runtime DB state for that release uses the v23 schema

Compatibility details live in [COMPATIBILITY.md](COMPATIBILITY.md).

---

## Testing Implications

Tests should express compatibility in terms of Brain Format version, not
just DB schema version.

Recommended test language:

- "valid Brain Format v1.0 brain"
- "drifted Brain Format v1.0 brain"
- "unsupported pre-v1 legacy brain"
- "runtime DB schema v23 rebuild"

This lets the suite distinguish:

- portable format conformance
- repair of the current supported format
- rejection of unsupported legacy layouts
- runtime cache rebuild behavior

---

## Current Baseline

The current baseline is:

- Brain Format: `1.0`
- Runtime DB schema: `v23`
- App version: `0.5.0`

Pre-Brain Format `1.0` development layouts are not part of Brain Format `1.0`. They are
legacy internal layouts, not supported portable versions.

# Versioning

This document defines the version model for brain-sync going forward.
It separates three different kinds of version so compatibility and tests
can reason about them cleanly.

---

## Version Types

brain-sync uses three distinct version domains:

| Domain | Purpose | Example |
|---|---|---|
| Brain Format version | Portable filesystem contract for a brain | `1.0` |
| Runtime DB schema version | Machine-local cache/runtime schema | `v24` |
| App version | Version of the brain-sync application | `0.6.0` |

These versions must not be conflated.

---

## Brain Format Version

The **Brain Format version** is the version of the portable on-disk
brain structure defined by [`docs/brain/`](brain/README.md) together with the
shared contract docs in this directory.

It governs:

- required filesystem layout
- manifest shapes
- frontmatter identity rules
- managed namespace semantics
- what counts as brain state

For the current supported release:

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

For the current supported release:

- runtime schema label: `v24`
- runtime schema integer in code / `meta.schema_version`: `24`

This runtime schema governs:

- `sync_cache`
- `child_discovery_requests`
- `regen_locks`
- `token_events`
- DB-local metadata used to create or rebuild those tables

The runtime DB may be deleted and rebuilt without invalidating a valid
brain. DB schema versioning therefore remains important for engineering,
but it must not be used as the public definition of "what version of
brain this is".

Supported runtime schema upgrades should migrate user databases in place
unless a compatibility row explicitly says otherwise. Rebuild remains the
recovery path for missing, corrupt, or unsupported runtime DB state, not the
default upgrade strategy.

---

## App Version

The **app version** is the version of the brain-sync application itself.
It should follow semantic versioning.

The canonical source for the app version is `pyproject.toml` under
`[project].version`.

For the current supported release, that value is `0.6.0`.

### App Version Bump Policy

Use app-version increments to communicate user-visible compatibility impact:

- increment **major** for intentional breaking changes to supported public
  contracts such as the Brain Format, supported CLI/MCP behavior, or other
  documented compatibility surfaces that require users to change how they
  upgrade or operate brain-sync
- increment **minor** for backward-compatible feature and architecture changes
  that materially extend the product, including new supported compatibility
  rows such as a runtime DB schema upgrade that preserves user continuity
  across releases
- increment **patch** for backward-compatible bug fixes, doc-only updates,
  small internal refactors, and other changes that do not introduce a new
  supported compatibility row or materially change expected user behavior

If a future packaging tool requires a four-part installer version such as
`0.6.0.0`, treat that as a packaging-derived form of the canonical app
version rather than as the primary version identifier in the spec. Build
metadata policy remains unspecified for now.

---

## Compatibility Expression

Compatibility should always be stated in the form:

`brain-sync <app version> supports Brain Format <format version> with runtime DB schema <db version>`

For the current supported release:

`brain-sync 0.6.0 supports Brain Format 1.0 with runtime DB schema v24`

This means:

- the app can create and operate on Brain Format 1.0 brains
- repair/rebuild flows apply to Brain Format 1.0 brains
- runtime DB state for that release uses the v24 schema

Compatibility details live in [COMPATIBILITY.md](COMPATIBILITY.md).

---

## Testing Implications

Tests should express compatibility in terms of Brain Format version, not
just DB schema version.

Recommended test language:

- "valid Brain Format v1.0 brain"
- "drifted Brain Format v1.0 brain"
- "unsupported pre-v1 legacy brain"
- "runtime DB schema v24 rebuild"

This lets the suite distinguish:

- portable format conformance
- repair of the current supported format
- rejection of unsupported legacy layouts
- runtime cache rebuild behavior

---

## Current Baseline

The current baseline is:

- Brain Format: `1.0`
- Runtime DB schema: `v24`
- App version: `0.6.0`

Pre-Brain Format `1.0` development layouts are not part of Brain Format `1.0`. They are
legacy internal layouts, not supported portable versions.

`0.5.0` with runtime DB schema `v23` was the clean-break release that
established the current portable format baseline. During the current
transition, that row remains a supported upgrade source. `0.6.0` with runtime
DB schema `v24` continues that portable baseline while treating in-place
runtime DB migration as the default expectation for supported upgrades.

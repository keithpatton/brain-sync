# Compatibility

This document defines the supported app-version / Brain Format / runtime DB
schema compatibility rows and the testing expectations that follow from
them.

Version terminology is defined in [VERSIONING.md](VERSIONING.md).

---

## Supported Rows

The current supported rows are:


| App version | Brain Format | Runtime DB schema | Support status              |
| ----------- | ------------ | ----------------- | --------------------------- |
| `0.5.0`     | `1.0`        | `v23`             | Supported as upgrade source |
| `0.6.0`     | `1.0`        | `v25`             | Supported                   |


Canonical compatibility statement:

`brain-sync 0.6.0 supports Brain Format 1.0 with runtime DB schema v25`

Transition statement:

`brain-sync 0.6.0 must accept supported Brain Format 1.0 brains carrying runtime DB schema v23 and migrate that runtime state to v25 in place`

If a packaging layer later emits a four-part installer version such as
`0.6.0.0`, that installer build still maps to the same canonical app
version `0.6.0` unless the packaging policy says otherwise.

---

## Implementation Import Paths

This compatibility document governs app-version, Brain Format, and runtime
schema support. It does not preserve temporary internal Python import aliases.

Canonical subsystem packages under `application/`, `interfaces/`, `brain/`,
`runtime/`, `sync/`, `regen/`, `query/`, `sources/`, `llm/`, and `util/` are
the supported Python import homes. Transitional root-module and legacy package
aliases from the ontology migration are not supported compatibility surfaces.

---

## Supported Operations

For the supported rows above, brain-sync must support:

- creating a fresh Brain Format `1.0` brain via `brain-sync init`
- operating on an existing valid Brain Format `1.0` brain
- repairing repairable drift in a Brain Format `1.0` brain via doctor
and rebuild flows
- opening Brain Format `1.0` brains whose machine-local runtime DB is still on
supported upgrade-source schemas such as `v23`
- migrating supported runtime DB versions in place during app upgrades
- recovering by rebuilding runtime DB state when it is missing, corrupt,
or on an unsupported schema without changing portable brain state

This support applies to brains already in Brain Format `1.0`.

---

## Unsupported Legacy Inputs

Pre-Brain Format `1.0` development layouts are **not** supported upgrade
targets for the supported rows above.

This means:

- they are not considered Brain Format `1.0`
- `doctor --fix` is not a legacy layout conversion tool in this release
- users with pre-Brain Format `1.0` development brains must re-initialise into a fresh
Brain Format `1.0` brain

The product may later introduce format-to-format upgrade guarantees, but
that is outside the initial Brain Format `1.0` support baseline.

---

## Compatibility Test Obligations

Every supported compatibility row or transition row must have tests that
prove:

1. Fresh init creates a conforming brain of the supported Brain Format.
2. A drifted supported-format brain can be repaired without loss of user
  knowledge.
3. Supported runtime DB versions migrate in place without unnecessarily
  discarding machine-local user state.
4. Runtime DB deletion and rebuild do not invalidate the supported
  Brain Format.
5. Unsupported legacy layouts are detected clearly and are not silently
  treated as supported-format brains.

For the current supported rows, this means tests should cover:

- fresh Brain Format `1.0` conformance
- Brain Format `1.0` drift repair
- runtime DB `v23` to `v25` in-place migration
- Brain Format `1.0` runtime rebuild
- unsupported pre-Brain Format `1.0` legacy detection / re-init guidance

---

## Recommended Test Structure

The suite should move toward version-aware builders and compatibility
contracts.

Recommended primitives:

- `build_brain_v1(root, scenario=...)`
- `build_drifted_brain_v1(root, drift=...)`
- `build_legacy_pre_v1_brain(root, scenario=...)`
- `assert_brain_format_v1(root)`
- `assert_runtime_schema_migrates(root, from_version=..., to_version=...)`
- `assert_runtime_rebuildable(root)`
- `assert_unsupported_legacy_brain(root)`

Recommended placement:

- implementation tests remain in `tests/unit`, `tests/integration`,
`tests/system`, `tests/e2e`
- compatibility contract tests live in a dedicated suite such as
`tests/compat`

This keeps "does this module behave correctly?" separate from "what
portable brain formats does this release support?"

For the current transition, it also answers "which earlier supported rows must
still upgrade cleanly into the current row?"

---

## Future Evolution

When a future Brain Format `2.0` exists, this document should be updated
to add new compatibility rows, for example:


| App version | Brain Format | Runtime DB schema | Support status                                   |
| ----------- | ------------ | ----------------- | ------------------------------------------------ |
| `0.x.y`     | `1.0`        | `...`             | Supported / Deprecated / Read-only / Unsupported |
| `0.x.y`     | `2.0`        | `...`             | Supported                                        |


At that point, compatibility tests should expand to include:

- creation of new-format brains
- repair of current-format brains
- format-to-format upgrade flows, if supported
- explicit policy for deprecated or read-only legacy formats

---

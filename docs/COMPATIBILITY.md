# Compatibility

This document defines the supported compatibility baseline for the first
supportable brain-sync release and the testing expectations that follow
from it.

Version terminology is defined in [VERSIONING.md](VERSIONING.md).

---

## Supported Baseline

The first supportable release baseline is:

| App version | Brain Format | Runtime DB schema | Support status |
|---|---|---|---|
| `0.5.0` | `1.0` | `v23` | Supported |

Canonical compatibility statement:

`brain-sync 0.5.0 supports Brain Format 1.0 with runtime DB schema v23`

If a packaging layer later emits a four-part installer version such as
`0.5.0.0`, that installer build still maps to the same canonical app
version `0.5.0` unless the packaging policy says otherwise.

---

## Supported Operations

For the supported baseline above, brain-sync must support:

- creating a fresh Brain Format `1.0` brain via `brain-sync init`
- operating on an existing valid Brain Format `1.0` brain
- repairing repairable drift in a Brain Format `1.0` brain via doctor
  and rebuild flows
- deleting and rebuilding runtime DB state without changing portable
  brain state

This support applies to brains already in Brain Format `1.0`.

---

## Unsupported Legacy Inputs

Pre-Brain Format `1.0` development layouts are **not** supported upgrade targets for
the first supportable release.

This means:

- they are not considered Brain Format `1.0`
- `doctor --fix` is not a legacy layout conversion tool in this release
- users with pre-Brain Format `1.0` development brains must re-initialise into a fresh
  Brain Format `1.0` brain

The product may later introduce format-to-format upgrade guarantees, but
that is outside the initial Brain Format `1.0` support baseline.

---

## Compatibility Test Obligations

Every supported compatibility row must have tests that prove:

1. Fresh init creates a conforming brain of the supported Brain Format.
2. A drifted supported-format brain can be repaired without loss of user
   knowledge.
3. Runtime DB deletion and rebuild do not invalidate the supported
   Brain Format.
4. Unsupported legacy layouts are detected clearly and are not silently
   treated as supported-format brains.

For the initial baseline, this means tests should cover:

- fresh Brain Format `1.0` conformance
- Brain Format `1.0` drift repair
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
- `assert_runtime_rebuildable(root)`
- `assert_unsupported_legacy_brain(root)`

Recommended placement:

- implementation tests remain in `tests/unit`, `tests/integration`,
  `tests/system`, `tests/e2e`
- compatibility contract tests live in a dedicated suite such as
  `tests/compat`

This keeps "does this module behave correctly?" separate from "what
portable brain formats does this release support?"

---

## Future Evolution

When a future Brain Format `2.0` exists, this document should be updated
to add new compatibility rows, for example:

| App version | Brain Format | Runtime DB schema | Support status |
|---|---|---|---|
| `0.x.y` | `1.0` | `...` | Supported / Deprecated / Read-only / Unsupported |
| `0.x.y` | `2.0` | `...` | Supported |

At that point, compatibility tests should expand to include:

- creation of new-format brains
- repair of current-format brains
- format-to-format upgrade flows, if supported
- explicit policy for deprecated or read-only legacy formats

---

## Current Product Direction

For the current support baseline:

- Brain Format `1.0` is the first supportable portable format
- runtime DB schema `v23` is the first supportable runtime cache schema
  aligned to that format
- app version `0.5.0` is the intended first supportable release line

That gives brain-sync a clean baseline from which future supported
upgrades can be defined explicitly instead of being inferred from
internal migrations.

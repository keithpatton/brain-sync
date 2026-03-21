# Compatibility

This document defines the supported compatibility rows for the current release.

Version terminology is defined in [VERSIONING.md](VERSIONING.md).

---

## Supported Rows

| App version | Brain Format | Runtime DB schema | Status |
|---|---|---|---|
| `0.5.0` | `1.0` | `v23` | Supported upgrade source |
| `0.7.0.0` | `1.2` | `v29` | Current supported row |

Canonical compatibility statement:

`brain-sync 0.7.0.0 supports Brain Format 1.2 with runtime DB schema v29`

Transition guarantees for the current row:

- supported `0.5.0` brains on Brain Format `1.0` / runtime schema `v23` may be
  upgraded to Brain Format `1.2` / runtime schema `v29` using the guided
  migration path
- supported runtime DB schemas `v23`, `v24`, `v25`, `v26`, and `v27` must
  migrate in place to `v29`
- the unreleased interim runtime schema `v28` must migrate in place to `v29`
  before use; it is not itself a released compatibility row
- deleting or rebuilding the runtime DB must not change durable source truth in
  the portable manifest
- portable `knowledge_state = stale` must still force full rematerialization
  even when the stored `remote_fingerprint` matches the remote source

---

## Supported Operations

For the current row, brain-sync must support:

- fresh init of a conforming Brain Format `1.2` brain
- normal operation on valid Brain Format `1.2` brains
- doctor/rebuild flows that preserve portable source truth
- guided migration from `0.5.0` / Brain Format `1.0` / runtime schema `v23`
  to `0.7.0.0` / Brain Format `1.2` / runtime schema `v29`
- in-place migration from supported runtime DB schemas to `v29`
- cross-machine continuation from portable manifest truth even when runtime DB
  state differs per machine

---

## Unsupported Inputs

The following are not supported compatibility surfaces:

- pre-Brain Format `1.0` development layouts
- Brain Format `1.1` as a steady-state supported compatibility row
- provisional runtime DB shapes that do not match a supported schema row
- ad hoc manifest mixes that combine retired Brain Format `1.1` portable
  missing-timestamp fields with Brain Format `1.2` fields

Unsupported runtime DB state may be rebuilt. Unsupported portable brain state
requires explicit migration or re-initialization rather than silent coercion.

---

## Compatibility Test Obligations

The suite should prove:

1. fresh Brain Format `1.2` init
2. `0.5.0` / Brain Format `1.0` / runtime schema `v23` ->
   `0.7.0.0` / Brain Format `1.2` / runtime schema `v29` guided migration expectations
3. runtime DB `v23/v24/v25/v26/v27 -> v29` in-place migration
4. unreleased runtime DB `v28 -> v29` in-place migration when encountered
5. runtime DB rebuild without durable source-truth loss
6. cross-machine continuation from shared manifest state

Current compatibility-focused coverage should include:

- registration writing `knowledge_state = awaiting`
- successful materialization writing `knowledge_state = materialized`
- moved or rediscovered files writing `knowledge_state = stale`
- durable `missing` holding-state behavior with machine-local missing-observation history
- `stale` forcing full rematerialization even when `remote_fingerprint` matches
- administrative listing returning missing registered sources with
  `knowledge_state`

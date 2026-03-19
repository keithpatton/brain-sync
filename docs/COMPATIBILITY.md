# Compatibility

This document defines the supported compatibility rows for the current release.

Version terminology is defined in [VERSIONING.md](VERSIONING.md).

---

## Supported Rows

| App version | Brain Format | Runtime DB schema | Status |
|---|---|---|---|
| `0.5.0` | `1.0` | `v23` | Supported upgrade source |
| `0.6.0` | `1.1` | `v26` | Current supported row |

Canonical compatibility statement:

`brain-sync 0.6.0 supports Brain Format 1.1 with runtime DB schema v26`

Transition guarantees for this row:

- supported Brain Format `1.0` brains may be upgraded to Brain Format `1.1`
  using the guided portable migration
- supported runtime DB schemas `v23`, `v24`, and `v25` must migrate in place
  to `v26`
- deleting or rebuilding the runtime DB must not change durable source truth in
  the portable manifest

---

## Supported Operations

For the current row, brain-sync must support:

- fresh init of a conforming Brain Format `1.1` brain
- normal operation on valid Brain Format `1.1` brains
- doctor/rebuild flows that preserve portable source truth
- guided migration from Brain Format `1.0` to `1.1`
- in-place migration from supported runtime DB schemas to `v26`
- cross-machine continuation from portable manifest truth even when runtime DB
  state differs per machine

---

## Unsupported Inputs

The following are not supported compatibility surfaces:

- pre-Brain Format `1.0` development layouts
- provisional runtime DB shapes that do not match a supported schema row
- ad hoc manifest mixes that combine retired Brain Format `1.0` source fields
  with Brain Format `1.1` fields

Unsupported runtime DB state may be rebuilt. Unsupported portable brain state
requires explicit migration or re-initialization rather than silent coercion.

---

## Compatibility Test Obligations

The suite should prove:

1. fresh Brain Format `1.1` init
2. Brain Format `1.0 -> 1.1` guided migration expectations
3. runtime DB `v23/v24/v25 -> v26` in-place migration
4. runtime DB rebuild without durable source-truth loss
5. cross-machine continuation from shared manifest state

Current compatibility-focused coverage should include:

- registration writing `knowledge_state = awaiting`
- successful materialization writing `knowledge_state = materialized`
- moved or rediscovered files writing `knowledge_state = stale`
- two-stage `missing` lifecycle behavior
- `stale` forcing full rematerialization even when `remote_fingerprint` matches

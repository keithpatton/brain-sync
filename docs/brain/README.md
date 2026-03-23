# Brain Reference

This directory is the authoritative reference for the portable brain state
managed by brain-sync.

Brain Format `1.2` is the current outward-facing version of the portable
brain's filesystem/schema contract. It determines compatibility and migration
expectations for durable on-disk state such as portable layout, manifests,
sidecars, frontmatter, reserved namespaces, and portable/runtime ownership
boundaries.

It does not currently version regen prompt resources or packaged summary and
journal templates as such. Those belong to the regen prompt contract and are
tracked by prompt version unless they change the portable on-disk contract
itself.

## Reference Set

| Document | Purpose |
|---|---|
| [`SCHEMAS.md`](./SCHEMAS.md) | Portable brain manifests, sidecars, and frontmatter |
| [`TEMPLATES.md`](./TEMPLATES.md) | Normative generated artifact shapes instantiated in the brain |
| [`../RULES.md`](../RULES.md) | Cross-cutting state authority, mutation, and reconciliation rules |
| [`../GLOSSARY.md`](../GLOSSARY.md) | Shared vocabulary for brain, runtime, and compatibility terms |
| [`../VERSIONING.md`](../VERSIONING.md) | Brain version, runtime DB schema version, and app version model |
| [`../COMPATIBILITY.md`](../COMPATIBILITY.md) | Supported app/brain/runtime compatibility rows |

## Scope

Use this directory for questions about:

- what counts as portable brain state
- which on-disk brain documents exist and where they live
- which generated artifacts are normative instances inside the brain
- what the current brain version means
- which source lifecycle facts are portable versus machine-local

At a high level, Brain Format covers the portable brain contract:

- directory and path layout inside the brain root
- durable manifest and sidecar fields
- frontmatter identity and durable ownership rules
- reserved managed namespaces
- what is portable brain state versus runtime-only state

It does not currently cover implementation-only regen prompt changes or
packaged template wording changes unless those changes alter the portable
artifact contract on disk.

Brain Format `1.2` keeps source identity, placement, lifecycle state, and
last-successful materialization baseline in portable manifests, while leaving
missing-observation timing and explicit-finalization coordination in machine-
local runtime state. A source in portable `knowledge_state = missing` remains
registered until it is either rediscovered or explicitly finalized.

Do not use this directory for runtime-only machine-local files or application
architecture rationale. Those live in [`docs/runtime/`](../runtime/README.md)
and [`docs/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md).

For normative code-boundary and state-authority rules that span both portable
and runtime planes, see [`../RULES.md`](../RULES.md).

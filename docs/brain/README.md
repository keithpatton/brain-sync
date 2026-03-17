# Brain Reference

This directory is the authoritative reference for the portable brain state
managed by brain-sync.

Brain Format `1.0` is the current outward-facing version of the portable
brain. It determines compatibility and migration expectations for durable
on-disk state.

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

Do not use this directory for runtime-only machine-local files or application
architecture rationale. Those live in [`docs/runtime/`](../runtime/README.md)
and [`docs/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md).

For normative code-boundary and state-authority rules that span both portable
and runtime planes, see [`../RULES.md`](../RULES.md).

# Brain Format Specification

This directory is the authoritative specification for the portable brain
contract used by brain-sync.

These documents define the on-disk format, versioning model, and compatibility
rules for Brain Format `1.0`. This README is only an index into that spec set.

## Spec Set

| Document | Purpose |
|---|---|
| [`RULES.md`](./RULES.md) | Behavioral invariants and system guarantees for a valid brain |
| [`SCHEMAS.md`](./SCHEMAS.md) | Schema-defined manifests, frontmatter, and runtime DB shape |
| [`VERSIONING.md`](./VERSIONING.md) | Brain Format, runtime DB, and app version model |
| [`COMPATIBILITY.md`](./COMPATIBILITY.md) | Supported compatibility row and legacy handling policy |
| [`GLOSSARY.md`](./GLOSSARY.md) | Shared terminology used across the spec |
| [`TEMPLATES.md`](./TEMPLATES.md) | Regeneration template and packaged-instruction rules |

## Governance

Changes to this specification must be intentional:

- update versioning when the portable contract changes
- update compatibility when support boundaries change
- keep downstream docs aligned rather than redefining rules there

For repository working rules, see [`AGENTS.md`](../../AGENTS.md).

For system design and rationale, see
[`docs/architecture/ARCHITECTURE.md`](../architecture/ARCHITECTURE.md).

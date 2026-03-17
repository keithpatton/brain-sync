# Runtime Reference

This directory is the authoritative reference for machine-local runtime state
used by brain-sync.

Runtime state is not part of the portable brain. It may be deleted and rebuilt
without damaging a valid brain.

## Reference Set

| Document | Purpose |
|---|---|
| [`SCHEMAS.md`](./SCHEMAS.md) | Runtime DB tables, `config.json`, and `daemon.json` |
| [`../RULES.md`](../RULES.md) | Cross-cutting state authority and mutation rules |
| [`../GLOSSARY.md`](../GLOSSARY.md) | Shared vocabulary for brain and runtime terms |
| [`../VERSIONING.md`](../VERSIONING.md) | Brain version, runtime DB schema version, and app version model |
| [`../COMPATIBILITY.md`](../COMPATIBILITY.md) | Supported app/brain/runtime compatibility rows |

## Scope

Use this directory for questions about:

- the machine-local runtime directory under `~/.brain-sync/`
- runtime DB tables and schema versioning
- config and daemon status file shapes
- which runtime artifacts are disposable versus durable

Do not use this directory for portable brain manifests or generated
brain-resident artifacts. Those live in [`docs/brain/`](../brain/README.md).

For normative code-boundary and state-authority rules that span both portable
and runtime planes, see [`../RULES.md`](../RULES.md).

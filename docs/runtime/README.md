# Runtime Reference

This directory is the authoritative reference for machine-local runtime state
used by brain-sync.

Runtime state is not part of the portable brain. It may be deleted and rebuilt
without damaging a valid brain.

When a supported runtime schema migration exists, normal upgrades should
preserve machine-local state in place. Deletion and rebuild are recovery paths,
not the default upgrade strategy.

For the current architecture stage, one runtime config directory owns one
active brain. If `config.json` still contains multiple registered roots, only
the first entry is treated as active runtime state.

That current single-brain runtime model coexists with a config-dir daemon
startup guard: `daemon.json` is the latest daemon status snapshot for the
config directory, while durable startup exclusion for that runtime lives in
`daemon.lock`.

Runtime schema `v29` splits active polling from source lifecycle coordination:

- `sync_polling` is polling-only for actively scheduled registered sources
- `source_lifecycle_runtime` stores machine-local missing-observation
  timestamps plus source-level leases for restart-safe lifecycle coordination;
  explicit finalization now relies on current revalidation instead of
  lifecycle-session freshness

Operational events remain machine-local, append-only diagnostics. They are
best-effort, may duplicate, and are non-authoritative.

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
- which runtime artifacts are authoritative, reconstructable, or expected to
  survive supported upgrades

Do not use this directory for portable brain manifests or generated
brain-resident artifacts. Those live in [`docs/brain/`](../brain/README.md).

For normative code-boundary and state-authority rules that span both portable
and runtime planes, see [`../RULES.md`](../RULES.md).

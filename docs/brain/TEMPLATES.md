# Brain Templates

This document defines the generated artifact templates whose instances live in
the portable brain and shape
[generated meaning](../GLOSSARY.md#generated-meaning).

Templates define the layout of generated content. Each concrete file
written by brain-sync from a template is an instance of that template.
See [../GLOSSARY.md](../GLOSSARY.md) for precise definitions of these terms.

This document is normative for artifact purpose, path patterns, ownership, and
durability rules. The canonical structural templates for generated summary and
journal content live in packaged regen resources and are also fed directly to
prompt assembly at runtime.

Implementation references in this document point at canonical package owners,
not compatibility shims.

---

## Summary

`summary.md` is the primary regenerable semantic summary for a knowledge
area.

It is:

- brain-sync-owned
- regenerable (may be rebuilt at any time)
- the main semantic landing page for queries and navigation

**Path pattern**

```text
knowledge/<area>/.brain-sync/insights/summary.md
```

Examples:

- `knowledge/.brain-sync/insights/summary.md` (root area rollup)
- `knowledge/_core/.brain-sync/insights/summary.md`
- `knowledge/teams/platform/.brain-sync/insights/summary.md`

**Template description**

The summary represents the current semantic understanding of an area. It is
rebuilt from:

- readable files in the area (for leaf areas)
- child area summaries (for parent areas — compression pyramid)
- raw `_core` files when regenerating `_core` itself
- `_core`'s distilled summary when regenerating any other area

It should be concise, stable, and oriented toward quick understanding rather
than document inventory. Summary stability is enforced by a similarity guard
(>0.97 similarity = discard rewrite).

It must also distinguish between:

- grounded signals that are directly supported by the provided area material
- interpretation that joins dots across documents or through `_core` framing

The system should prefer truthful, source-grounded language over polished but
overstated synthesis. Claims about people, roles, approvals, ownership, or
decision authority must be source-backed or explicitly described as unclear.

`_core` provides the user's high-authority top-level framing, but more recent
or more specific direct area evidence may still update factual understanding.
When those pull in different directions, the summary should surface the tension
explicitly rather than silently collapsing it.

**Canonical structure**

See the authoritative runtime-fed summary template:
[templates/insights/summary.md](../../src/brain_sync/regen/resources/templates/insights/summary.md)

**Example instance**

See [brain-example platform summary.md](../../brain-example/knowledge/teams/platform/.brain-sync/insights/summary.md)
for a live instance.

**Current implementation**:
[regen/engine.py](../../src/brain_sync/regen/engine.py),
[INSIGHT_INSTRUCTIONS.md](../../src/brain_sync/regen/resources/INSIGHT_INSTRUCTIONS.md),
[templates/insights/summary.md](../../src/brain_sync/regen/resources/templates/insights/summary.md)

---

## Journal

A journal is an append-only temporal record for a knowledge area.

It captures meaningful changes in understanding, decisions, milestones, or
status. Journals are **not regenerable** — they represent point-in-time
observations and survive all automated cleanup operations.

**Path pattern**

```text
knowledge/<area>/.brain-sync/journal/YYYY-MM/YYYY-MM-DD.md
```

Examples:

- `knowledge/teams/platform/.brain-sync/journal/2026-03/2026-03-15.md`
- `knowledge/.brain-sync/journal/2026-03/2026-03-15.md` (root area)

**Template description**

Journal files are daily logs. Each entry is appended to the day file under a
timestamp heading.

Journal entries should focus on what changed, what was directly observed, and
what interpretation emerged from that change. When an entry includes
interpretation, it should be labelled as such rather than presented as settled
fact.

The runtime owns the day-file path and the `## HH:MM` timestamp heading. The
canonical journal template describes the entry body written beneath that
runtime-added heading.

**Canonical structure**

See the authoritative runtime-fed journal template:
[templates/insights/journal.md](../../src/brain_sync/regen/resources/templates/insights/journal.md)

Entries are chronological and append-only in normal operation.

**Example instance**

See [brain-example platform journal](../../brain-example/knowledge/teams/platform/.brain-sync/journal/2026-03/2026-03-15.md)
for a live instance.

**Current implementation**:
[regen/engine.py](../../src/brain_sync/regen/engine.py),
[templates/insights/journal.md](../../src/brain_sync/regen/resources/templates/insights/journal.md)

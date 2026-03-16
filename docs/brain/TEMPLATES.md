# Brain Templates

This document defines the generated artifact templates whose instances live in
the portable brain and shape
[generated meaning](../GLOSSARY.md#generated-meaning).

Templates define the layout of generated content. Each concrete file
written by brain-sync from a template is an instance of that template.
See [../GLOSSARY.md](../GLOSSARY.md) for precise definitions of these terms.

This document is normative for the brain-resident artifacts that result from
regeneration. The packaged prompt and template source files used to produce
those artifacts are implementation details described by code, not by this
reference.

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

**Example instance**

See [brain-example platform summary.md](../../brain-example/knowledge/teams/platform/.brain-sync/insights/summary.md)
for a live instance. Inline:

```md
# Summary

The platform area combines user-authored notes with a synced Confluence page
about attachment handling. The page demonstrates how synced attachments can
be kept under the area's managed namespace while remaining referenceable
from the materialized markdown.

## Signals

- the source page is tracked through a manifest and in-file identity frontmatter
- attachments are stored under `.brain-sync/attachments/c987654/`
- the user-facing markdown can link to those managed files directly
```

**Current implementation**:
[regen.py](../../src/brain_sync/regen.py),
[INSIGHT_INSTRUCTIONS.md](../../src/brain_sync/instructions/INSIGHT_INSTRUCTIONS.md),
[templates/insights/summary.md](../../src/brain_sync/templates/insights/summary.md)

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

Entry format:

```md
## HH:MM
```

Entries are chronological and append-only in normal operation.

**Example instance**

See [brain-example platform journal](../../brain-example/knowledge/teams/platform/.brain-sync/journal/2026-03/2026-03-15.md)
for a live instance. Inline:

```md
## 08:46

Completed attachment sync for Confluence page `confluence:987654`.

- materialized the source page to `c987654-attachment-handling.md`
- stored the image under `.brain-sync/attachments/c987654/`
- verified the markdown links to the managed attachment path
```

**Current implementation**:
[regen.py](../../src/brain_sync/regen.py)

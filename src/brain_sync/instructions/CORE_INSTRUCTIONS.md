# Brain Instructions

This is a structured second brain managed by brain-sync.

## Folder Structure

```
brain-root/
  knowledge/                         <- ALL human/sync content
    _core/                           <- Global: semantic grounding
    <arbitrary folders>/             <- Initiatives, projects, topics
  insights/                          <- Strict mirror of knowledge/ tree
    _core/                           <- Global: shared understanding
      summary.md                     <- Primary orientation summary
      <other insight files>          <- Additional core artifacts
      journal/                       <- Temporal thinking
        YYYY-MM/
          YYYY-MM-DD.md
    <mirrors knowledge/>/
      summary.md                     <- Area landing page (required)
      <other files>.md               <- Additional insight artifacts
      journal/                       <- Temporal thinking for this area
        YYYY-MM/
          YYYY-MM-DD.md
  schemas/                           <- Global: structural definitions
    insights/                        <- How meaning is surfaced in insights
      summary.md
      decisions.md
      glossary.md
      status.md
```

- `knowledge/` is human-owned. Users and brain-sync write here.
- `insights/` mirrors knowledge/ 1:1. Managed by brain-sync's regen engine.
  Insights are regenerated asynchronously when knowledge changes.
- `schemas/` contains structural definitions. The `insights/` subfolder
  defines how meaning should be surfaced when generating insights.
- `_sync-context/` subfolders contain relationship metadata for synced content.

## Global Context

The brain contains a small set of locations that form global context.
Global context represents the shared semantic foundation of the brain.

| Location | Role |
|---|---|
| `knowledge/_core/` | **Semantic grounding** — foundational knowledge about the brain's world: taxonomy, organisational context, artifact semantics. Helps correctly interpret documents and folders. |
| `schemas/` | **Structural definitions** — contains subfolders that define structure for different concerns. `schemas/insights/` defines how meaning should be surfaced when generating and interpreting insights. |
| `insights/_core/` | **Shared understanding** — global insights derived from core knowledge: summaries, glossaries. Represents the brain's current shared understanding. |

### Ownership and resilience

Global context folders are deployed by `brain-sync init` but are
human-managed — the user may modify, extend, or remove them, just like
the knowledge folder itself.

- If `_core/` or `schemas/` folders are present, use them as global context.
- If any are absent, proceed without them and apply reasonable defaults.
- `schemas/insights/` files define the recommended artifact structures.
  Without them, generate insights using general best practices, but the
  results will be less consistent.

### Rules

- The `_core/` directory is only valid at the top level of `knowledge/`
  and `insights/`. It must not appear elsewhere in the brain hierarchy.
- Schemas are structural definitions, not domain knowledge.

## insights/ Structure

Each knowledge subfolder MAY have a corresponding insights subfolder containing:

- `summary.md` — the required landing page for the area. Loaded first.
  See `schemas/insights/summary.md` for the recommended structure.
- Additional insight files alongside summary.md: diagrams, models, analysis.
  See `schemas/insights/` for other available artifact types.
  Referenced from summary.md so they are discoverable.
- `journal/YYYY-MM/YYYY-MM-DD.md` — temporal thinking log for the area.

## Conventions

- Use ISO dates: `YYYY-MM-DD`
- Journal entries: prefix with `## YYYY-MM-DD` headings
- When recording thoughts in journals, distinguish between facts,
  interpretations, and open questions
- Keep journal entries concise: working scratchpad, not prose

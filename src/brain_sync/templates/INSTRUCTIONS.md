# Brain Instructions

This is a structured second brain managed by brain-sync.

## Folder Structure

```
brain-root/
  INSTRUCTIONS.md                    <- This file
  knowledge/                         <- ALL human/sync content
    _core/                           <- Reference material (identity, org)
    <arbitrary folders>/             <- Initiatives, projects, topics
  insights/                          <- Strict mirror of knowledge/ tree
    _core/                           <- Core orientation (always load)
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
```

- `knowledge/` is human-owned. Users and brain-sync write here.
- `insights/` mirrors knowledge/ 1:1. Managed by brain-sync's regen engine.
  Insights are regenerated asynchronously when knowledge changes.
- `knowledge/_core/` contains always-loaded reference material.
- `_sync-context/` subfolders contain relationship metadata for synced content.

## insights/ Structure

Each knowledge subfolder MAY have a corresponding insights subfolder containing:

- `summary.md` — the required landing page for the area. Loaded first.
- Additional insight files alongside summary.md: diagrams, models, analysis.
  Referenced from summary.md so they are discoverable.
- `journal/YYYY-MM/YYYY-MM-DD.md` — temporal thinking log for the area.

## Summary Template (`summary.md`)

Used at every level. Rewritten (not appended) as understanding deepens.
Should answer: "What do I need to know right now?"

```markdown
# [Name] - Current State Summary

*Last updated: YYYY-MM-DD*

## What This Is
Brief explanation of scope.

## Why It Matters
Business context, strategic importance.

## Architecture / Design
Key decisions, components, patterns.

## Status
Current phase, blockers, what's deferred.

## Key Entities / Concepts
Domain model, boundaries, ownership.

## Key People
Who is involved, their roles.

## Key Insights
Succinct analytical opinions. Signal from noise.

## Risks and Concerns
Concrete, specific risks with context.

## Open Questions
Unresolved questions that need answers.
```

Middle sections adapt per context — omit sections that don't apply.
**Key Insights**, **Risks and Concerns**, and **Open Questions** are mandatory.

## Conventions

- Use ISO dates: `YYYY-MM-DD`
- Journal entries: prefix with `## YYYY-MM-DD` headings
- When recording thoughts in journals, distinguish between facts,
  interpretations, and open questions
- Keep journal entries concise: working scratchpad, not prose

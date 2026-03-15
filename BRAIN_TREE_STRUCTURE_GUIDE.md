# Brain Tree Structure Guide

This guide captures a reusable brain structure pattern that other people can
adapt to their own brains.

It is intentionally generic. The goal is not to copy exact folder names, but
to copy the shape of the system and the reasoning behind it.

## Top Tips

- Start small. You do not need to design the whole tree up front.
- Keep folders reasonably sized. A good rule of thumb is roughly 5-7 files in
  a knowledge area before you consider splitting it into sub-areas.
- Remember that the unit of knowledge compression and meaning generation is the
  folder. If one folder contains too much mixed material, the summary gets less
  precise and regen gets more expensive.
- `brain-sync run` works well as an on-demand daemon. You do not need to keep
  it running all the time if you want to control token burn. Start it when you
  need it, let it pick up changes, and stop it when you are done.

## Design Goals

A good brain tree should:

- separate durable reference knowledge from active work
- make it obvious where a new note should go
- support both manually written notes and synced external sources
- scale from a few areas to hundreds of documents without becoming flat chaos
- let summaries roll up naturally from leaf areas to parent areas

The structure is strong because it combines:

- a small number of stable top-level buckets
- clear distinctions between long-lived knowledge and active initiative work
- area-local summaries and attachments
- mixed source types inside the same conceptual area

## Recommended Top-Level Structure

Use four top-level buckets under `knowledge/`:

```text
knowledge/
  _core/
  initiatives/
  organisation/
  teams/
```

### `_core/`

Use `_core/` for context that should shape how the whole brain is interpreted.

Typical contents:

- personal profile and working style
- role context
- organisation context
- taxonomy or naming rules

Suggested example:

```text
_core/
  taxonomy.md
  Me/
    about-me.md
    role-context.md
  Organisation/
    org-context.md
```

### `initiatives/`

Use `initiatives/` for active projects, programs, product bets, major technical
streams, and time-bounded bodies of work.

Typical contents:

- PRDs
- ERDs
- design documents
- whiteboards
- meetings
- gap analyses
- supporting notes

Suggested shape:

```text
initiatives/
  Initiative A/
    project-instructions.md
    meetings/
      20260316.md
    whiteboards/
      system-map.png
      flow-notes.csv
    PRD Feature X/
      source-doc.md
    ERD Service Y/
      design-doc.md
      supporting/
        tradeoffs.md
        implementation-notes.md
```

### `organisation/`

Use `organisation/` for durable company-wide or cross-cutting reference
material.

Typical contents:

- communication norms
- operating models
- lifecycle or process documentation
- templates
- guidance and glossaries

Suggested shape:

```text
organisation/
  communication/
    naming-conventions.md
    channel-guide.md
  playbook/
    operating-model.md
    principles.md
  product-development-lifecycle/
    lifecycle.md
    engineering-templates/
      template.md
      additional-guidance/
        glossary.md
        stakeholder-guide.md
    product-templates/
      template.md
```

### `teams/`

Use `teams/` for team-local operating knowledge that is important, but not
organisation-wide and not specific to a single initiative.

Typical contents:

- team operating structure
- weekly reports
- delivery cadences
- team tenets

Suggested shape:

```text
teams/
  Team A/
    operating-structure.md
    tenets.md
  Team B/
    delivery/
      weekly-reports/
        weekly-report.md
```

## The Key Pattern: Concept First, Source Second

One of the most useful patterns is that folders are organized by conceptual
area, not by source system.

That means:

- put documents about the same topic together even if they came from different places
- allow synced files, local notes, meeting notes, and whiteboards to coexist in one area
- avoid trees like `confluence/`, `google-docs/`, or `miro/` at the top level

Good:

```text
initiatives/
  Initiative A/
    PRD Feature X/
      local-notes.md
      g123-feature-prd.md
      c456-design-discussion.md
```

Less helpful:

```text
knowledge/
  confluence/
  google-docs/
  local-files/
```

The first structure makes it much easier for summaries to represent the topic
rather than the storage system.

## A Practical Depth Model

This kind of brain tends to work well with a depth of 2-4 levels below the
top-level bucket.

A useful mental model is:

```text
bucket -> domain or initiative -> sub-area -> artifact cluster
```

Examples:

- `organisation -> lifecycle -> templates -> guidance`
- `initiatives -> initiative -> workstream -> meetings`
- `teams -> team -> function -> cadence bucket`

Try to avoid:

- very flat trees with dozens of siblings in one folder
- very deep trees where every document sits 6-8 levels down

## Folder Size Guidance

Because summaries and regen operate at the folder level, folder size matters.

A good rule of thumb:

- 1-3 files: excellent, very crisp area summary
- 4-7 files: still healthy for most areas
- 8+ files: usually a sign that the folder wants one or more child areas

Common split patterns:

- break meetings into `meetings/`
- break design work into named PRD or ERD sub-areas
- move supporting material into `supporting/` or `additional-guidance/`
- split by workstream if one initiative folder is doing too many jobs

The goal is not an exact file count. The goal is keeping each folder about one
coherent topic.

## Recommended Folder Types Inside an Area

These recurring subfolders work well:

- `meetings/`
- `whiteboards/`
- `weekly-reports/`
- `additional-guidance/`
- `supporting/`
- named artifact areas like `PRD <name>/` or `ERD <name>/`

These are useful because they answer common retrieval questions:

- "What did we discuss?"
- "What designs exist here?"
- "What supporting context sits under this doc?"
- "What changed over time?"

## How to Mix Local Notes and Synced Sources

A strong pattern is to let local files and synced files live in the same area.

For example, an area might contain:

- a synced design doc
- a synced product doc
- a manually written note
- a meeting note
- a whiteboard export

That works well because the area summary can synthesize the whole topic instead
of forcing each source type into its own silo.

Rule of thumb:

- use local files for interpretation, notes, and lightweight working documents
- use synced files for source-of-truth material from external systems
- keep them together if they describe the same concept

## Date-Based Folders

Date-based folders are most useful for recurring material, not for everything.

Good uses:

- meeting notes
- weekly reports
- temporary work packets

Suggested patterns:

```text
meetings/
  20260316.md

weekly-reports/
  2026-03-16-weekly-report.md

decisions/
  2026-03/
    2026-03-16.md
```

Avoid making the entire tree date-based. Dates are great for cadence material,
but poor as the main navigation system for durable knowledge.

## How Summaries and Attachments Should Fit

Each knowledge area can carry its managed state beside the content:

```text
Some Area/
  source-doc.md
  local-note.md
  .brain-sync/
    insights/
      summary.md
      insight-state.json
    attachments/
      <source-id>/
```

This is valuable because:

- the summary stays with the area it describes
- attachments stay with the source they came from
- moving an area moves its managed state with it

People adopting this pattern should treat `.brain-sync/` as reserved and avoid
adding their own notes there.

## Placement Rules That Work Well

When deciding where a new document belongs, use this order:

1. Does it describe me, my preferences, or the shared vocabulary of the brain?
   Put it in `_core/`.
2. Is it durable company or cross-org reference material?
   Put it in `organisation/`.
3. Is it about a team's operating model or recurring delivery rhythm?
   Put it in `teams/`.
4. Is it tied to a concrete project, stream, or active body of work?
   Put it in `initiatives/`.

Then ask:

1. Is it a top-level area, a sub-area, or a supporting artifact?
2. Does it deserve its own folder because it will accumulate notes, meetings, or attachments?
3. Is it one-off enough to remain a single file in the parent area?

## A Reusable Template

This is a good starting tree for most people:

```text
knowledge/
  _core/
    taxonomy.md
    Me/
      about-me.md
      role-context.md
    Organisation/
      organisation-context.md

  initiatives/
    Initiative A/
      project-instructions.md
      meetings/
        20260316.md
      whiteboards/
        system-map.png
      PRD Feature X/
        feature-prd.md
      ERD Service Y/
        service-design.md
        supporting/
          implementation-notes.md

  organisation/
    communication/
      naming-conventions.md
    playbook/
      operating-model.md
    product-development-lifecycle/
      lifecycle.md
      engineering-templates/
        template.md
        additional-guidance/
          glossary.md
      product-templates/
        template.md

  teams/
    Team A/
      operating-structure.md
    Team B/
      delivery/
        weekly-reports/
          2026-03-16-weekly-report.md
```

## What Makes This Structure Shareable

This structure is portable because it uses a few broad ideas that apply to many
brains:

- identity and context at `_core/`
- active work in `initiatives/`
- durable reference in `organisation/`
- team-local operating knowledge in `teams/`
- conceptual grouping before source-system grouping
- stable area names with recurring sub-area patterns

It should work well for:

- personal work brains
- leadership brains
- engineering/product brains
- consulting or client knowledge bases
- founder and operator brains

## Suggested Adoption Path

If someone wants to apply this to their own brain, a good rollout path is:

1. Create the four top-level buckets.
2. Move a handful of current notes into the bucket they naturally belong to.
3. Create one or two initiative areas and one or two organisation areas.
4. Add recurring subfolders only where they genuinely recur.
5. Split folders only when they stop producing crisp summaries.

The best version of this structure is not the most elaborate one. It is the one
that makes new information easy to place and old information easy to rediscover.

# PLAN_docs-upgrade — Documentation Governance Migration

## Context

brain-sync documentation has grown organically across CLAUDE.md, ARCHITECTURE.md, README.md, and docs/brain-format/. Three problems have emerged:

1. **Agent-specific naming** — CLAUDE.md is Claude Code specific; the project now uses Codex too and needs agent-agnostic AGENTS.md
2. **No documentation governance** — agents don't know what belongs where, leading to duplication that grows weeds over time
3. **brain-format isolation** — the authoritative spec set has zero inbound links from CLAUDE.md, ARCHITECTURE.md, or README.md
4. **Duplication** — three topics (state authority, module deps, adapter pattern) appear in both CLAUDE.md and ARCHITECTURE.md at different detail levels

The goal: clear governance so every agent knows what each document is for, where to write, and how to maintain separation of concerns.

---

## Documentation Authority Hierarchy

```
docs/brain-format/  >  docs/architecture/  >  AGENTS.md  >  README.md
(specification)        (understanding)         (practice)     (user guide)
```

Nothing downstream may conflict with anything upstream.

---

## Changes

### 1. Create `AGENTS.md` (new file, repo root)

Content structure, top to bottom:

**1a. Documentation Governance** (new, replaces CLAUDE.md "Governance" section lines 263-274)

Table defining the four doc layers with purpose, audience, and governance rules:
- `docs/brain-format/` — specification and rulebook, authoritative source of truth
- `docs/architecture/` — thinking and reflection, conceptual, explanatory
- `AGENTS.md` — doing things right: coding, testing, git, privacy, engineering
- `README.md` — user guide: install, CLI, config, usage

Rules: what goes where, what triggers updates to each doc, "when in doubt prefer the most specific document."

**1b. Brain Format Contract** (new section)

- Lists the 6 brain-format docs and their roles
- "Before making format-breaking changes" checklist: check RULES.md, flag conflicts, propose version bump per VERSIONING.md, update COMPATIBILITY.md
- Statement: brain-format is highest-authority for format questions

**1c. Source Code Hygiene** — migrated verbatim from CLAUDE.md lines 7-50

**1d. Engineering Conventions / Tooling** — migrated verbatim from CLAUDE.md lines 53-68

**1e. Testing** — migrated verbatim from CLAUDE.md lines 72-195 (all subsections: tiers, running, xdist, LLM backend, E2E harness, isolation, adding tests, failure classification)

**1f. State Authority** (DEDUPLICATED)

Replace CLAUDE.md lines 199-205 with:
- 2-sentence actionable rule: "disk before DB on all mutations" + "manifest.py and sidecar.py are canonical"
- Pointer: `See docs/architecture/ARCHITECTURE.md §2.5 for the full authority model`

**1g. Module Dependency Rule** (DEDUPLICATED)

Replace CLAUDE.md lines 209-233 with:
- 1-sentence rule: "core/library modules must not import from CLI, commands, or entrypoints"
- Pointer: `See docs/architecture/ARCHITECTURE.md §1 for the full module structure`

**1h. Source Adapter Architecture** (DEDUPLICATED)

Replace CLAUDE.md lines 237-246 with:
- 2-sentence rule: "source-specific logic only in adapters under sources/<type>/; shared modules must be source-type-agnostic"
- Pointer: `See docs/architecture/ARCHITECTURE.md Source Adapter Pattern for the full design`

**1i. Architecture update trigger** — folded into the governance section (1a), not duplicated as a standalone section

### 2. Replace `CLAUDE.md` (existing file)

Replace entire contents with:

```markdown
@AGENTS.md
```

Claude Code's file-include syntax loads AGENTS.md. Codex reads AGENTS.md directly via OOTB support.

### 3. Create `docs/brain-format/README.md` (new file)

Short entry point:
- Title: "Brain Format Specification"
- 1-2 sentence description: authoritative spec for the portable brain contract
- Table of the 6 documents with one-line purpose each
- Governance note: changes require versioning per VERSIONING.md, links to AGENTS.md Brain Format Contract section
- "Referenced by" links to AGENTS.md and ARCHITECTURE.md

### 4. Minimal edit to `docs/architecture/ARCHITECTURE.md`

Line 34 currently reads: `Dependency direction rules are defined in \`CLAUDE.md\`.`

Update to: `Dependency direction rules are defined in \`AGENTS.md\`. The brain format specification is at \`docs/brain-format/\`.`

No other content changes to ARCHITECTURE.md.

---

### 5. Copy plan to project planning trail

Copy this plan to `docs/plans/PLAN_docs-upgrade.md` following the project's planning convention.

---

## Files

| File | Action |
|---|---|
| `AGENTS.md` | Create |
| `CLAUDE.md` | Replace (thin pointer) |
| `docs/brain-format/README.md` | Create |
| `docs/architecture/ARCHITECTURE.md` | Edit line 34 only |
| `docs/plans/PLAN_docs-upgrade.md` | Create (plan trail) |

---

## Deduplication Summary

| Topic | AGENTS.md (after) | ARCHITECTURE.md (unchanged) |
|---|---|---|
| State Authority | 2-sentence rule + link | Full model §2.5 (lines 138-235) |
| Module Dependencies | 1-sentence rule + link | Full module table §1 (lines 12-35) |
| Source Adapters | 2-sentence rule + link | Full pattern (lines 115-134) |

---

## Verification

1. **Nothing lost** — walk every section of old CLAUDE.md, confirm it appears in AGENTS.md or is covered by an ARCHITECTURE.md pointer
2. **No contradictions** — brief rules in AGENTS.md align with ARCHITECTURE.md detail (especially state authority invariant 7 "manifest-first writes")
3. **Links resolve** — all markdown cross-references between AGENTS.md, ARCHITECTURE.md, brain-format/ work
4. **Claude Code loads** — start Claude Code in repo, verify it loads AGENTS.md via `@AGENTS.md` in CLAUDE.md
5. **brain-format reachable** — confirm inbound links from both AGENTS.md and ARCHITECTURE.md
6. **Governance self-documenting** — the governance table makes it unambiguous where each content type belongs
7. **Codex compatible** — AGENTS.md at repo root, standard markdown, no Claude-specific syntax

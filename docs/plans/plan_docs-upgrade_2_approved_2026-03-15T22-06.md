# plan_docs-upgrade_2 — Documentation Governance Migration (Revised)

Revision addressing review feedback in `plan_docs-upgrade_review_1_2026-03-15.md`.

---

## Context

brain-sync documentation has grown organically across CLAUDE.md, ARCHITECTURE.md, README.md, and docs/brain-format/. The v23 code refactor has landed and the test suite is green, but the core docs still describe pre-v23 behavior. This creates two problems:

1. **Agent alignment** — CLAUDE.md is Claude-specific; the project now uses Codex too and needs agent-agnostic AGENTS.md with clear governance
2. **Stale high-authority docs** — ARCHITECTURE.md and README.md still describe the old layout, old DB tables, old identity format, and old attachment paths. Agents reading these docs will make wrong decisions.

The goal is both: a neutral agent entrypoint with clear governance, AND correction of stale docs that shape agent and user decisions.

---

## Prerequisites

Execution should begin from a committed v23 code checkpoint. The docs pass is a separate follow-up change, not mixed into the product refactor.

---

## Documentation Authority Hierarchy

```
docs/brain-format/  >  docs/architecture/  >  AGENTS.md  >  README.md
(specification)        (understanding)         (practice)     (user guide)
```

Nothing downstream may conflict with anything upstream.

### Document Boundaries (Diataxis)

| Document | Content Mode | Must Contain | Must NOT Contain |
|---|---|---|---|
| `docs/brain-format/` | Reference / Specification | Invariants, schemas, format contract, versioning | Procedural guidance, architecture rationale, tutorials |
| `docs/architecture/` | Explanation | System design, module responsibilities, state models, rationale, technical debt | On-disk schema definitions (defer to brain-format), procedural rules, user-facing how-tos |
| `AGENTS.md` | Operational rules | Coding standards, test commands, git hygiene, privacy rules, practical constraints | Architecture explanation, format spec detail, user tutorials |
| `README.md` | Tutorial / How-to | Install, configure, use, update — task-oriented user guidance | Architecture internals, state models, format spec detail |

When in doubt, prefer the most specific document.

---

## Changes

### 1. Create `AGENTS.md` (new file, repo root)

Content structure, top to bottom:

**1a. Documentation Governance** (new, replaces CLAUDE.md "Governance" section)

- Authority hierarchy table (4 layers with purpose, audience, content mode)
- Document boundary rules (what must / must not appear in each layer)
- Update triggers: what changes require updates to which doc
- "When in doubt prefer the most specific document"

**1b. Brain Format Contract** (new section)

- Lists the 6 brain-format docs and their roles
- "Before making format-breaking changes" checklist: check RULES.md, flag conflicts, propose version bump per VERSIONING.md, update COMPATIBILITY.md
- Statement: brain-format is highest-authority for format questions

**1c. Source Code Hygiene** — migrated verbatim from CLAUDE.md (no PII, placeholders, test fixtures)

**1d. Engineering Conventions / Tooling** — migrated verbatim (Python 3.11+, ruff, pyright, line length 120, pre-commit commands)

**1e. Testing** — migrated verbatim (all subsections: tiers, running, xdist, LLM backend, E2E harness, isolation, adding tests, failure classification)

**1f. State Authority** (DEDUPLICATED)

- 2-sentence actionable rule: "disk before DB on all mutations" + "manifest.py and sidecar.py are canonical"
- Pointer: `See docs/architecture/ARCHITECTURE.md §2.5 for the full authority model`

**1g. Module Dependency Rule** (DEDUPLICATED)

- 1-sentence rule: "core/library modules must not import from CLI, commands, or entrypoints"
- Pointer: `See docs/architecture/ARCHITECTURE.md §1 for the full module structure`

**1h. Source Adapter Architecture** (DEDUPLICATED)

- 2-sentence rule: "source-specific logic only in adapters under sources/<type>/; shared modules must be source-type-agnostic"
- Pointer: `See docs/architecture/ARCHITECTURE.md Source Adapter Pattern for the full design`

**1i. Architecture update trigger** — folded into the governance section (1a), not duplicated standalone

### 2. Replace `CLAUDE.md` (existing file)

Replace entire contents with:

```markdown
@AGENTS.md
```

Claude Code's file-include syntax loads AGENTS.md. Codex reads AGENTS.md directly via OOTB support.

### 3. Create `docs/brain-format/README.md` (new file)

Non-normative index into the six spec documents. Summarises and links but does not redefine any rule from the spec documents.

- Title: "Brain Format Specification"
- 1-2 sentence description: authoritative spec for the portable brain contract
- Table of the 6 documents with one-line purpose each
- Governance note: changes require versioning per VERSIONING.md
- "Referenced by" links to AGENTS.md and ARCHITECTURE.md

### 4. Rewrite `docs/architecture/ARCHITECTURE.md` — v23 alignment pass

Targeted rewrite of stale sections. The document's role (explanation, system design, rationale) stays the same. No structural reorganisation — just correcting content to match v23 reality.

**Stale sections requiring update:**

| Section | Lines | What's stale | v23 correction |
|---|---|---|---|
| System Structure table | 27 | Sidecars at `insights/**/.regen-meta.json` | `knowledge/<area>/.brain-sync/insights/insight-state.json` |
| Reconcile lifecycle | 64 | References old sidecar model | Per-area sidecar files |
| Ownership model | 74 | `insights/` as separate tree | `knowledge/<area>/.brain-sync/insights/` |
| Attachment storage | 80-90 | `_attachments/{page_id}/` path and diagram | `.brain-sync/attachments/{source_dir_id}/` |
| State authority table | 148 | `insights/**/.regen-meta.json` | `knowledge/<area>/.brain-sync/insights/insight-state.json` |
| State authority table | 150-152 | `documents`, `relationships`, `daemon_status` tables | Remove these rows (tables deleted in v23) |
| Managed-file identity | 159-162 | HTML comment identity markers | YAML frontmatter identity |
| Source manifest example | 176-190 | `manifest_version`, `fetch_children`, `child_path` | `version`, remove operational flags |
| Control plane directory | 198-206 | `version.json`, `.sync-state.sqlite`, `insights/` | `brain.json`, DB at `~/.brain-sync/db/`, no separate insights tree |
| DB table justifications | 224-230 | `documents`, `relationships`, `daemon_status` rows | Remove (tables deleted in v23) |
| Global context cache | 250 | `schemas/`, `insights/_core/` | `knowledge/_core/` only |
| Resolved debt | 257 | "Dead v1 manifest system" misleading | Manifests are authoritative in v23, correct the note |

Also update the CLAUDE.md cross-reference on line 34 to point to AGENTS.md and add brain-format pointer.

### 5. Rewrite `README.md` — v23 alignment pass

Keep README user-facing (tutorial/how-to). Remove architecture-heavy internals. Correct stale v23 content.

**Stale content requiring update:**

| Section | Lines | What's stale | v23 correction |
|---|---|---|---|
| Folder structure — after init | 224-236 | Shows `insights/`, `schemas/`, `.sync-state.sqlite` at brain root | Show `.brain-sync/` + `knowledge/` only |
| Folder structure — in practice | 242-273 | Shows `_attachments/`, separate `insights/` tree, `schemas/` | v23 layout with `.brain-sync/` per area |
| Folder restrictions | 275-286 | `_attachments/`, `insights/` mirrors knowledge, `schemas/` deployed | Correct paths and ownership model |
| MCP get_context tool | 299 | References `schemas/`, `insights/_core/` | `knowledge/_core/` and area insights |
| State model | 514-530 | `insights/**/.regen-meta.json`, `.sync-state.sqlite`, `documents`/`relationships` tables | v23 paths and 4-table DB |
| Upgrade & recovery | 533-537 | `.sync-state.sqlite` path | `~/.brain-sync/db/brain-sync.sqlite` |

**Content to relocate (Diataxis):**

The "How it works" section (lines 354-422) contains architectural explanation: sync engine timing strategy, watcher design, regen build-system model, agent role delineation. This is explanation content, not user how-to.

Options:
- Move to `docs/architecture/ARCHITECTURE.md` under a "Core Workflows" section
- Keep a brief user-facing summary in README ("brain-sync watches for changes and regenerates insights automatically") with a pointer to architecture for detail

Recommend: brief summary in README + pointer. Keeps README focused on tasks.

---

## Files

| File | Action |
|---|---|
| `AGENTS.md` | Create |
| `CLAUDE.md` | Replace (thin `@AGENTS.md` pointer) |
| `docs/brain-format/README.md` | Create (non-normative index) |
| `docs/architecture/ARCHITECTURE.md` | v23 alignment rewrite (12 stale sections) |
| `README.md` | v23 alignment rewrite (6 stale sections + Diataxis relocation) |

---

## Deduplication Summary

| Topic | AGENTS.md (after) | ARCHITECTURE.md (after rewrite) |
|---|---|---|
| State Authority | 2-sentence rule + link | Full v23 model §2.5 |
| Module Dependencies | 1-sentence rule + link | Full module table §1 |
| Source Adapters | 2-sentence rule + link | Full v23 adapter pattern |

---

## Verification

1. **Nothing lost** — walk every section of old CLAUDE.md, confirm it appears in AGENTS.md or is covered by an ARCHITECTURE.md pointer
2. **No contradictions** — AGENTS.md rules align with ARCHITECTURE.md detail; both align with brain-format spec
3. **v23 accuracy** — no remaining references to: `insights/` as top-level tree, `_attachments/`, `.sync-state.sqlite` at brain root, `manifest_version`, `fetch_children`, `child_path`, `documents`/`relationships`/`daemon_status` tables, `schemas/` deployed to brain root, HTML comment identity, `version.json`
4. **Links resolve** — all markdown cross-references between AGENTS.md, ARCHITECTURE.md, brain-format/, README.md work
5. **Claude Code loads** — start Claude Code in repo, verify it loads AGENTS.md via `@AGENTS.md` in CLAUDE.md
6. **brain-format reachable** — confirm inbound links from both AGENTS.md and ARCHITECTURE.md
7. **Governance self-documenting** — the governance table + boundary rules make it unambiguous where each content type belongs
8. **Codex compatible** — AGENTS.md at repo root, standard markdown, no Claude-specific syntax
9. **Diataxis purity** — README is task-oriented user guide; architecture is explanation; brain-format is reference; AGENTS.md is operational rules

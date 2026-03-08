---
name: brain-sync
description: >
  Load and navigate a structured second brain managed by brain-sync. Use this
  skill whenever the user mentions "brain", "second brain", or asks about
  topics, initiatives, people, or context tracked in their brain. Also trigger
  when asked to set up syncing for a URL. Trigger liberally. If in doubt,
  load the brain.
---

# brain-sync - Second Brain Skill

## Step 1: Discover the brain

The brain is a filesystem folder with `.sync-state.sqlite` at its root,
alongside `knowledge/`, `insights/`, and `schemas/` folders. The brain root is configured
in `~/.brain-sync/config.json`.

## Step 2: Understand the protocol

CORE_INSTRUCTIONS.md (loaded alongside this skill) defines the folder
structure, summary template, and conventions. **Follow it from this point
forward.**

## Step 3: Load context

Load context progressively. Stop as soon as you can answer the question. The
goal is minimum viable context, not comprehensive loading.

### Priority order

#### 1. Always load first (every conversation) — global context
- All files in `knowledge/_core/` — semantic grounding: identity, org context,
  taxonomy, artifact semantics.
- All files in `schemas/` — insight structure: defines how meaning is surfaced
  in insights. Schemas are structural, not domain knowledge.
- All files in `insights/_core/` (excluding `journal/`) — shared understanding:
  global summaries, glossaries, current priorities, active work.

Load in this order: `knowledge/_core/` → `schemas/` → `insights/_core/`.

This same pattern applies at every level: when loading insights for any area,
load all insight files in that folder but always exclude `journal/` unless
temporal context is specifically needed.

#### 2. Load area insights for topic orientation
- `insights/<area>/summary.md` for the relevant area. **If the summary answers
  the question, stop here.**
- Other insight artifacts in the area only if the summary references them and
  the question requires that detail.
- Sub-area `summary.md` files only if the conversation is specifically about
  that sub-area. Do not load all sub-area summaries speculatively.

#### 3. Load journal for historical context (when needed)
- Only when understanding how thinking evolved matters, e.g. "why did we
  decide X?" or "what changed since last month?"
- Start with the most recent entries. Load at most 2-3 entries before checking
  if the answer has emerged.
- Journal is never loaded proactively.

#### 4. Load knowledge for deep dives (last resort)
- Area knowledge only when the question requires detail beyond what insights
  capture
- When loading synced content, check `_sync-context/_index.md` first. Use
  child/linked page **titles** to decide which to load. Do not load all
  children speculatively.

### Stop rules

- **If the summary answers the question, do not load source documents.**
- **Do not load `_sync-context/` content unless answering a question the
  summary cannot.**
- **Do not load journal unless temporal context is needed.**
- **Do not load attachments (images, PDFs) unless specifically asked.**

Use $ARGUMENTS as a hint for which area to load (e.g. invoked with "AAA",
load the matching initiative insights). Otherwise infer from conversation
context, or ask.

## Your access

- **Read** everything: knowledge/, insights/, schemas/
- **Do not write** to insights/ — insights are regenerated asynchronously
  by brain-sync when knowledge changes
- **May manage** sync sources when the user asks

### Managing sync sources — Python API (preferred)

When possible, use the importable Python API instead of CLI subprocess
calls. This avoids permission prompts and root discovery issues.

```python
from brain_sync.commands import (
    add_source, remove_source, list_sources, move_source,
)
from brain_sync.regen import regen_path, regen_all
```

All functions auto-discover the brain root from `~/.brain-sync/config.json`
when called without an explicit `root` argument.

| Function | Usage |
|---|---|
| `add_source(url=url, target_path=path)` | Register a URL for syncing |
| `remove_source(source=id_or_url)` | Unregister a source |
| `list_sources()` | List registered sources |
| `move_source(source=id, to_path=path)` | Move a source |
| `regen_path(root, path)` | Regenerate insights for a path |
| `regen_all(root)` | Regenerate all insights |

### CLI fallback

Use CLI commands only when Python import is unavailable. The `--root`
flag is optional — if omitted, the brain root is read from config.

| Command | Usage |
|---|---|
| `brain-sync add <url> --path <path>` | Register a URL for syncing |
| `brain-sync remove <id-or-url>` | Unregister a source |
| `brain-sync list` | List registered sources |
| `brain-sync move <id> --to <path>` | Move a source |
| `brain-sync regen [<path>]` | Manually trigger insight regen |

Optional flags for `add`: `--include-links`, `--include-children`,
`--include-attachments`

### Commands you should NOT invoke

Do not run these unless the user explicitly asks:

- `brain-sync init` — creates a new brain
- `brain-sync run` — starts the long-running daemon
- `brain-sync update-skill` — reinstalls skill files

### Interpreting sync requests

When the user asks to "sync", "add", or "track" a URL, use:

```python
from brain_sync.commands import add_source
result = add_source(url="<url>", target_path="<knowledge-path>")
```

Infer `target_path` from the URL content type (e.g. a Confluence page
about "Architecture" → `target_path="architecture"`). Ask the user to
confirm the path if uncertain.

## Step 4: Orient and confirm

After loading context, report back:
- Which files were loaded
- A brief orientation: who the user is, what's in scope, current status
- Confirm readiness to assist

**Always report changes:** When creating or updating any file, report which
files were created/updated at the end of the response.

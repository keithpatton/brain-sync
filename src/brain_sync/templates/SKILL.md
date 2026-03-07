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
alongside `knowledge/` and `insights/` folders. The brain root is configured
in `~/.brain-sync/config.json`.

## Step 2: Understand the protocol

INSTRUCTIONS.md (loaded alongside this skill) defines the folder structure,
summary template, and conventions. **Follow it from this point forward.**

## Step 3: Load context

Load context progressively. Stop as soon as you can answer the question. The
goal is minimum viable context, not comprehensive loading.

### Priority order

#### 1. Always load first (every conversation)
- All files in `insights/_core/` (excluding `journal/`). This is the primary
  orientation: identity, org context, current priorities, active work.

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
- `knowledge/_core/` only when the core insights are insufficient
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

- **Read** everything: knowledge/, insights/
- **Do not write** to insights/ — insights are regenerated asynchronously
  by brain-sync when knowledge changes
- **May run** brain-sync CLI commands when the user asks to manage sync sources

### Managing sync sources

To add a sync source: `brain-sync add <url> --path <knowledge-relative-path>`
To list sources: `brain-sync list`
To remove: `brain-sync remove <canonical-id-or-url>`
To move: `brain-sync move <canonical-id> --to <new-path>`

### Sub-command: sync

If $ARGUMENTS starts with "sync", this is a request to set up syncing for a URL.
Expected form: `sync <url> to <relative-knowledge-path>`

Run `brain-sync add <url> --path <relative-knowledge-path>` via Bash to register
the source. Report the result and confirm brain-sync will pick it up on next run.

## Step 4: Orient and confirm

After loading context, report back:
- Which files were loaded
- A brief orientation: who the user is, what's in scope, current status
- Confirm readiness to assist

**Always report changes:** When creating or updating any file, report which
files were created/updated at the end of the response.

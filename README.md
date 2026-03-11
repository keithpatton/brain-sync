# brain-sync

A brain engine that syncs external knowledge sources, watches for changes, and maintains AI-generated insight summaries. Point it at a root folder and it handles: folder structure setup, source syncing, file watching, and autonomous insight regeneration via Claude.

## Getting started

### Install

```bash
pip install -e .
```

For Google Docs syncing, include the `google` extra:

```bash
pip install -e ".[google]"
```

### Prerequisites

**Claude CLI** — required for insight regeneration. Install and authenticate [Claude Code](https://docs.anthropic.com/en/docs/claude-code).

### Initialise a brain

```bash
brain-sync init ~/my-brain
```

This creates the folder structure, initialises the SQLite state database, and installs the Claude Code skill to `~/.claude/skills/brain-sync/`.

Safe to run on an existing folder — only adds missing structure.

### Configure source credentials

After initialising, configure credentials for each source type you want to sync from. Supported: Confluence and Google Docs.

**Confluence** — create an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens), then:

```bash
brain-sync config confluence \
  --domain yourcompany.atlassian.net \
  --email you@example.com \
  --token your-api-token
```

This writes credentials to `~/.brain-sync/config.json`. Alternatively, set environment variables: `CONFLUENCE_DOMAIN`, `CONFLUENCE_EMAIL`, `CONFLUENCE_TOKEN`.

**Google Docs** — requires the `google` extra (`pip install -e ".[google]"`). Then authenticate:

```bash
brain-sync config google
```

This opens a browser for consent. The token is cached in `~/.brain-sync/config.json`.
To re-authenticate: `brain-sync config google --reauth`

### Add a source

```bash
# Confluence page (with context discovery)
brain-sync add https://yourcompany.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title \
  --path initiatives/my-project \
  --include-links --include-children --include-attachments

# Google Doc
brain-sync add "https://docs.google.com/document/d/1A2B3C/edit" --path area/
```

Sources are registered in SQLite — no manifest files needed.

`--include-links`, `--include-children`, and `--include-attachments` are Confluence-only. Comments are synced for Confluence; Google Docs comments are not yet supported.

### Start the daemon

```bash
brain-sync run --root ~/my-brain
```

The daemon syncs sources, watches `knowledge/` for changes, and enqueues insight regeneration when content changes.

### Talk to your brain

The skill is auto-installed during `brain-sync init`. In Claude Code, invoke it with `/brain-sync` or mention "brain" in conversation. All brain interaction goes through MCP tools — no filesystem access required.

## Folder structure

### After `brain-sync init`

```
my-brain/                               ← you choose the name
  .sync-state.sqlite                    ← managed by brain-sync
  knowledge/                            ← your content goes here
    _core/                              ← global context you maintain
  insights/                             ← agent-generated, don't edit
    _core/
  schemas/                              ← managed by brain-sync
    insights/
      summary.md
```

Init also installs the Claude Code skill to `~/.claude/skills/brain-sync/` and registers the brain in `~/.brain-sync/config.json`.

### In practice — human, synced, and generated content

```
acme-brain/
  .sync-state.sqlite
  knowledge/
    _core/                              ← you write and maintain these
      about-me.md
      org.md
      taxonomy.md
    initiatives/                        ← your folder structure, any depth
      Platform - AAA/
        ERD/
          c123456-erd.md                ← synced from Confluence by brain-sync
          _sync-context/                ← auto-managed by brain-sync
            _index.md
            linked/
            children/
            attachments/
        Meetings/
          notes.md                      ← manually added by you
  insights/                             ← all agent-generated, mirrors knowledge/
    _core/
      summary.md
    initiatives/
      Platform - AAA/
        summary.md
        ERD/
          summary.md
          journal/
            2026-03/
              2026-03-07.md
  schemas/
    insights/
      summary.md                        ← deployed by init
```

**`knowledge/`** is human-owned. You organise folders however you like. brain-sync writes synced pages here; you can also add files manually via `brain-sync add <file>`.

Restrictions:
- `_core/` is reserved for always-loaded global context (top-level only)
- `_sync-context/` directories are managed by brain-sync — do not edit or modify their contents
- Do not rename synced source files — filenames are ID-anchored (e.g. `c12345-page-title.md`) and renaming breaks the link between the file and its sync source
- Filenames starting with `_` or `.` are excluded from insight generation
- Supported formats: `.md`, `.txt` (`.docx` via `brain-sync convert`)

**`insights/`** is agent-owned. brain-sync triggers regeneration; the insights agent writes summaries and journal entries. Mirrors `knowledge/` 1:1.

**`schemas/`** defines the structure of insight artifacts. Currently only `summary.md` is used. Deployed by `brain-sync init`.

## MCP server

brain-sync includes an MCP server that provides complete brain access — querying, searching, reading, source management, and insight regeneration. This lets Claude Code and Claude Desktop interact with the brain without filesystem access.

### Register the server

The project includes `.mcp.json` at the repo root, which Claude Code picks up automatically. To register globally (across all projects):

```bash
claude mcp add --transport stdio --scope user brain-sync -- python -m brain_sync.mcp
```

For Claude Desktop, add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "brain-sync": {
      "command": "python",
      "args": ["-m", "brain_sync.mcp"]
    }
  }
}
```

Restart Claude Code/Desktop. The following tools become available:

#### Brain query tools

| Tool | Description |
|------|-------------|
| `brain_sync_query` | **Primary entrypoint.** Search for areas matching a query. Set `include_global=True` for core context. |
| `brain_sync_get_context` | Load global context (knowledge/_core, schemas, insights/_core) for broad orientation. |
| `brain_sync_open_area` | Load full insight context for a specific area — summary, artifacts, children. |
| `brain_sync_open_file` | Read a specific text file from the brain (.md, .txt, .json, .yaml, .yml). |

#### Source management tools

| Tool | Description |
|------|-------------|
| `brain_sync_list` | List registered sources (optional `filter_path`) |
| `brain_sync_add` | Register a URL for syncing or add a local file |
| `brain_sync_suggest_placement` | Suggest brain areas for placing a new document |
| `brain_sync_update` | Update settings for a source (pass only the flags to change) |
| `brain_sync_remove` | Unregister a source |
| `brain_sync_move` | Move a source to a new path |
| `brain_sync_reconcile` | Reconcile DB target paths with filesystem after offline moves |
| `brain_sync_regen` | Regenerate insights (optional `path`, omit for all) |

All tools return `{"status": "ok", ...}` on success or `{"status": "error", "error": "<type>", ...}` on failure.

Token budgets are enforced server-side — responses are deterministically capped to prevent prompt explosion.

### Run manually

```bash
python -m brain_sync.mcp
```

The server communicates over stdio using the MCP JSON-RPC protocol.

## CLI reference

| Command | Description |
|---|---|
| `brain-sync init <root>` | Create folder structure, install skill, init SQLite |
| `brain-sync run [--root <path>]` | Start the daemon (sync + watch + regen) |
| `brain-sync add <source> [--path <path>] [--include-links] [--include-children] [--include-attachments] [--copy] [--dry-run] [--subtree <path>]` | Add a file or register a sync source to your brain (suggests placement when `--path` omitted) |
| `brain-sync remove <canonical-id-or-url> [--delete-files]` | Unregister a source |
| `brain-sync list [--path <filter>] [--status]` | List registered sources |
| `brain-sync move <canonical-id> --to <new-path>` | Move a source to a new knowledge path |
| `brain-sync update <canonical-id-or-url> [--include-links\|--no-include-links] [--include-children\|--no-include-children] [--include-attachments\|--no-include-attachments]` | Update source settings without re-adding |
| `brain-sync reconcile [--root <path>]` | Update DB target paths to match where files actually are on disk |
| `brain-sync regen [<knowledge-path>]` | Manually trigger insight regeneration (all paths if omitted) |
| `brain-sync config confluence --domain <d> --email <e> --token <t>` | Configure Confluence credentials |
| `brain-sync config google [--reauth]` | Authenticate with Google for Google Docs syncing |
| `brain-sync convert <file> [--comments-from <docx>]` | Convert .docx to markdown, or append comments from .docx to .md |
| `brain-sync update-skill` | Re-install skill and instruction files to `~/.claude/skills/brain-sync/` |

All commands accept `--root <path>` (defaults to current directory) and `--log-level` (DEBUG, INFO, WARNING).

## How it works

### Sync engine

The daemon polls registered sources on an adaptive schedule:

| Unchanged duration | Check interval |
|---|---|
| Recently changed | 30 minutes |
| 1+ week | 1 hour |
| 2+ weeks | 4 hours |
| 3+ weeks | 12 hours |
| 3+ months | 24 hours |

When content changes, the interval resets to 30 minutes. Confluence sources get a cheap version check (REST API) before a full fetch, so unchanged pages are fast. Google Docs does not support version checks — every sync does a full fetch via HTML export.

### Context discovery

When a source has `include_links`, `include_children`, or `include_attachments` enabled, the daemon discovers and syncs related documents into `_sync-context/` subdirectories:

| Flag | Discovers | Storage |
|---|---|---|
| `--include-links` | Pages linked from the primary document | `_sync-context/linked/` |
| `--include-children` | Direct child pages in the page tree | `_sync-context/children/` |
| `--include-attachments` | Attached files (images, PDFs, etc.) | `_sync-context/attachments/` |

Context documents are incrementally maintained (added, updated, removed) and an auto-generated index at `_sync-context/_index.md` provides a navigable map.

### Knowledge watcher

The daemon watches `knowledge/` recursively for file changes:

- 30-second debounce window (batches rapid changes)
- Ignores `_sync-context/`, temp files, and `insights/`
- On change: enqueues insight regeneration for the affected folder
- On folder move: mirrors the move to `insights/` and updates source paths in the database

### Insight regeneration

Regeneration works like a build system (Make/Bazel), not an AI reasoning chain. The engine is deterministic — the LLM's only job is to write good summaries.

**How it works:**

1. A knowledge folder changes (detected by watcher or manual `brain-sync regen`)
2. Compute content hash of all `.md` files in the folder
3. If hash matches the last regen — skip (nothing changed)
4. Invoke Claude CLI headless to read the knowledge files and write `summary.md`
5. If the new summary is >97% similar to the old one — discard (prevents LLM rewording drift)
6. Walk up to the parent folder and repeat (parent reads child summaries, never raw knowledge)
7. Stop when a summary is unchanged

**Leaf summaries** read raw knowledge files. **Parent summaries** read only child summaries. This creates a compression pyramid where each level abstracts the level below.

The insights agent also writes **journal entries** at `insights/<path>/journal/YYYY-MM/YYYY-MM-DD.md` when knowledge changes are significant, capturing what changed and why it matters.

**Timing and tokens** are tracked in the database (`insight_state` table) for observability.

### Insight regeneration vs agent skill

brain-sync has two distinct agent roles:

| | Insights agent | Skill agent |
|---|---|---|
| **When** | Triggered by brain-sync (daemon or `regen` command) | Triggered by user in Claude Code |
| **How** | Claude CLI headless (`--print --dangerously-skip-permissions`) | Interactive Claude Code session |
| **Access** | Reads `knowledge/`, `schemas/`, writes `insights/` | Reads everything, writes nothing |
| **Purpose** | Maintain summaries and journal entries | Answer questions, navigate context |
| **Instructions** | INSIGHT_INSTRUCTIONS.md (embedded in prompt) | SKILL.md (in `~/.claude/skills/`) |

The skill agent benefits from the insights agent's work — it loads pre-computed summaries instead of reading raw knowledge files, enabling fast progressive disclosure.

## Configuration

brain-sync stores configuration in `~/.brain-sync/config.json`:

```json
{
  "brains": ["/path/to/my-brain"],
  "log_level": "INFO",
  "confluence": {
    "domain": "yourcompany.atlassian.net",
    "email": "you@example.com",
    "token": "your-api-token"
  },
  "google": {
    "token": "<managed by brain-sync config google>"
  },
  "regen": {
    "model": "claude-sonnet-4-6",
    "effort": "medium",
    "timeout": 300,
    "max_turns": 50,
    "similarity_threshold": 0.97
  }
}
```

The `brains` list is written by `brain-sync init`. The `log_level` applies to both the daemon and MCP server (DEBUG, INFO, WARNING). The `confluence` section stores Confluence REST API credentials (can also be set via `CONFLUENCE_DOMAIN`, `CONFLUENCE_EMAIL`, `CONFLUENCE_TOKEN` env vars). The `google` section stores the OAuth token managed by `brain-sync config google`. The `regen` section is optional — defaults are used if omitted.

## Converting .docx files

Google Docs comments are only preserved in `.docx` exports (not markdown). The `convert` command extracts comments and produces markdown files the regen engine can process.

**Hybrid mode** (recommended) — export from Google Docs as both `.md` and `.docx`, then merge:

```bash
brain-sync convert document.md --comments-from document.docx
```

This appends a `## Comments` section to the markdown with author, date, annotated text, and comment body. Idempotent — re-running replaces the existing comments section.

**Full conversion** — when only `.docx` is available:

```bash
brain-sync convert document.docx
```

Converts body text to markdown and appends comments. Writes `document.md` alongside the original.

Options: `--output <path>` to write to a specific location.

## Filename convention

All synced files use ID-anchored filenames for stability across title changes:

| Source | Pattern | Example |
|---|---|---|
| Confluence | `c{page_id}-{slug}.md` | `c123456-traveller-profile-service-erd.md` |
| Google Docs | `g{doc_id}-{slug}.md` | `g1A2B3C-product-prd.md` |
| Attachments | `a{attachment_id}-{filename}` | `a456789-architecture-diagram.png` |

## Offline knowledge management

You own `knowledge/` — you can restructure it while the daemon is stopped and brain-sync will reconcile on next startup.

### Safe offline operations

| Action | Why it works |
|---|---|
| Move folders between areas | Reconcile detects files by ID-anchored filename |
| Move individual files to different folders | Same — ID prefix enables rediscovery |
| Delete synced files | Recreated on next sync (idempotent) |
| Create your own files in `knowledge/` | Never touched by sync (no ID-anchor match) |
| Rename files (keeping the ID prefix) | Rediscovery matches on prefix, e.g. `c12345-old.md` to `c12345-new-name.md` |

### Operations that break things

| Action | Why it breaks |
|---|---|
| Remove the ID prefix from a synced filename (e.g. `c12345-page.md` to `page.md`) | Reconcile cannot find it — file is orphaned, sync recreates a duplicate |
| Edit synced file content | Synced files are managed artifacts — treat them as read-only. Next sync overwrites without merge or backup |
| Move `_sync-context/` contents outside their parent folder | Relationship paths break, context is re-fetched from scratch |
| Change the ID portion of a filename (e.g. `c12345` to `c99999`) | File becomes unfindable, orphaned |

### How reconcile works

- `brain-sync run` performs: reconcile, enqueue regen, sync, regen — so insights rebuild automatically in the same run after offline moves
- `brain-sync reconcile` is available as a manual CLI command (updates the database only, does not trigger regen)
- `brain_sync_reconcile` MCP tool is available from Claude (same — database only, no regen)
- `insights/` is derived state managed by regen — reconcile updates source paths, then regen rebuilds insights at the correct locations and cleans up orphaned state

## State

Sync state is persisted to `.sync-state.sqlite` (SQLite with WAL mode) in the brain root:

- **sources** — per-source scheduling, content hash, target path, context flags
- **documents** — canonical ID, URL, title, content hash for all synced documents
- **relationships** — parent-child links between primary sources and context documents
- **insight_state** — per-folder content hash, regen timing, token counts, status

If the state file is lost, the daemon starts fresh (one redundant fetch cycle, insights regenerated on next change).

## Development

```bash
pip install -e ".[dev,google]"
python -m pytest
```

593 tests covering: state persistence, schema migrations, file operations, scheduler, context discovery, link rewriting, regen engine (including prompt construction), regen queue, watcher moves, docx conversion, MCP server, source adapters, and integration tests.

## Supported sources

| Source | Status | Auth |
|---|---|---|
| Confluence | Working | REST API (basic auth via config or env vars) |
| Google Docs | Working | Native OAuth2 (`--client-secrets`), gcloud CLI fallback |

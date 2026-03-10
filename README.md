# brain-sync

A brain engine that syncs external knowledge sources, watches for changes, and maintains AI-generated insight summaries. Point it at a root folder and it handles: folder structure setup, source syncing, file watching, and autonomous insight regeneration via Claude.

## Getting started

### Install

```bash
pip install -e .
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

After initialising, configure credentials for each source type you want to sync from. Currently supported: Confluence.

**Confluence** — create an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens), then:

```bash
brain-sync config confluence \
  --domain yourcompany.atlassian.net \
  --email you@example.com \
  --token your-api-token
```

This writes credentials to `~/.brain-sync/config.json`. Alternatively, set environment variables: `CONFLUENCE_DOMAIN`, `CONFLUENCE_EMAIL`, `CONFLUENCE_TOKEN`.

### Add a source

```bash
brain-sync add https://yourcompany.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title \
  --path initiatives/my-project \
  --include-links --include-children --include-attachments
```

Sources are registered in SQLite — no manifest files needed.

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
  schemas/                              ← editable — you can modify or add schemas
    insights/
      summary.md
      decisions.md
      glossary.md
      status.md
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
      summary.md                        ← deployed by init, editable
      decisions.md
      glossary.md
      status.md
```

**`knowledge/`** is human-owned. You organise folders however you like. brain-sync writes synced pages here; you can also add files manually.

**`insights/`** is agent-owned. brain-sync triggers regeneration; the insights agent writes summaries and journal entries. Mirrors `knowledge/` 1:1.

**`schemas/`** defines the structure of insight artifacts. Deployed by `brain-sync init` — you can edit existing schemas or add new ones.

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
| `brain_sync_add` | Register a URL for syncing |
| `brain_sync_remove` | Unregister a source |
| `brain_sync_move` | Move a source to a new path |
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
| `brain-sync add <url> [--path <path>] [--include-links] [--include-children] [--include-attachments]` | Register a source for syncing |
| `brain-sync remove <canonical-id-or-url> [--delete-files]` | Unregister a source |
| `brain-sync list [--path <filter>] [--status]` | List registered sources |
| `brain-sync move <canonical-id> --to <new-path>` | Move a source to a new knowledge path |
| `brain-sync regen [<knowledge-path>]` | Manually trigger insight regeneration (all paths if omitted) |
| `brain-sync config confluence --domain <d> --email <e> --token <t>` | Configure Confluence credentials |
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

When content changes, the interval resets to 30 minutes. Each source gets a version check (REST API) before a full fetch, so unchanged pages are cheap.

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
  "regen": {
    "model": "claude-sonnet-4-6",
    "effort": "medium",
    "timeout": 300,
    "max_turns": 50,
    "similarity_threshold": 0.97
  }
}
```

The `brains` list is written by `brain-sync init`. The `log_level` applies to both the daemon and MCP server (DEBUG, INFO, WARNING). The `confluence` section stores Confluence REST API credentials (can also be set via `CONFLUENCE_DOMAIN`, `CONFLUENCE_EMAIL`, `CONFLUENCE_TOKEN` env vars). The `regen` section is optional — defaults are used if omitted.

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

## State

Sync state is persisted to `.sync-state.sqlite` (SQLite with WAL mode) in the brain root:

- **sources** — per-source scheduling, content hash, target path, context flags
- **documents** — canonical ID, URL, title, content hash for all synced documents
- **relationships** — parent-child links between primary sources and context documents
- **insight_state** — per-folder content hash, regen timing, token counts, status

If the state file is lost, the daemon starts fresh (one redundant fetch cycle, insights regenerated on next change).

## Development

```bash
pip install -e ".[dev]"
python -m pytest
```

359 tests covering: state persistence, schema migrations, file operations, scheduler, context discovery, link rewriting, regen engine (including prompt construction), regen queue, watcher moves, docx conversion, MCP server, and integration tests.

## Supported sources

| Source | Status | Auth |
|---|---|---|
| Confluence | Working | REST API (basic auth via config or env vars) |
| Google Docs | Scaffolded | gcloud OAuth (pending setup) |

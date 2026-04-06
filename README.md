# brain-sync

brain-sync is a local-first tool for building markdown-native knowledge bases.
It syncs external documents into a portable filesystem-based brain, maintains
AI-generated summaries for each knowledge area, and exposes the result to MCP
clients and agent workflows.

It gives you:

- a portable brain rooted in normal files and folders
- source sync into `knowledge/`
- automatic reconciliation of online and offline changes
- co-located summaries, journals, and attachments under `.brain-sync/`
- an MCP server for chat-based access and management

For the normative on-disk contract, see `docs/brain/` and the shared
reference docs under `docs/`.

For synced-source lifecycle behavior, event/state models, and daemon/reconcile
flow explanation, see `docs/sync/README.md`.

## Getting Started

### Prerequisites

- Python `3.11+`
- Claude CLI for regeneration

Install and authenticate Claude Code first:
[Anthropic Claude Code docs](https://docs.anthropic.com/en/docs/claude-code)

### Install

```bash
pip install -e .
```

For Google Docs syncing:

```bash
pip install -e ".[google]"
```

### Initialize a Brain

```bash
brain-sync init ~/my-brain
```

This creates the baseline brain structure:

- `.brain-sync/brain.json`
- `.brain-sync/sources/`
- `knowledge/`
- `knowledge/_core/`

It also installs the Claude skill to `~/.claude/skills/brain-sync/` and
registers the brain in `~/.brain-sync/config.json`.

### Configure Sources

#### Confluence

```bash
brain-sync config confluence \
  --domain yourcompany.atlassian.net \
  --email you@example.com \
  --token your-api-token
```

Credentials are stored in `~/.brain-sync/config.json`. You can also use
`CONFLUENCE_DOMAIN`, `CONFLUENCE_EMAIL`, and `CONFLUENCE_TOKEN`.

#### Google Docs

```bash
brain-sync config google
```

This opens a browser for OAuth consent and stores the token in
`~/.brain-sync/config.json`.

### Start the Daemon

```bash
brain-sync run --root ~/my-brain
```

The daemon reconciles offline changes, syncs sources, watches `knowledge/`,
and regenerates summaries as needed. The current runtime model allows only one
active daemon per runtime config directory, so if another live brain-sync
daemon is already using the same config dir, the new start is refused
immediately by the runtime startup guard. Startup also prunes old local
`token_events` and `operational_events` history before it reloads active sync
state.

### Add a Source

```bash
brain-sync add https://yourcompany.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title \
  --path initiatives/my-project \
  --fetch-children \
  --sync-attachments

brain-sync add "https://docs.google.com/document/d/1A2B3C/edit" --path area
```

`--path` is optional. If omitted, brain-sync can suggest placement based on
your existing tree.

`--fetch-children` and `--sync-attachments` are execution-time sync options.

### Sync a Source Now

```bash
brain-sync sync [<canonical-id-or-url> ...]
```

This requests immediate polling for active sources by setting their persisted
next-check time to now.

- with no selectors, all active sources are marked due immediately
- with one or more selectors, only those active sources are marked due
  immediately

The command does not fetch remote content itself. It only updates
`sync_polling` so the targeted sources are due on the next daemon refresh or
the next `brain-sync run`.

### Add a Local File

```bash
brain-sync add-file ./notes.md --path area
```

Supported direct file imports: `.md`, `.txt`

For `.docx`, use `brain-sync convert` first.

## Folder Structure

### After `brain-sync init`

```text
my-brain/
  .brain-sync/
    brain.json
    sources/
  knowledge/
    _core/
```

Runtime state is intentionally outside the brain root:

```text
~/.brain-sync/
  config.json
  daemon.json
  db/brain-sync.sqlite
```

### In Practice

Not sure how to structure your brain? See the
[Knowledge Tree Structure Guide](./docs/user/BRAIN_TREE_STRUCTURE_GUIDE.md) for
a shareable, generic example of top-level buckets, knowledge-area sizing, and
practical placement rules.

Want a quick visual walkthrough? See [Demo Videos](./docs/user/DEMOS.md).

### Ownership Rules

- `knowledge/` is where your documents live.
- `.brain-sync/` is the reserved managed namespace.
- Synced source files are managed content and may be overwritten on the next
  sync.
- Co-located summaries and attachments move with their area automatically.
- `_core/` is the optional core-knowledge area that feeds global context.

## Talk To Your Brain

### Claude Code

Register the MCP server once:

```bash
claude mcp add --transport stdio --scope user brain-sync -- python -m brain_sync.interfaces.mcp.server
```

Then restart Claude Code and invoke `/brain-sync` or mention your brain in the
conversation.

### Claude Desktop

1. Install the skill from `src/brain_sync/skills/brain_sync/SKILL.md`
2. Register the MCP server:

```json
{
  "mcpServers": {
    "brain-sync": {
      "command": "python",
      "args": ["-m", "brain_sync.interfaces.mcp.server"]
    }
  }
}
```

3. Restart Claude Desktop

### Backing Up Your Brain

Initialize a private Git repository at the brain root and push it to a private
remote. Commit the brain:

- `knowledge/`
- `.brain-sync/`

Do not commit machine-local runtime state from `~/.brain-sync/`. That directory
contains disposable caches, local credentials, daemon state, and the runtime DB.

Using a private Git repo matters for two reasons:

- it gives you normal backups, history, branching, and multi-machine sync for
  the brain itself
- it keeps your checked-out files consistent across Windows, macOS, and Linux,
  which helps avoid newline-only checkout differences being mistaken for content
  changes during reconcile and regen

For a brain repository, prefer byte-stable checkout rules over OS-native line
ending translation. Add a `.gitattributes` file at the brain root like this:

```gitattributes
* -text
*.png binary
*.jpg binary
*.jpeg binary
*.gif binary
*.pdf binary
*.sqlite binary
```

`* -text` tells Git not to rewrite line endings on checkout. That keeps the
working tree bytes stable across supported platforms, which is especially
important because brain-sync hashes the files it sees on disk when deciding
whether a knowledge area changed.

### Example Requests

- "Add this Confluence page to initiatives/platform and sync attachments"
- "Summarize what my brain knows about Project X"
- "Open the platform area and show me the current summary"
- "Compare the docs in my brain with this code change"

## MCP Server

brain-sync exposes an MCP server for querying, reading, and managing the brain.

Primary tools:

| Tool | Description |
|---|---|
| `brain_sync_query` | Search areas by query |
| `brain_sync_tree` | Return the full semantic knowledge-area tree as a sparse read-only JSON structure |
| `brain_sync_get_context` | Load global context from the `_core` summary at `knowledge/_core/.brain-sync/insights/summary.md` |
| `brain_sync_open_area` | Load an area's summary, artifacts, and children |
| `brain_sync_open_file` | Read a text file from the brain |
| `brain_sync_list` | List registered sources, including `knowledge_state` for missing registered sources |
| `brain_sync_add` | Register a sync source |
| `brain_sync_add_file` | Add a local markdown or text file |
| `brain_sync_update` | Update source settings |
| `brain_sync_remove` | Remove a sync source; may return handled `not_found` or `lease_conflict` |
| `brain_sync_move` | Move one registered source by exact canonical ID to a new path; may return handled `not_found` or `lease_conflict` |
| `brain_sync_finalize_missing` | Explicitly finalize one missing registered source by exact canonical ID |
| `brain_sync_reconcile` | Reconcile filesystem moves |
| `brain_sync_regen` | Regenerate summaries |

Run manually:

```bash
python -m brain_sync.interfaces.mcp.server
```

## CLI Reference

| Command | Description |
|---|---|
| `brain-sync init <root>` | Initialize a brain |
| `brain-sync run [--root <path>]` | Start the daemon |
| `brain-sync add <url> [...]` | Register a URL for sync |
| `brain-sync add-file <file> [...]` | Import a local markdown or text file |
| `brain-sync remove <canonical-id-or-url> [--delete-files]` | Remove a sync source and its synced files (`--delete-files` is accepted for compatibility); may return handled `not_found` or `lease_conflict` |
| `brain-sync remove-file <path>` | Remove a local file from `knowledge/` |
| `brain-sync list [--path <filter>] [--status]` | List registered sources and print `State: <knowledge_state>` for each source |
| `brain-sync move <canonical-id> --to <new-path>` | Move one registered source by exact canonical ID; may return handled `not_found` or `lease_conflict` |
| `brain-sync update <canonical-id-or-url> [...]` | Update source settings |
| `brain-sync sync [<canonical-id-or-url> ...]` | Schedule priority polling for all active sources or the listed active sources by updating `sync_polling`; handled `not_found` is returned when any listed selector is not currently active |
| `brain-sync reconcile [--root <path>]` | Reconcile filesystem moves |
| `brain-sync finalize-missing <canonical-id>` | Explicitly finalize one missing registered source after revalidation; requires an exact canonical ID, not a URL or path |
| `brain-sync status [--root <path>]` | Show daemon and sync status |
| `brain-sync tree [--json]` | Show the full semantic knowledge-area tree; `--json` emits the same sparse contract as `brain_sync_tree` |
| `brain-sync regen [<knowledge-path>]` | Trigger regeneration |
| `brain-sync doctor [--fix|--rebuild-db]` | Validate or repair a brain |
| `brain-sync config confluence ...` | Configure Confluence credentials |
| `brain-sync config google [--reauth]` | Authenticate Google Docs access |
| `brain-sync convert <file> [--comments-from <docx>]` | Convert `.docx` to markdown |
| `brain-sync migrate [--root <path>]` | Legacy attachment-layout migration helper |
| `brain-sync update-skill` | Re-install the Claude skill |

All commands accept `--log-level`. Commands that operate on a brain root accept
`--root`.

## Updating brain-sync

1. Stop the daemon
2. Pull the latest code
3. Update the skill:

```bash
brain-sync update-skill
```

4. Restart your MCP client
5. Start `brain-sync run` again

## Configuration

brain-sync stores machine-local configuration in `~/.brain-sync/config.json`.

Typical fields include:

- registered brain roots
- log level
- Confluence credentials
- Google token
- regen settings
- operational event retention settings
- token retention settings

Local telemetry retention keys:

- `operational_events.retention_days` defaults to `90`
- `token_events.retention_days` defaults to `90`

## Converting .docx Files

Google Docs comments survive best through `.docx` exports.

Hybrid mode:

```bash
brain-sync convert document.md --comments-from document.docx
```

Full conversion:

```bash
brain-sync convert document.docx
```

## State and Recovery

brain-sync uses three broad state layers:

1. durable manifests in `.brain-sync/sources/`
2. durable per-area insight state in `knowledge/**/.brain-sync/insights/`
3. machine-local runtime DB and daemon state in `~/.brain-sync/`

If the runtime DB is lost, it can be rebuilt from the durable brain state.

Run `brain-sync doctor` after upgrades or if the brain looks inconsistent.

## Offline Knowledge Management

You can move, rename, create, and delete files under `knowledge/` while the
daemon is stopped.

On the next `brain-sync run`:

- manifests are reconciled with filesystem truth
- moved synced files are rediscovered
- missing synced sources remain registered until you explicitly run
  `brain-sync finalize-missing <canonical-id>`
- changed areas are re-queued for regeneration
- co-located summaries and attachments already move with their folders

`brain-sync finalize-missing` is intentionally conservative: it accepts one
exact canonical ID at a time, not a URL, path, or bulk target, revalidates
local presence first, finalizes immediately when an already-missing source is
still absent, and returns `not_missing` instead of deleting anything if the
source reappears during revalidation. Likewise, `brain-sync move` now requires
an exact canonical ID, while `brain-sync remove` accepts either a canonical ID
or URL; both return handled `not_found` when the target source cannot be
resolved, rather than partially entering lifecycle work.

## Development

```bash
pip install -e ".[dev,google]"
python -m pytest -n auto
```

## Supported Sources

| Source | Status | Auth |
|---|---|---|
| Confluence | Working | REST API credentials via config or env |
| Google Docs | Working | Native OAuth browser consent |

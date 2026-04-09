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
- a bootstrap-capable MCP launcher for chat-based access and management

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
pip install .
```

Google OAuth support is bundled in the packaged runtime. No separate
`.[google]` extra is required for normal use.

The install provides two user-facing commands:

- `brain-sync` for CLI operations and terminal foreground daemon runs
- `brain-sync-mcp` for the shared bootstrap-capable MCP launcher used by all host integrations

### Choose a Host

brain-sync supports three host integration styles, all pointing at the same
shared `brain-sync-mcp` launcher seam:

| Host | Integration model | Repo artifact |
|---|---|---|
| Claude Code | Direct MCP registration | `.mcp.json` |
| Claude Desktop | Manual MCP registration plus skill | `docs/examples/claude-desktop.mcp.json`, `src/brain_sync/interfaces/mcp/resources/brain_sync/SKILL.md` |
| Codex | Repo-local plugin | `plugins/brain-sync/`, `.agents/plugins/marketplace.json` |

These host integrations are intentionally thin and share the same installed
`brain-sync-mcp` launcher command. Before using any host integration, install the
package into the Python environment you want the host to use:

```bash
python -m pip install -e .
brain-sync-mcp
```

If the second command starts the MCP launcher successfully, the launcher command
surface is installed correctly. Stop it with `Ctrl+C` after the check.

#### Claude Code

Claude Code uses direct MCP registration. Register the MCP server once:

```bash
claude mcp add --transport stdio --scope user brain-sync -- brain-sync-mcp
```

Then restart Claude Code and mention your brain in the conversation.

#### Claude Desktop

Claude Desktop currently uses manual MCP registration plus the brain-sync
skill.

1. Install the skill from `src/brain_sync/interfaces/mcp/resources/brain_sync/SKILL.md`
2. Register the MCP server manually:

```json
{
  "mcpServers": {
    "brain-sync": {
      "command": "brain-sync-mcp"
    }
  }
}
```

You can also copy the checked-in example from
`docs/examples/claude-desktop.mcp.json`.

3. Restart Claude Desktop

#### Codex

Codex uses a repo-local plugin. This repository ships a marketplace manifest at
`.agents/plugins/marketplace.json`, and it points at the checked-in plugin
bundle in `plugins/brain-sync/`.

To use it:

1. Install `brain-sync` so `brain-sync-mcp` is available on `PATH`.
2. Restart Codex with this repository open as the active workspace.
3. Codex should surface `brain-sync` from `brain-sync Repo Plugins`
   automatically because the repo marketplace marks it `INSTALLED_BY_DEFAULT`.
4. If it still is not enabled, open the plugin directory, choose
   `brain-sync Repo Plugins`, and enable `brain-sync` manually.

If you do not see the marketplace after the repo adds
`.agents/plugins/marketplace.json`, fully quit and reopen Codex.

### First Use

The primary interface is your host integration, not the raw tool names. If you
are starting from scratch, ask Claude Code, Claude Desktop, or Codex to create
a brain and show status:

- "Create a new brain at `C:\\Users\\you\\my-brain` and show runtime status."

If you already have an initialized brain, ask the host to attach it:

- "Attach `C:\\Users\\you\\my-brain` and show runtime status."

brain-sync can remember multiple registered brains on the same machine, but the
runtime uses one active attached root at a time for shared daemon control and
host sessions.

## Talk To Your Brain

Once a brain is attached, you usually interact with brain-sync by asking your
host to do work in plain language rather than naming MCP tools directly.

### What You Can Ask

- "Show runtime status for the attached brain."
- "Search my brain for AAA and open the best match."
- "Summarize what my brain knows about Project X."
- "Open the platform area and show me the current summary."
- "Start the shared daemon if needed."
- "Add this Confluence page to initiatives/platform and sync attachments."
- "Suggest where this document should live, then add it."
- "Reconcile filesystem moves and regenerate changed areas."
- "Compare the docs in my brain with this code change."

### Configure Your Brain

Source authentication is still CLI-first in this slice. Configure credentials
once, then use your host integration for the day-to-day work.

#### Confluence

```bash
brain-sync config confluence \
  --domain yourcompany.atlassian.net \
  --email you@example.com \
  --token your-api-token
```

Credentials are stored in `~/.brain-sync/config.json`. You can also use
`CONFLUENCE_DOMAIN`, `CONFLUENCE_EMAIL`, and `CONFLUENCE_TOKEN`.

After that, you can ask your host:

- "Add this Confluence page to initiatives/platform."

#### Google Docs

```bash
brain-sync config google \
  --client-id your-google-client-id \
  --client-secret your-google-client-secret
```

`--client-id` and `--client-secret` must come from a Google OAuth client that
already exists in a Google Cloud project. They are not generated by
`brain-sync`. For most users, this means creating a Desktop App OAuth client in
Google Cloud first, then supplying those values here.

This opens a browser for OAuth consent and stores both the OAuth client and the
token in `~/.brain-sync/config.json`. Use `--reauth` to force a new consent
flow later.

After that, you can ask your host:

- "Add this Google Doc to initiatives/platform."

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

### Ownership Rules

- `knowledge/` is where your documents live.
- `.brain-sync/` is the reserved managed namespace.
- Synced source files are managed content and may be overwritten on the next
  sync.
- Co-located summaries and attachments move with their area automatically.
- `_core/` is the optional core-knowledge area that feeds global context.

## Backing Up Your Brain

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

## CLI Reference

Most users can stay in Claude, Claude Desktop, or Codex once their host
integration is set up. The CLI still matters for terminal-first workflows,
automation, and source configuration.

| Command | Description |
|---|---|
| `brain-sync init <root>` | Initialize a brain |
| `brain-sync run [--root <path>]` | Start the real foreground daemon engine |
| `brain-sync attach-root <root>` | Attach an existing initialized brain and make it the active runtime root |
| `brain-sync start` | Start or adopt the shared background daemon for the active runtime root |
| `brain-sync stop` | Stop the shared `launcher-background` daemon when remote control is supported |
| `brain-sync restart` | Restart the shared `launcher-background` daemon when remote control is supported |
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
| `brain-sync status [--root <path>]` | Show setup, daemon, and sync status for the active runtime |
| `brain-sync tree [--json]` | Show the full semantic knowledge-area tree; `--json` emits the same sparse contract as `brain_sync_tree` |
| `brain-sync regen [<knowledge-path>]` | Trigger regeneration |
| `brain-sync doctor [--fix|--rebuild-db]` | Validate or repair a brain |
| `brain-sync config confluence ...` | Configure Confluence credentials |
| `brain-sync config google [--reauth]` | Authenticate Google Docs access |
| `brain-sync convert <file> [--comments-from <docx>]` | Convert `.docx` to markdown |
| `brain-sync migrate [--root <path>]` | Legacy attachment-layout migration helper |
| `brain-sync update-skill` | Re-install the Claude Desktop skill |

All commands accept `--log-level`. Commands that operate on a brain root accept
`--root`.

### Common CLI Tasks

Initialize a new brain:

```bash
brain-sync init ~/my-brain
```

Attach an existing initialized brain and make it active:

```bash
brain-sync attach-root ~/my-existing-brain
```

Start the real foreground daemon engine:

```bash
brain-sync run --root ~/my-brain
```

Use the launcher-managed background daemon for the active attached root:

```bash
brain-sync start
brain-sync status
brain-sync stop
brain-sync restart
```

`brain-sync start` is idempotent when a healthy daemon is already running for
the same runtime config dir. `brain-sync stop` and `brain-sync restart`
remotely control only `launcher-background` daemons in v1. A healthy
terminal-started `brain-sync run` daemon is still adoptable for status and
normal use, but remote stop/restart remains intentionally unsupported.

Register a source:

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

Request immediate polling for active sources:

```bash
brain-sync sync [<canonical-id-or-url> ...]
```

With no selectors, all active sources are marked due immediately. With one or
more selectors, only those active sources are marked due immediately. The
command does not fetch remote content itself; it only updates `sync_polling`
so the targeted sources are due on the next daemon refresh or the next
`brain-sync run`.

Add a local markdown or text file:

```bash
brain-sync add-file ./notes.md --path area
```

Supported direct file imports: `.md`, `.txt`

For `.docx`, use `brain-sync convert` first.

## MCP Tool Reference

Most users will not invoke these tools directly. They are the MCP surface that
Claude, Claude Desktop, Codex, and other compatible hosts call under the hood.

brain-sync exposes a bootstrap-capable MCP launcher for querying, reading, and
managing the brain.

### MCP Daemon Lifecycle

This section applies when a host starts `brain-sync-mcp` as an MCP stdio
server.

You do not normally need to keep a separate `brain-sync-mcp` terminal open for
host-driven use. The host starts the MCP server process when needed.

Bootstrap and admin tools can run without a daemon. When a full brain tool is
used, the MCP surface first requires a usable attached root and then ensures a
healthy shared daemon exists for the active runtime root, reusing one if it is
already running or starting one if it is not.

If MCP starts the daemon, it starts a detached `launcher-background` daemon for
the current runtime config directory. That daemon is shared across later host
sessions for the same runtime and is not tied to the lifetime of one Claude or
Codex terminal session. If the host kills the MCP server process, the detached
daemon can continue running and be adopted later. When the installed CLI
wrapper is available, the launcher starts the daemon via `brain-sync`, which
makes it easier to identify in process lists on platforms such as Windows.

You can still use the CLI directly. Normal CLI commands can coexist with
host-driven MCP use, but `brain-sync run` is still a daemon start. brain-sync
allows only one daemon per runtime config directory, so starting a second
daemon for the same runtime is refused.

If you choose to run `brain-sync run` yourself in a terminal, MCP clients can
adopt that healthy daemon for status and normal use. In v1, remote
`brain_sync_stop` and `brain_sync_restart` support applies only to
`launcher-background` daemons, not terminal-owned foreground daemons.

When no usable active root is attached, the launcher starts in bootstrap mode.
Setup/admin tools work immediately, and full brain tools remain visible for MCP
clients that cache the initial tool list, but those full tools fail closed
until `brain_sync_init` or `brain_sync_attach_root` completes:

| Tool | Description |
|---|---|
| `brain_sync_setup_status` | Report whether an active usable root is attached |
| `brain_sync_init` | Initialize and attach a new brain root |
| `brain_sync_attach_root` | Attach an existing initialized brain root |
| `brain_sync_status` | Show runtime bootstrap, daemon, and content status |
| `brain_sync_start` | Start or adopt the shared background daemon |
| `brain_sync_stop` | Stop a `launcher-background` daemon when supported |
| `brain_sync_restart` | Restart a `launcher-background` daemon when supported |

After `brain_sync_init` or `brain_sync_attach_root`, those same full tools
become usable in the current session.

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
brain-sync-mcp
```

## Updating brain-sync

1. Stop the daemon
2. Pull the latest code
3. Reinstall the package:

```bash
python -m pip install -e .
```

4. If you use Claude Desktop with the manual skill, update the skill:

```bash
brain-sync update-skill
```

5. Restart your host
6. Start `brain-sync run` again

## Configuration

brain-sync stores machine-local configuration in `~/.brain-sync/config.json`.

Typical fields include:

- registered brain roots, with `brains[0]` as the active runtime root
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
pip install -e ".[dev]"
python -m pytest -n auto
```

## Supported Sources

| Source | Status | Auth |
|---|---|---|
| Confluence | Working | REST API credentials via config or env |
| Google Docs | Working | Native OAuth browser consent |

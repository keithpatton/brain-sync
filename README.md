# brain-sync

Cross-platform daemon that watches folders for `sync-manifest.yaml` files and syncs declared external sources into local markdown files.

## What it does

- Scans a target root folder for `sync-manifest.yaml` files
- Fetches content from declared sources (Confluence pages, Google Docs)
- Converts HTML to markdown and writes output files next to the manifest
- Touches a `.dirty` marker when content changes
- Maintains adaptive refresh with backoff (1h → 4h → 12h → 7d)
- Persists sync state to `.sync-state.json`

The daemon is fully generic — it has no knowledge of any specific repository structure. Its only job is: find manifests, fetch sources, write files.

## Quick start

### Install

```bash
pip install -e .
```

### Prerequisites

**Confluence** — install and configure [confluence-cli](https://github.com/pchuri/confluence-cli):

```bash
npm install -g confluence-cli
confluence init --domain "yourcompany.atlassian.net" \
  --api-path "/wiki/rest/api" \
  --auth-type "basic" \
  --email "you@company.com" \
  --token "YOUR_API_TOKEN"
```

Create an API token at [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens).

**Google Docs** — requires `gcloud` with appropriate OAuth scopes (setup docs TBD).

### Create a manifest

In any folder under your target root, create `sync-manifest.yaml`:

```yaml
touch_dirty_relative_path: ../.dirty

sources:
  - url: https://yourcompany.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title
    file: page-title.md

  - url: https://docs.google.com/document/d/abc123
    file: design-doc.md

  - url: https://yourcompany.atlassian.net/wiki/spaces/SPACE/pages/789/Another+Page
    file: auto  # auto-derives filename from page title
```

### Run

```bash
brain-sync --root /path/to/target/folder
```

Or with debug logging:

```bash
brain-sync --root /path/to/target/folder --log-level DEBUG
```

## Manifest schema

| Field | Required | Description |
|---|---|---|
| `sources` | Yes | List of sources to sync |
| `sources[*].url` | Yes | URL of the external document |
| `sources[*].file` | Yes | Output filename (bare name, no path separators), or `auto` to derive from document title |
| `touch_dirty_relative_path` | No | Path to dirty marker, relative to manifest folder. Defaults to `.dirty` in the manifest folder. |

## How it works

1. **Watcher** detects new/changed/removed `sync-manifest.yaml` files (via `watchdog` + periodic rescan)
2. **Scheduler** maintains a priority queue with adaptive backoff per source
3. **Pipeline** for each source: detect type → metadata check → fetch → convert to markdown → atomic write → touch dirty if changed

### Refresh model

| Unchanged duration | Check interval |
|---|---|
| < 7 days | 1 hour |
| 7–14 days | 4 hours |
| 14–21 days | 12 hours |
| > 21 days | 7 days |

When content changes, the interval resets to 1 hour.

### Confluence features

- Page content fetched and converted to markdown
- Inline comments appended under a `## Comments` section
- Metadata version check to skip unnecessary full fetches

## State

Sync state is persisted to `.sync-state.sqlite` (SQLite with WAL mode) in the root folder, tracking per source:
- Last checked/changed timestamps
- Content hash (SHA-256)
- Current polling interval
- Metadata fingerprint (page version)

If the state file is lost or corrupt, the daemon starts fresh (one redundant fetch cycle).

## Development

```bash
pip install -e ".[dev]"
pytest
```

### Tests

- **Unit tests** for manifest parsing, state persistence, file operations, scheduler, URL parsing, HTML conversion
- **Integration tests** with mocked subprocess calls covering the full sync flow: manifest → fetch → write → dirty → state

## Supported sources

| Source | Status | Auth |
|---|---|---|
| Confluence | Working | confluence-cli (API token) |
| Google Docs | Scaffolded | gcloud OAuth (pending setup) |

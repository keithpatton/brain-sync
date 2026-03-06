# brain-sync

Cross-platform daemon that watches folders for `sync-manifest.yaml` files and syncs declared external sources into local markdown files.

## What it does

- Scans a target root folder for `sync-manifest.yaml` files
- Fetches content from declared sources (Confluence pages, Google Docs)
- Converts HTML to markdown and writes output files next to the manifest
- Touches a `.dirty` marker when content changes
- Maintains adaptive refresh with backoff (30m → 1h → 4h → 12h → 24h)
- Persists sync state to `.sync-state.sqlite`
- Discovers and syncs contextual documents (linked pages, child pages, attachments)
- Automatically reconnects moved files via canonical filename prefix matching

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

The confluence-cli config (`~/.confluence-cli/config.json`) is also used for the REST API client. Environment variables `CONFLUENCE_DOMAIN`, `CONFLUENCE_EMAIL`, `CONFLUENCE_TOKEN` work as a fallback.

**Google Docs** — requires `gcloud` with appropriate OAuth scopes (setup docs TBD).

### Create a manifest

In any folder under your target root, create `sync-manifest.yaml`:

```yaml
touch_dirty_relative_path: ../.dirty

sources:
  # Minimal — just a URL. Filename auto-derived from page title (e.g. c123456-page-title.md)
  - url: https://yourcompany.atlassian.net/wiki/spaces/SPACE/pages/123456/Page+Title

  # Explicit filename override (use sparingly — auto is preferred)
  - url: https://docs.google.com/document/d/abc123
    file: design-doc.md

  # Full context discovery — linked pages, children, and attachments
  - url: https://yourcompany.atlassian.net/wiki/spaces/SPACE/pages/789/Architecture
    include_links: true
    include_children: true
    include_attachments: true
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

| Field | Required | Default | Description |
|---|---|---|---|
| `sources` | Yes | | List of sources to sync |
| `sources[*].url` | Yes | | URL of the external document |
| `sources[*].file` | No | `auto` | Output filename (bare name, no path separators). `auto` derives a stable ID-anchored filename from the document (e.g. `c123456-page-title.md`) |
| `sources[*].include_links` | No | `false` | Discover and sync pages linked from this source |
| `sources[*].include_children` | No | `false` | Discover and sync child pages |
| `sources[*].include_attachments` | No | `false` | Discover and sync attachments |
| `sources[*].link_depth` | No | `1` | How many levels of links to follow (0 or 1) |
| `touch_dirty_relative_path` | No | `.dirty` | Path to dirty marker, relative to manifest folder |

## How it works

1. **Watcher** detects new/changed/removed `sync-manifest.yaml` files (via `watchdog` + periodic rescan)
2. **Scheduler** maintains a priority queue with adaptive backoff per source, ±20% jitter, persisted across restarts
3. **Pipeline** for each source: detect type → version check (REST API) → fetch → convert to markdown → context discovery → link rewriting → atomic write → touch dirty if changed

### Refresh model

| Unchanged duration | Check interval |
|---|---|
| Recently changed | 30 minutes |
| 1+ week | 1 hour |
| 2+ weeks | 4 hours |
| 3+ weeks | 12 hours |
| 3+ months | 24 hours |

When content changes, the interval resets to 30 minutes.

### Confluence features

- Page content fetched via REST API (fast version check before full fetch)
- Inline comments appended under a `## Comments` section (via confluence-cli)
- Context discovery: linked pages, child pages, attachments stored in `_sync-context/`
- Context index generated at `_sync-context/_index.md`
- Confluence URLs in primary markdown rewritten to local relative paths
- YAML frontmatter on context files for self-description

### Context discovery

When a source declares `include_links`, `include_children`, or `include_attachments`, the daemon discovers and syncs related documents alongside the primary source. Context files are stored in `_sync-context/` subdirectories next to the manifest.

| Flag | What it discovers | Storage folder |
|---|---|---|
| `include_links: true` | Pages linked from the primary document's HTML body | `_sync-context/linked/` |
| `include_children: true` | Direct child pages in the Confluence page tree | `_sync-context/children/` |
| `include_attachments: true` | Files attached to the primary page (images, PDFs, etc.) | `_sync-context/attachments/` |

The `link_depth` field controls how many levels of links are followed from the primary source. Set to `1` (default) to discover pages directly linked from the primary. Set to `0` to disable link discovery even when `include_links` is true. Values greater than 1 are rejected to prevent runaway crawling.

Context documents are **incrementally maintained**:

- **Added** — newly discovered documents are fetched and written on first encounter
- **Updated** — existing context documents are version-checked each cycle and only re-fetched when the source has changed
- **Removed** — documents no longer discoverable from the primary are cleaned up automatically
- **Shared** — if two primary sources both link to the same page, the context file is kept as long as at least one primary still references it

Each context markdown file includes YAML frontmatter with its canonical ID, source URL, relationship type, and parent reference, making files self-describing even without the database.

An auto-generated index at `_sync-context/_index.md` provides a navigable map of all context documents grouped by relationship type.

Confluence URLs appearing in the primary markdown are automatically rewritten to relative paths pointing at the local context files (e.g. `https://...atlassian.net/.../pages/789/...` becomes `./_sync-context/linked/c789-design-overview.md`). Links to pages outside the discovered set are left intact.

### Folder moves and reorganisation

The sync engine identifies documents by **canonical ID** (e.g. `confluence:123456`), not by file path. If you move a `sync-manifest.yaml` and its surrounding folder to a different location under the root, or reorganise files within the manifest directory, the daemon will automatically reconnect:

- On each sync cycle, the daemon checks whether stored file paths still exist
- If a file has moved, it searches the manifest directory for the canonical filename prefix (e.g. `c123456-`) and reconnects the match
- The internal database is updated with the new path — no manual intervention required

This means you can freely reorganise your folder structure without breaking sync state.

### Filename convention

All synced files use ID-anchored filenames so identity is stable even when titles change:

| Source | Pattern | Example |
|---|---|---|
| Confluence | `c{page_id}-{slug}.md` | `c123456-traveller-profile-service-erd.md` |
| Google Docs | `g{doc_id}-{slug}.md` | `g1A2B3C-product-prd.md` |
| Attachments | `a{attachment_id}-{filename}` | `a456789-architecture-diagram.png` |

### Path rediscovery

If a synced file is moved or its parent folder is reorganised, the daemon automatically reconnects it by searching for the canonical filename prefix (e.g. `c123456-`) under the manifest directory. No manual intervention required.

### Output structure

```
project/
  sync-manifest.yaml
  c123456-erd.md                        # primary source
  _sync-context/
    _index.md                           # auto-generated context graph
    linked/
      c789012-design-overview.md
    children/
      c456789-sub-page.md
    attachments/
      a456789-diagram.png
```

## State

Sync state is persisted to `.sync-state.sqlite` (SQLite with WAL mode) in the root folder, tracking:

- **sources** — per-source scheduling, content hash, metadata fingerprint, polling interval
- **documents** — canonical ID, URL, title, content hash for all synced documents
- **relationships** — parent→child links between primary sources and context documents

If the state file is lost or corrupt, the daemon starts fresh (one redundant fetch cycle).

## Development

```bash
pip install -e ".[dev]"
pytest
```

### Tests

156 tests covering: manifest parsing, state persistence (SQLite round-trips, schema migration), file operations (including path rediscovery), scheduler (jitter, adaptive tiers, persistence), URL parsing (all Confluence formats), HTML conversion, context discovery, reconciliation, link rewriting, context index generation, REST client (with mocked responses including 429 retry), and integration tests.

## Supported sources

| Source | Status | Auth |
|---|---|---|
| Confluence | Working | REST API (basic auth via confluence-cli config or env vars) |
| Google Docs | Scaffolded | gcloud OAuth (pending setup) |

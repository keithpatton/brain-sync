# Supporting Input: v23 Refactor Context

This document is a supporting input for the v23 planning trail. It captures
implementation context and phase mapping that informed the approved plan, but
it is not itself the canonical plan artifact.

This document describes the implementation guide for refactoring brain-sync
from the current v21 codebase to the v23 brain format defined in:

- [RULES.md](../brain-format/RULES.md) — system invariants
- [GLOSSARY.md](../brain-format/GLOSSARY.md) — terminology
- [SCHEMAS.md](../brain-format/SCHEMAS.md) — schema definitions
- [TEMPLATES.md](../brain-format/TEMPLATES.md) — regen templates
- [VERSIONING.md](../brain-format/VERSIONING.md) — version model
- [COMPATIBILITY.md](../brain-format/COMPATIBILITY.md) — supported app/format/runtime matrix

**No legacy migration tooling in this refactor.** This is a clean break
from pre-v23 development layouts. Existing pre-v23 brains must be
re-initialised with `brain-sync init`. The refactor establishes v23 as
the first supportable portable format: **Brain Format v1.0**.

### Note on `brain-example/`

`brain-example/` is a local exemplar of the intended v23 layout and
naming conventions. It is illustrative only — the `docs/brain-format/`
documents remain authoritative for architecture and behaviour. Do not
treat `brain-example/` as a source of architecture truth over the spec
docs.

`brain-example/` is gitignored and may contain sensitive real-world
information. Planning and test design must not depend on reading or
copying its contents. If an exemplar brain structure is useful for tests,
fixtures must be synthesized by the test harness from code (e.g.
`create_brain()`, `seed_knowledge_tree()` in the E2E harness). If the
codebase does not already construct v23-shaped brains in tests, fixture
construction should become part of the E2E/integration test foundation
work in Phase 3.

### Version reference for this refactor

This refactor establishes the first explicit version contract for
brain-sync:

- **Brain Format**: `1.0` (portable filesystem format; represented on
  disk by `.brain-sync/brain.json` with `{ "version": 1 }`)
- **Runtime DB schema**: `v23` (machine-local cache/runtime schema; not
  the user-facing compatibility contract)
- **App version**: `0.5.0` semver for the first supportable release

If a packaging layer later requires a four-part installer version (for
example `0.5.0.0`), derive it from the canonical app version rather than
making the four-part form the primary version identifier in the spec.
Until binary packaging exists, the canonical application version should
be stamped in the Python project metadata (`pyproject.toml`).

---

## Phase 1: Database & Configuration

**Goal:** Move the database out of the brain root and into the brain-sync
user directory. Simplify the schema to 4 tables.

### Changes

| Module | Change |
|--------|--------|
| `config.py` | Add `db_path()` → `~/.brain-sync/db/brain-sync.sqlite`. Ensure `db/` directory is created on first access. |
| `state.py` | Accept `db_path` parameter instead of deriving from brain root. Drop `documents`, `relationships`, `daemon_status` tables. Remove all v21 migrations — start fresh at schema integer `23` for the new runtime DB. Remove all references to `fetch_children`, `child_path`, and `manifest_version` from state helpers. |
| `__main__.py` | Resolve DB path via `config.db_path()` and pass to state initialisation. Move daemon status to `~/.brain-sync/daemon.json` (plain JSON, not SQLite). Remove `insights/` tree logic from daemon loop. |
| `commands/init.py` | Create exactly: `.brain-sync/brain.json`, `.brain-sync/sources/`, `knowledge/`, `knowledge/_core/`. Must NOT create: top-level `insights/`, `schemas/`, `.sync-state.sqlite`, `knowledge/.brain-sync/` (root-area managed state), `.gitignore`. |
| `mcp.py` | `BrainRuntime` resolves DB path from config, not brain root. |

### Brain manifest

`.brain-sync/brain.json` is the required root manifest. Its schema is
minimal per [SCHEMAS.md](SCHEMAS.md):

```json
{
  "version": 1
}
```

`brain-sync init` creates this file. `doctor --fix` recreates it if
missing. No other fields are added in v23 — the schema is intentionally
minimal.

### Init creates vs must-not-create

**Creates:**

- `.brain-sync/brain.json` — brain manifest
- `.brain-sync/sources/` — empty source directory
- `knowledge/` — knowledge tree root
- `knowledge/_core/` — global context directory (convenience, not
  invariant — a brain without `_core/` is valid)

**Must NOT create:**

- top-level `insights/` (v21 artifact)
- `schemas/` (v21 artifact — templates are internal to the package)
- `.sync-state.sqlite` (v21 artifact — DB lives in user directory)
- `knowledge/.brain-sync/` (root-area managed state — created on first
  regen, not on init)
- `.gitignore` (no runtime artifacts in brain root to exclude)

### DB Schema (v23, fresh)

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE sync_cache (
    canonical_id TEXT PRIMARY KEY,
    last_checked_utc TEXT,
    last_changed_utc TEXT,
    content_hash TEXT,
    metadata_fingerprint TEXT,
    next_check_utc TEXT,
    interval_seconds INTEGER
);
CREATE TABLE regen_locks (
    knowledge_path TEXT PRIMARY KEY,
    regen_status TEXT DEFAULT 'idle',
    regen_started_utc TEXT,
    owner_id TEXT,
    error_reason TEXT
);
CREATE TABLE token_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    operation_type TEXT,
    resource_type TEXT,
    resource_id TEXT,
    is_chunk INTEGER,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    total_tokens INTEGER,
    duration_ms INTEGER,
    num_turns INTEGER,
    success INTEGER,
    created_utc TEXT
);
```

`token_events` is machine-local observability data, durable for local
inspection, but not part of core brain-state recovery. Deleting it loses
telemetry history but does not affect brain function.

### Daemon Status

Replace the `daemon_status` DB table with `~/.brain-sync/daemon.json`:

```json
{
  "pid": 12345,
  "started_utc": "2026-03-15T08:00:00Z",
  "status": "running",
  "brain_root": "/path/to/brain"
}
```

Written atomically on daemon start, cleared on clean shutdown.
Stale PID detection: `os.kill(pid, 0)` on Unix, `ctypes.windll
.kernel32.OpenProcess` on Windows (no new dependency).

### Test impact

- `test_state.py` — rewrite for v23 schema (no migrations, 4 tables)
- `test_db_lifecycle.py` — rewrite for new DB path resolution
- E2E harness `brain.py` — `BrainFixture.db_path` points to
  `config_dir/db/brain-sync.sqlite` instead of `root/.sync-state.sqlite`
- All subprocess tests — `BRAIN_SYNC_CONFIG_DIR` already isolates; no change
  needed

---

## Phase 2: Manifests & Identity

**Goal:** Simplify source manifests and switch to YAML frontmatter.

### Source manifest filenames

Source manifests are named `<source_dir_id>.json` per
[SCHEMAS.md](SCHEMAS.md). The `source_dir_id` is the deterministic
filesystem-safe derivative of the canonical ID (type prefix letter +
provider ID, e.g. `c987654` for `confluence:987654`). It is normative
in v23 and is used consistently for:

- source manifest filenames
- per-source attachment directory names
- repair and rediscovery of source-owned managed artifacts

This is normative — the filename is the lookup key for
`read_all_source_manifests()`. If a file is misnamed, doctor reports
DRIFT and `--fix` renames it based on the `canonical_id` inside the JSON.

| Module | Change |
|--------|--------|
| `manifest.py` | Validate filename matches `canonical_id` on read. Add `expected_filename()` helper. |
| `commands/doctor.py` | Add DRIFT check: manifest filename vs `canonical_id`. `--fix` renames mismatched files. |

### Manifest schema changes

| Field | Action |
|-------|--------|
| `manifest_version` | Rename to `version` |
| `fetch_children` | **Delete from all code paths.** Not a manifest field, not a runtime state field, not a DB column. Becomes `--fetch-children` parameter on `add`/`sync` commands only. |
| `child_path` | **Delete from all code paths.** Same treatment as `fetch_children`. Becomes `--child-path` parameter on `add`/`sync` commands only. |
| All other fields | Unchanged |

These are not just "treated as parameters" — they must be fully removed
from durable state. Concrete cleanup:

| Module | What to remove/change |
|--------|----------------------|
| `manifest.py` | Delete `fetch_children` and `child_path` from `SourceManifest` dataclass. Rename `manifest_version` → `version`. `read_source_manifest()` silently ignores these fields if present in old files (read tolerance). All writes use v23 schema only. |
| `state.py` | Remove any `fetch_children`/`child_path` columns or references in `sync_cache` or state helpers. |
| `commands/sources.py` | `add` command accepts `--fetch-children` and `--child-path` as CLI parameters, passes them to `process_source()`. `reconcile_sources()` ignores unknown manifest fields. Remove any code that reads these from manifests. |
| `pipeline.py` | `process_source()` receives `fetch_children` and `child_path` as function parameters only. Remove any reads of these from `SourceManifest` or `SourceState`. |
| `__main__.py` | Remove any daemon-loop code that reads `fetch_children`/`child_path` from manifests or DB to pass to pipeline. These are only relevant in the `add`/`sync` command path. |

### Frontmatter switch

v23 writes YAML frontmatter instead of HTML comments. The `brain_sync_`
prefix prevents collision with user-authored frontmatter.

```yaml
---
brain_sync_source: confluence
brain_sync_canonical_id: confluence:987654
brain_sync_source_url: https://acme.atlassian.net/wiki/spaces/ACME/pages/987654
---
```

#### Write semantics (merge, not replace)

If a fetched markdown document already contains YAML frontmatter,
brain-sync must **merge** — upsert only the three `brain_sync_*` keys
and preserve all other existing keys. It must not replace the entire
frontmatter block.

Implementation: parse existing frontmatter as a dict, upsert
`brain_sync_source`, `brain_sync_canonical_id`, `brain_sync_source_url`,
serialise back.

#### Read semantics (tolerance)

All surfaces that read source identity must accept both YAML frontmatter
(v23) and legacy HTML comments (v21). This is read tolerance for
transition — new writes always use YAML.

#### All read/write/repair surfaces

| Module | Surface | Change |
|--------|---------|--------|
| `pipeline.py` | `prepend_managed_header()` | Write: merge `brain_sync_*` keys into existing frontmatter or create new block. |
| `pipeline.py` | `strip_managed_header()` | Read: parse both YAML frontmatter and HTML comments. |
| `pipeline.py` | `extract_source_id()` | Read: extract canonical ID from both formats. |
| `fileops.py` | `rediscover_local_path()` | Read: scan for YAML `brain_sync_canonical_id` (tier 2 identity resolution). Accept HTML comments as fallback. |
| `reconcile.py` | three-tier identity resolution | Read: tier 2 uses YAML frontmatter scan with HTML comment fallback. |
| `commands/doctor.py` | frontmatter identity check | Read: verify frontmatter matches manifest. Repair: rewrite HTML comments as YAML frontmatter via `--fix`. |

### Test impact

- `test_manifest.py` — update for new field names, verify old-format tolerance
- `test_pipeline.py` — update header assertions for YAML format
- `test_fileops.py` — update `rediscover_local_path` tests
- `test_reconcile_knowledge_tree.py` — update identity resolution tests

---

## Phase 3: Filesystem Layout

**Goal:** Co-locate insights under `knowledge/<area>/.brain-sync/` and
eliminate the separate `insights/` tree.

This is the largest change. It touches the most modules and eliminates the
most fragile v21 operation (mirror_folder_move).

### Layout change

**v21:**
```
brain-root/
├── knowledge/teams/platform/
│   ├── doc.md
│   └── _attachments/c987654/
├── insights/teams/platform/
│   ├── summary.md
│   ├── .regen-meta.json
│   └── journal/2026-03/2026-03-15.md
└── .sync-state.sqlite
```

**v23:**
```
brain-root/
├── knowledge/teams/platform/
│   ├── doc.md
│   └── .brain-sync/
│       ├── insights/
│       │   ├── summary.md
│       │   └── insight-state.json
│       ├── journal/
│       │   └── 2026-03/2026-03-15.md
│       └── attachments/
│           └── c987654/
│               └── a4736286723-diagram.png
└── .brain-sync/
    ├── brain.json
    └── sources/
```

### Module changes

| Module | Change |
|--------|--------|
| `sidecar.py` | Read/write `insight-state.json` at `knowledge/<area>/.brain-sync/insights/insight-state.json` instead of `insights/<area>/.regen-meta.json`. Rename `RegenMeta` → `InsightState` (or keep internal name, update paths). |
| `regen.py` | All insight path computation uses `knowledge/<area>/.brain-sync/insights/` instead of `insights/<area>/`. Summary reads/writes, journal appends — all updated. `compute_waves()` unchanged (still walks knowledge/). |
| `regen_lifecycle.py` | Insight path resolution updated. |
| `watcher.py` | **Remove `mirror_folder_move()`** entirely. Folder moves in knowledge/ automatically carry `.brain-sync/` subtrees. Watcher only needs to update manifest `materialized_path` and `target_path`, plus DB `sync_cache` and `regen_locks` paths. Exclude `.brain-sync/` from content change detection (dot-prefix handles this naturally). |
| `reconcile.py` | Orphan detection looks for `knowledge/<area>/.brain-sync/insights/` directories with no corresponding content in `knowledge/<area>/`. `clean_insights_tree()` updated for new paths. No more `insights/` tree scanning. |
| `fileops.py` | `EXCLUDED_DIRS` updated: remove `_attachments`, `_sync-context`. Add `.brain-sync` (or rely on dot-prefix filtering in `is_content_dir()`). `content_hash()` must skip `.brain-sync/` when hashing area content. |
| `fs_utils.py` | `find_all_content_paths()` skips `.brain-sync/` directories. `is_content_dir()` returns `False` for `.brain-sync`. |
| `attachments.py` | Write attachments to `knowledge/<area>/.brain-sync/attachments/<source_dir_id>/` instead of `knowledge/<area>/_attachments/<source_dir_id>/`. Cleanup is `rmtree` of source directory — no reference counting. Remove all `documents`/`relationships` table reads and cross-source reference counting logic. Update inline image URL rewriting to use new paths. |
| `commands/sources.py` | Source deregistration (second-stage missing protocol): `rmtree` the source's attachment directory under `.brain-sync/attachments/<source_dir_id>/`. Remove any `documents`/`relationships` DB cleanup. |
| `area_index.py` | `AreaIndex.build()` reads summaries from `knowledge/<area>/.brain-sync/insights/summary.md` instead of `insights/<area>/summary.md`. |
| `commands/init.py` | Stop creating top-level `insights/` directory. |
| `commands/doctor.py` | All insight path checks updated. Orphan detection uses new layout. |
| `__main__.py` | Remove all `insights/` tree logic from daemon loop. |
| `mcp.py` | Update any paths that reference `insights/` tree directly. |

### Root area (`knowledge/`)

`knowledge/` itself is a valid knowledge area per
[GLOSSARY.md](GLOSSARY.md#knowledge-area). It gets its own
`knowledge/.brain-sync/insights/` and `knowledge/.brain-sync/journal/`
when regen first runs (not on init).

The root area is the top of the wave topology — it regenerates last
and has no parent to propagate to. Like any other area, it regenerates
from its own readable files (if any) and child area summaries.

| Module | Change |
|--------|--------|
| `regen.py` | `compute_waves()` must include the root area (path `""` or `"."`) in the outermost wave. Regen input for root area: its own readable files (if any) + child area summaries. Insight path computation must handle the root: `knowledge/.brain-sync/insights/summary.md`. |
| `reconcile.py` | Orphan detection and hash-check must include the root area. Root `knowledge/.brain-sync/insights/` is valid whether the root has its own files, only child summaries, or both. |
| `commands/doctor.py` | Root area insight consistency check: `knowledge/.brain-sync/insights/insight-state.json` hashes must match. |
| `area_index.py` | `AreaIndex.build()` must include root area and read its summary from `knowledge/.brain-sync/insights/summary.md`. |
| `mcp.py` | Query and context tools must resolve the root area correctly. |
| `sidecar.py` | `read_insight_state()` / `write_insight_state()` must handle root path (empty string or `.`). |

### Context assembly (regen and explicit context loading)

v23 context sources must align to
[RULES.md — Regen Context Assembly](RULES.md#regen-context-assembly):

1. **Instructions** — bundled with the brain-sync package (not from
   `schemas/` on disk)
2. **Global context** — `knowledge/_core/` files
3. **Area files** — readable files in the area (leaf areas)
4. **Child summaries** — summaries from child areas (parent areas)
5. **Existing summary** — current summary for stability comparison

v21 artifacts to remove from context assembly:

| Module | What to remove |
|--------|---------------|
| `regen.py` | Remove any loading of `schemas/insights/` from brain root. Load templates from package resources only. Remove any loading of `insights/_core/summary.md` as a context source — global context comes from `knowledge/_core/` files, not from the old insights tree. |
| `mcp.py` | Remove any `insights/_core` references in context-loading surfaces. Raw global context comes from `knowledge/_core/` only. Deterministic query/search should not implicitly inject raw `_core`; `_core` participates there as a normal area via generated meaning and indexed artifacts. |

### Elimination list

These v21 constructs are removed entirely:

- `mirror_folder_move()` in `watcher.py`
- `FolderMove` dataclass in `watcher.py`
- `move_queue` in `KnowledgeEventHandler`
- `drain_moves()` method
- Top-level `insights/` directory creation
- `_attachments/` directory convention
- `_sync-context/` directory convention
- `documents` and `relationships` DB tables (Phase 1)
- `EXCLUDED_DIRS` entries for `_attachments`, `_sync-context`

### Test impact

This phase has the highest test impact. Nearly every test that touches
insights paths, the watcher, or reconciliation needs updating.

- `test_watcher_moves.py` — rewrite: no more mirror moves, test that
  manifest/DB paths update on folder move
- `test_regen.py` — update all insight path assertions
- `test_sidecar.py` — update paths to `insight-state.json`
- `test_reconcile_knowledge_tree.py` — update orphan detection paths
- `test_doctor.py` (unit + integration) — update insight path checks
- E2E `test_fs_moves.py` — rewrite: verify folder moves carry insights
- E2E `test_offline_reconcile.py` — update path assertions
- E2E `assertions.py` — `assert_summary_exists()`, `assert_no_orphan_insights()`,
  `assert_brain_consistent()` all updated for co-located layout
- E2E regression `test_folder_move_duplicate_insights.py` — the bug this
  tests (duplicate insights after mirror move) cannot occur in v23; keep
  test but update to verify co-located move correctness

---

## Phase 4: Templates & Context Assembly

**Goal:** Internalise regen templates. Remove `schemas/` from brain root.
Align context assembly to v23 spec.

### Changes

| Module | Change |
|--------|--------|
| `commands/init.py` | Remove schema deployment (`schemas/insights/` copy to brain root). Already updated in Phase 1 to not create `schemas/`. |
| `regen.py` | Load templates from package resources (`importlib.resources` or `__file__`-relative path) instead of reading from `schemas/insights/` on disk. Remove any loading of `insights/_core/summary.md` as a context source. Global context comes exclusively from `knowledge/_core/` files. |
| `mcp.py` | Remove any `insights/_core` references in explicit context-loading surfaces. Deterministic query/search should not treat raw `_core` specially. |
| Template files | Stay in `src/brain_sync/schemas/insights/` in the repo as source code but are loaded as package data, never deployed. Or move to `src/brain_sync/templates/` for clarity. |

### Test impact

- `test_phase0.py` — remove assertions about `schemas/` directory creation
- `test_commands.py` — update `init` assertions
- Integration `test_regen_pipeline.py` — verify regen works without
  on-disk schemas, verify context assembly uses `knowledge/_core/` (not
  `insights/_core`)

---

## Phase 5: Watcher & Reconciliation Polish

**Goal:** Simplify watcher and reconciliation now that the hard layout
changes are done.

### Watcher behaviour

With mirror moves eliminated, the watcher becomes simpler. The core
contract: **manifests must reflect filesystem truth before regen runs
for any affected area.**

Debounce is also the online reconciliation boundary per
[RULES.md](RULES.md#regen-queue): watcher events may batch during the
debounce window (30s default), but before regeneration starts for any
ready area the system must apply pending manifest and path updates so
durable state reflects filesystem truth.

#### Event handling

1. **File create/edit/delete** → queue containing area for regen
   (unchanged from v21)
2. **File move across areas** → queue both old and new areas for regen
3. **Folder move/rename** → batch manifest `materialized_path` and
   `target_path` updates + DB `sync_cache`/`regen_locks` path updates
   before regen runs
4. **Folder delete** → each contained synced source enters first-stage
   missing protocol (mark `missing` in manifest with timestamp)
5. **`.brain-sync/` events** → ignore (dot-prefix exclusion)

#### Online synced-file behaviour

| Event | Watcher response |
|-------|-----------------|
| Synced file deleted | Source enters first-stage missing protocol: manifest `status` → `missing`, `missing_since_utc` set. Area queued for regen. |
| Synced file moved to another area | Both old and new areas queued for regen. Manifest `materialized_path` and `target_path` updated before regen. |
| Synced file renamed | Area queued for regen. Manifest `materialized_path` updated. Identity preserved via frontmatter. |
| Folder moved/renamed containing synced files | All contained source manifests updated (batched). Both old and new area paths queued for regen. |

#### Module changes

| Module | Change |
|--------|--------|
| `watcher.py` | Remove `mirror_folder_move()`, `FolderMove`, `move_queue`, `drain_moves()`. Replace with `update_manifest_paths()` that batches manifest and DB path updates for moved folders. Add first-stage missing protocol for deleted synced files. Ensure all path updates complete before regen queue is drained. |
| `__main__.py` | Daemon loop: remove `drain_moves()` call. After `drain_events()`, run manifest path reconciliation for any folder moves detected, then `pop_ready()` for regen. The debounce window naturally provides the batching point. |
| `regen_queue.py` | No structural change — still receives area paths. But verify it handles both old and new area paths when a file moves across areas. |

### Reconciliation behaviour

Reconciliation is filesystem-authoritative. It must be able to rebuild
correct runtime state from three durable sources:

- source manifests (`.brain-sync/sources/*.json`)
- the knowledge tree (files and directories under `knowledge/`)
- per-area `insight-state.json` files

`regen_locks` is runtime coordination only — it is not a durable index
of areas. Reconciliation must not assume DB rows are complete or correct.

#### Algorithm

1. **Discover areas:** Walk `knowledge/` for all content directories
   (including root area). This is the authoritative set of areas.

2. **Prune orphan DB state:** For each `regen_locks` row where the
   knowledge path no longer exists as an area, delete the row. Clean
   `knowledge/<path>/.brain-sync/insights/` (delete insights, preserve
   journals). If the `.brain-sync/` directory contains only an empty
   `journal/` subtree after cleanup, leave it (journals are durable).

3. **Hash-check tracked areas:** For each area that has both a DB row
   and an `insight-state.json`, recompute content hash from disk. If
   changed, enqueue for regen.

4. **Detect new/moved areas:** For each content directory not in DB,
   check for existing `.brain-sync/insights/` (evidence of prior regen
   — likely a moved area). Enqueue for regen.

5. **Manifest reconciliation:** For each source manifest, verify
   `materialized_path` file exists. If not, run three-tier identity
   resolution:
   - Tier 1: direct path check
   - Tier 2: frontmatter identity scan (YAML, with HTML comment fallback)
   - Tier 3: canonical prefix glob
   If found at a new path, update manifest `materialized_path` and
   `target_path`. If not found, enter first-stage missing protocol.
   If already `missing` from a prior reconciliation pass, deregister:
   delete manifest, clean DB rows, remove source attachments.

6. **Root area:** Include `knowledge/` itself in steps 2–4. The root
   area path is `""` (empty string). It may contain readable files of
   its own and/or derive meaning from child area summaries. Its insight
   state lives at `knowledge/.brain-sync/insights/insight-state.json`.

7. **Rebuild sync_cache:** For any manifest whose `canonical_id` has no
   `sync_cache` row, seed a row from the manifest's `sync_hint`.

### Module changes

| Module | Change |
|--------|--------|
| `watcher.py` | See watcher behaviour above. |
| `reconcile.py` | Rewrite to filesystem-authoritative algorithm above. Remove all `insights/` tree references. Add root area handling. |
| `__main__.py` | Daemon loop: remove `drain_moves()`. After `drain_events()`, run manifest reconciliation for folder moves, then `pop_ready()`. |

### Test impact

- `test_reconcile_knowledge_tree.py` — rewrite for filesystem-authoritative
  algorithm, include root area
- `test_reconcile.py` (integration) — update for co-located layout, add
  DB-rebuild-from-disk test
- `test_reconcile_state.py` (integration) — update path assertions
- `test_watcher_moves.py` — rewrite for batched manifest updates, online
  synced file delete/move behaviour

---

## Phase 6: Doctor & Recovery

**Goal:** Update doctor to validate v23 invariants.

### Doctor checks (v23)

| Check | Severity | Description |
|-------|----------|-------------|
| Root structure | DRIFT | `knowledge/` and `.brain-sync/` exist at brain root |
| Brain manifest | DRIFT | `.brain-sync/brain.json` exists and is valid `{"version": 1}` |
| Source manifests | DRIFT | Each `.brain-sync/sources/*.json` is valid, has required fields |
| Manifest filename | DRIFT | Each manifest filename matches `canonical_id` inside the JSON |
| Materialized paths | DRIFT | Each manifest's `materialized_path` resolves to a file |
| Frontmatter identity | DRIFT | Each synced file has YAML frontmatter matching its manifest (HTML comments = DRIFT, repairable) |
| Insight consistency | DRIFT | Each `insight-state.json` has hashes matching disk content |
| Orphan insights | DRIFT | No `.brain-sync/insights/` without corresponding content in the area |
| Root area consistency | DRIFT | `knowledge/.brain-sync/insights/` consistent if present |
| Reserved namespace misuse | DRIFT | User content found inside `.brain-sync/` directories |
| Attachment consistency | DRIFT | Each active source's attachment directory exists if `sync_attachments=true` and attachments have been synced |
| DB consistency | DRIFT | DB is reachable and schema version matches |
| Journal safety | — | Journals are never deleted by doctor (invariant, not a check) |

#### Reserved namespace misuse

User content found inside `.brain-sync/` directories is classified as
DRIFT per the [GLOSSARY.md](GLOSSARY.md#doctor) severity model.
`doctor --fix` must **never** move or delete user content in
`.brain-sync/`. The message warns that the file may be overwritten or
deleted by brain-sync operations. Stale managed artifacts (e.g. orphan
`insight-state.json` with no corresponding summary) may still be
repaired/cleaned by `--fix`.

### Repairs

| Repair | `--fix` action |
|--------|----------------|
| Missing `brain.json` | Recreate with `{"version": 1}` |
| Misnamed manifest file | Rename to match `canonical_id` inside the JSON |
| Missing DB | Recreate from manifests and insight state |
| Stale `materialized_path` | Run three-tier resolution, update manifest |
| HTML comment frontmatter | Rewrite as YAML frontmatter (merge, preserving other keys) |
| Orphan insights | Delete insights (preserve journals) |
| Stale DB rows | Delete rows for paths that no longer exist |
| Reserved namespace misuse | Report only — never auto-fix user content |

### Test impact

- `test_doctor.py` (unit + integration) — rewrite for v23 checks
- `test_doctor_cli.py` (system) — update CLI assertions

---

## Module Impact Summary

Modules sorted by change magnitude:

| Impact | Module | Nature of change |
|--------|--------|-----------------|
| **Heavy** | `watcher.py` | Remove mirror_folder_move, simplify to path updates |
| **Heavy** | `regen.py` | All insight paths change |
| **Heavy** | `state.py` | New DB location, drop 3 tables, fresh schema |
| **Heavy** | `reconcile.py` | New layout, simplified orphan detection |
| **Heavy** | `sidecar.py` | New file name and path |
| **Medium** | `pipeline.py` | YAML frontmatter, `fetch_children` as parameter |
| **Medium** | `fileops.py` | Updated exclusions, new attachment paths |
| **Medium** | `commands/doctor.py` | New invariant checks |
| **Medium** | `commands/init.py` | No schemas deployment, no insights/ creation |
| **Medium** | `commands/sources.py` | CLI flags for fetch_children/child_path |
| **Medium** | `attachments.py` | New attachment paths under `.brain-sync/` |
| **Medium** | `area_index.py` | Read summaries from new location |
| **Medium** | `manifest.py` | Field renames, drop operational flags |
| **Light** | `config.py` | Add `db_path()` |
| **Light** | `fs_utils.py` | Skip `.brain-sync/` in content discovery |
| **Light** | `__main__.py` | Remove insights/ tree logic, new DB path |
| **Light** | `mcp.py` | Updated path resolution in BrainRuntime |
| **Light** | `regen_queue.py` | No change (operates on knowledge paths) |
| **Light** | `regen_lifecycle.py` | Path updates only |
| **Light** | `scheduler.py` | No change |
| **Light** | `retry.py` | No change |
| **Light** | `converter.py` | No change |
| **Light** | `sources/*` | No change (adapters are layout-agnostic) |
| **Light** | `llm/*` | No change |
| **Light** | `logging_config.py` | No change |
| **None** | `confluence_rest.py` | No change |
| **None** | `docx_converter.py` | No change |
| **None** | `token_tracking.py` | No change (table unchanged) |

---

## Dependency Order

Phases must be executed in order. Within each phase, changes can proceed
in parallel where there are no import dependencies.

```
Phase 1 (DB & Config)
  ↓
Phase 2 (Manifests & Identity)
  ↓
Phase 3 (Filesystem Layout)  ← largest, most tests affected
  ↓
Phase 4 (Templates)
  ↓
Phase 5 (Watcher & Reconciliation Polish)
  ↓
Phase 6 (Doctor & Recovery)
```

Phase 1 and Phase 2 are nearly independent and could overlap, but
Phase 1 first is cleaner because Phase 2's integration tests need the new
DB location.

Phase 4 is independent of Phase 3 in code but logically follows it (no
point internalising templates while insights/ tree still exists).

---

## Test Strategy

### Approach

1. **Rewrite or remove, don't skip** — where a v21 test encodes invalid
   v23 architecture (e.g. mirror_folder_move, `insights/` tree paths,
   `documents`/`relationships` table queries), rewrite it for v23 or
   delete it. Use `@pytest.mark.skip(reason="v21 layout")` only for
   tests whose v21 assertion is valid but the code path hasn't been
   migrated yet within a phase. All skips must be resolved before the
   phase is complete.

2. **Equivalent coverage** — every v21 test that is removed must have a
   v23 equivalent that covers the same invariant in the new layout.

3. **Phase-gated testing** — each phase must pass all tests before
   proceeding. Run `pytest -n auto -m "unit or integration or external or
   mcp" --timeout=30` after each phase.

4. **E2E harness first** — update `BrainFixture`, `assert_brain_consistent()`,
   and `assert_summary_exists()` before updating individual E2E tests.
   These are the foundation.

5. **Regression tests preserved** — E2E regressions
   (`test_content_hash_redundant_regen.py`,
   `test_folder_move_duplicate_insights.py`) are rewritten for v23
   layout. The invariants they protect still matter.

6. **Version-aware builders, not static private brains** — the test
   suite should construct representative brains from code. Do not depend
   on `brain-example/` or other private/sensitive directories.

7. **Compatibility tests are separate from implementation tests** — add
   a dedicated compatibility layer that expresses what app version,
   brain format version, and runtime DB schema are supported together.

### Version-aware test foundation

The current suite is broad, but much of its filesystem setup is
implicitly v21-shaped (`.sync-state.sqlite`, top-level `insights/`,
legacy fixture trees). v23 should use this refactor to establish a more
explicit test foundation for ongoing format evolution.

Recommended foundation:

- Add builder-style helpers that synthesize brains from code rather than
  copying fixed fixture directories.
- Make the builder API version-aware from the start, even if only
  `Brain Format v1.0` is supported initially.
- Keep private real-world exemplar brains out of automated tests.

Suggested test primitives:

- `build_brain_v1(root, scenario=...)` — create a conforming Brain
  Format v1.0 brain
- `build_drifted_brain_v1(root, drift=...)` — create a valid v1.0 brain
  plus repairable drift for doctor/rebuild tests
- `build_legacy_pre_v1_brain(root, scenario=...)` — create a
  representative unsupported pre-v23 layout for explicit rejection or
  re-init guidance tests

Suggested scenario shapes:

- empty initialized brain
- root-area content
- `_core/` present
- nested areas
- synced source with frontmatter
- area with attachments
- area with journals
- moved/renamed synced file
- offline folder move
- missing source / second-stage deregistration

Suggested compatibility assertions:

- `assert_brain_format_v1(root)` — portable filesystem invariants hold
- `assert_runtime_rebuildable(root)` — DB can be deleted and rebuilt
  without changing portable brain state
- `assert_doctor_healthy_v1(root)` — doctor reports healthy or only
  explicitly expected findings
- `assert_unsupported_legacy_brain(root)` — unsupported pre-v23 inputs
  fail clearly and direct the user toward re-init rather than silently
  mutating unknown layouts

### Compatibility suite direction

Add a dedicated compatibility test layer (for example `tests/compat/`)
with the following responsibilities:

- prove that a fresh `brain-sync init` brain conforms to Brain Format
  v1.0
- prove that a drifted Brain Format v1.0 brain can be repaired by
  `doctor --fix` / rebuild paths
- prove that deleting runtime state does not invalidate a Brain Format
  v1.0 brain
- prove that unsupported pre-v23 layouts are detected as unsupported for
  upgrade rather than being mistaken for v1.0 brains

This compatibility layer should become the home for future
format-to-format upgrade tests once Brain Format v2+ exists.

### Required v23 test coverage

These tests must exist before the refactor is complete. They may be
written incrementally within each phase.

| Area | Tests |
|------|-------|
| Root area | Regen produces `knowledge/.brain-sync/insights/summary.md` from own readable files (if any) and child summaries. Reconciliation detects offline changes in root area. Doctor validates root area insight consistency. |
| `brain.json` | `brain-sync init` creates `.brain-sync/brain.json` with `{"version": 1}`. Doctor detects missing `brain.json` and `--fix` recreates it. |
| Manifest filename | Doctor detects misnamed manifest file (DRIFT). `--fix` renames based on `canonical_id`. |
| YAML frontmatter merge | Materialization into a file with existing frontmatter preserves non-`brain_sync_*` keys. Upsert only the three `brain_sync_*` keys. |
| Identity resolution tiers | Tier 1: `materialized_path` resolves. Tier 2: frontmatter scan finds moved file. Tier 3: canonical prefix glob finds renamed file. Verify HTML comment fallback in tier 2. |
| Online watcher: synced file delete | File deletion triggers first-stage missing protocol in manifest. |
| Online watcher: synced file move | Move across areas queues both areas for regen and updates manifest paths. |
| Online watcher: folder move | Manifest path updates batched before regen. Insights travel with folder. |
| DB rebuild from disk | Delete DB. Reconciliation rebuilds `sync_cache` from manifests and `regen_locks` from knowledge tree + `insight-state.json` files. |
| Context assembly | Regen loads instructions from package (not `schemas/` on disk). No `insights/_core` in context. `knowledge/_core/` files loaded as global context. |
| Attachment lifecycle | Attachments written to `.brain-sync/attachments/<source_dir_id>/`. Source deregistration `rmtree`s the directory. No reference counting. Inline image URLs use new paths. |
| Init creates/not-creates | Verify init creates `brain.json`, `sources/`, `knowledge/`, `knowledge/_core/`. Verify init does NOT create `insights/`, `schemas/`, `.sync-state.sqlite`, `knowledge/.brain-sync/`, `.gitignore`. |
| Compatibility baseline | `build_brain_v1(...)` or equivalent harness helper produces a valid Brain Format v1.0 brain. `assert_brain_format_v1(...)` passes on it. |
| Drift repair baseline | `build_drifted_brain_v1(...)` plus `doctor --fix` returns to a valid Brain Format v1.0 state without losing user knowledge. |
| Unsupported legacy detection | Representative pre-v23 layouts are rejected or directed to re-init; they are not silently treated as valid Brain Format v1.0 brains. |
| Runtime rebuild contract | A valid Brain Format v1.0 brain remains valid after deleting runtime DB state and rebuilding it. |

### Test architecture changes required early

The following test foundation work should happen before broad feature
rewrites, because many existing tests currently encode the v21 layout:

- update `tests/e2e/harness/brain.py` to stop hard-coding
  `.sync-state.sqlite` and top-level `insights/`
- update `tests/e2e/harness/assertions.py` so brain-consistency checks
  validate Brain Format v1.0 layout
- move from copied fixture directories toward builder-generated brains
  for new v23 coverage
- keep a small number of static fixtures only where byte-for-byte legacy
  regression setup is valuable

### Test count estimate

| Category | Approximate count |
|----------|-------------------|
| Tests to rewrite (path/layout changes) | ~30-40 |
| Tests to remove (v21-only constructs) | ~10-15 |
| Tests unchanged | ~400+ |
| New tests (v23-specific, see above) | ~15-20 |

The majority of tests (unit tests for adapters, converter, scheduler,
retry, token tracking, config, etc.) are layout-agnostic and need no
changes.

---

## Resolved Design Decisions

These questions were raised during pre-planning and have been resolved.
They are recorded here for context.

| Decision | Resolution |
|----------|-----------|
| Source manifest filename convention | Normative. Filename must be `<source_dir_id>.json`. Doctor detects mismatches as DRIFT, `--fix` renames. |
| Watcher manifest update timing | Watcher events may batch during debounce. An internal reconcile pass within the debounce window is acceptable. Manifests must reflect filesystem truth before regen runs. |
| Frontmatter merge vs replace | Merge. Upsert only `brain_sync_*` keys, preserve all other existing frontmatter. |
| Root-area managed state on init | No. `brain-sync init` does not create `knowledge/.brain-sync/`. Created on first regen. |
| Reserved namespace misuse severity | DRIFT (per GLOSSARY.md severity model). `doctor --fix` must never move/delete user content in `.brain-sync/`. |
| Attachment orphan handling | `rmtree` unconditionally on source deregistration. `.brain-sync/` is a managed namespace. |
| Journal preservation on area deletion | Accept the risk. System preserves journals during its own cleanup but cannot protect against user `rm -rf` of the area directory. Already stated in RULES.md managed files table. |
| Schema version numbering | `1`. Clean break. The v21 migration chain is deleted. `brain.json` version (also `1`) tracks brain format independently. |
| Insight state file name | `insight-state.json` (no dot-prefix). Already inside a managed namespace. Visibility aids debugging. |
| Daemon status format | JSON file at `~/.brain-sync/daemon.json` with `pid`, `brain_root`, `started_utc`. Stale PID detection via stdlib (no new dependencies). |
| `_core/` regen behaviour | `_core/` is a normal knowledge area. If it qualifies as an area (contains readable files), it gets normal regen/reconcile behaviour and co-located managed state (`knowledge/_core/.brain-sync/`). Its content is also injected as global context into all other areas' regen prompts. The summary is useful for `area_index` queries. |
| `token_events` table role | Machine-local observability data. Durable for local inspection but not part of core brain-state recovery. Deleting it loses telemetry history but does not affect brain function. |

## Implementation Checklist Items

These are concrete audit/verification tasks that must be completed during
implementation but are not open design questions.

### `.brain-sync/` exclusion from content discovery

`content_hash()` in `fileops.py` hashes all readable files in an area.
With `.brain-sync/` co-located, it must be excluded from hashing,
content discovery, regen scanning, and watcher event processing.

Audit all directory enumeration callers in `fileops.py` and `fs_utils.py`
to verify `.brain-sync` is in the exclusion set explicitly — do not rely
solely on dot-prefix conventions. (`Path.iterdir()` returns dotfiles on
all platforms.) The same inclusion rule must be used consistently across
discovery, hashing, regeneration, and reconciliation per the
[readable file](GLOSSARY.md#readable-file) definition.

---

## Deferred Concerns

These items are out of scope for v23 but are noted for future reference.

### Multi-brain support

The user directory (`~/.brain-sync/`) currently assumes one brain per
machine. `config.json` stores a single `brain_root`. Single brain is
sufficient for v23. `brain.json` schema stays `{"version": 1}` — no
`brain_id` field. If multi-brain is needed later, options include
keying `config.json` and DB paths by a brain identifier.

---

## Architectural Notes

### What stays the same

- Source adapter pattern and registry
- LLM backend abstraction
- Regen queue (debounce, cooldown, rate limit)
- Wave topology (depth-first, dirty propagation)
- Stability guard (>0.97 similarity)
- Scheduler (heap-based, adaptive tiers)
- Token tracking
- Retry with circuit breaker
- MCP server interface (tool names and parameters)
- CLI command names and flags (except manifest-related additions)

### What gets simpler

- No mirror_folder_move (the most fragile v21 operation)
- No reference counting for attachments
- No `documents` or `relationships` DB tables
- No schema deployment to brain root
- No `_attachments/` or `_sync-context/` conventions
- No `.gitignore` in brain root
- Single reserved namespace (`.brain-sync/`) everywhere

### What gets harder (temporarily)

- Phase 3 (filesystem layout) touches many modules simultaneously
- Test rewriting is labour-intensive but mechanical
- The co-located `.brain-sync/` requires careful exclusion from content
  discovery — any missed code path could hash or regen managed files

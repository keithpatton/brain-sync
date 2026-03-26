# PLAN: Structural Health Phase 1 (brain_sync_tree)

## Problem

The current brain-sync surfaces are good at content navigation and integrity
checking, but they do not give a client reasoning agent one complete,
trustworthy view of the semantic knowledge-area tree.

Today:

- `brain_sync_get_context` and `brain_sync_query` return truncated area
  listings designed for orientation and drill-down, not whole-tree reasoning.
- `brain_sync_open_area` expands one area at a time.
- `doctor` checks integrity and recoverability of the brain contract, not
  whether the visible tree is shaped in a way that supports the user's
  thinking.

This means an agent cannot cheaply answer:

- "What does my brain look like right now?"
- "Which visible folders are just scaffolding?"
- "Where are the synced files versus manual files?"
- "Which branches have brain-sync managed data such as insights or journals?"

For this first phase, the product need is narrower than "structural health":
provide one complete tree command with enough metadata for a client reasoning
agent to reason about the brain's structure.

## Goals

1. Expose the full semantic knowledge-area tree under `knowledge/` in one
   transport-neutral application call.
2. Provide both MCP and CLI parity for that tree surface.
3. Include enough per-node metadata for an external reasoning agent to reason
   about structure, file mix, and managed brain-sync data without needing
   follow-up discovery walks.
4. Keep the command read-only, deterministic, and cheap. No LLM calls, no
   mutations.

## Non-Goals

- Structural linting or advisory findings in this phase.
- Extending `doctor` in this phase.
- Taxonomy parsing or taxonomy-based checks in this phase.
- Auto-fixing or suggested actions in this phase.
- Dedicated cache design in this phase. If profiling later shows need, caching
  can be added in a follow-on revision.

## Design Decisions

These decisions were made by the brain owner during planning and are not open
for re-evaluation by the reviewer:

1. **Phase 1 is tree only.** `brain_sync_health` and any structural heuristics
   are deferred to a later revision. This plan is purely about the baseline
   tree command and CLI/MCP parity.

2. **The tree models the semantic knowledge-area tree only.** It follows the
   existing rules and implementation semantics for directories under
   `knowledge/` that participate in regeneration. Truly empty structural
   folders are out of scope for phase 1.

3. **The phase-1 tree should reuse existing semantic helpers as much as
   practical.** The design should build on current knowledge-area discovery and
   avoid introducing a second independent tree-definition policy.

4. **Synced-file context uses a state breakdown, not one aggregate count.**
   Per-node synced file counts must distinguish `awaiting`, `materialized`,
   `stale`, and `missing`.

5. **Counts are direct, not cumulative.** Per-node folder and file counts are
   for direct children of that folder only. Reasoning agents can derive
   subtree totals if needed.

6. **No taxonomy in v1.** `taxonomy.md` is out of scope for this phase.

7. **Application module placement: `application/structure.py`.** The
   transport-neutral tree export lives in a new application module. This keeps
   it separate from `browse.py`, which is optimized for capped content
   navigation, while avoiding confusion with the existing brain-layer
   `brain/tree.py` primitives.

## Design

### Phase 1 Scope

Deliver one new transport-neutral application function plus one MCP tool and
one CLI command:

- `tree_brain(root: Path) -> TreeResult`
- MCP: `brain_sync_tree`
- CLI: `brain-sync tree`

No `health_brain`, no health severities, no structural findings.

### Tree Contract

The tree represents the semantic knowledge-area tree under `knowledge/`:

- include the root `knowledge/` node
- include `_core/`
- include parent folders that qualify because they have descendant knowledge
  areas
- exclude directories that contain neither readable files nor descendant
  knowledge areas
- exclude `.brain-sync/` and other hidden dot-directories through the existing
  knowledge-area discovery rules

This means the phase-1 tree is the tree brain-sync already reasons over for
regen and summaries, rather than a broader filesystem skeleton.

### Data Model

```python
@dataclass(frozen=True)
class SyncedFileCounts:
    awaiting: int
    materialized: int
    stale: int
    missing: int


@dataclass(frozen=True)
class InsightStats:
    artifact_names: list[str]       # user-facing insight artifacts, e.g. ["summary.md"]
    summary_present: bool
    last_regen_utc: str | None
    content_hash: str | None
    structure_hash: str | None


@dataclass(frozen=True)
class JournalStats:
    entry_count: int
    first_entry_date: str | None    # YYYY-MM-DD if known
    last_entry_date: str | None     # YYYY-MM-DD if known


@dataclass(frozen=True)
class TreeNode:
    path: str                       # knowledge-relative; "" for knowledge root
    name: str                       # "knowledge" for root, else folder basename
    depth: int                      # 0 for knowledge root
    child_folder_count: int         # direct visible child folders
    manual_file_count: int          # direct readable non-synced files
    synced_files: SyncedFileCounts  # direct synced file counts by manifest state
    insights: InsightStats
    journals: JournalStats


@dataclass(frozen=True)
class TreeResult:
    nodes: list[TreeNode]
    total_nodes: int
    max_depth: int
```

### Semantics Of Counts

#### `child_folder_count`

Count direct child knowledge-area folders only:

- include direct child directories that qualify as knowledge areas
- exclude empty structural folders that are not knowledge areas
- rely on the existing content-discovery semantics used by current regen/query
  helpers

#### `manual_file_count`

Count direct readable files in the folder that are **not** synced managed
markdown files.

Implementation must not rely on `is_readable_file()` alone, because synced
markdown files also satisfy that predicate. Managed synced markdown must be
excluded by checking for managed identity, for example via
`extract_source_id(path)`.

#### `synced_files`

Count registered synced sources whose manifest `target_path` equals the node
path. Use the manifest `knowledge_state` breakdown:

- `awaiting`
- `materialized`
- `stale`
- `missing`

This is a registry-level state breakdown, not an "actually present files on
disk" count. The distinction is intentional and must be documented in the tool
description.

### Managed Brain-Sync Data

#### Insights

Expose whether user-facing insight artifacts exist for the folder.

For v1:

- `summary_present` reflects whether `summary.md` exists
- `artifact_names` lists user-facing insight artifact filenames in the
  area's `insights/` directory
- `artifact_names` must exclude `insight-state.json`, because that file is
  portable baseline state rather than a user-facing insight artifact
- `last_regen_utc`, `content_hash`, and `structure_hash` come from
  `read_all_regen_meta`

This design leaves room for future insight artifact expansion without changing
the tree command from a boolean-only shape.

#### Journals

Expose whether journals exist and a lightweight summary of journal coverage:

- `entry_count`
- `first_entry_date`
- `last_entry_date`

For v1, dates are derived conservatively from journal filenames where they
match the current `YYYY-MM-DD.md` pattern. If no dated entries are found,
`first_entry_date` and `last_entry_date` are `None`.

### Existing Helper Reuse

Phase 1 should reuse the existing semantic tree helpers as much as practical.

In particular:

- `find_all_content_paths()` already discovers the bottom-up semantic
  knowledge-area tree
- `get_child_dirs()` already returns direct child directories that participate
  in content discovery

`tree_brain()` should build on those existing semantics rather than inventing a
new folder-policy layer in phase 1.

### Orchestration

```python
def tree_brain(root: Path) -> TreeResult:
    """Return the full semantic knowledge-area tree under knowledge/ with per-node metadata."""
```

Implementation outline:

1. Resolve `knowledge/` root.
2. Preload source manifests with `read_all_source_manifests(root)`.
3. Build a `{target_path: SyncedFileCounts}` index from manifests.
4. Preload regen sidecars with `read_all_regen_meta(knowledge_root(root))`.
5. Discover the semantic knowledge-area paths using existing helpers.
6. For each node:
   - count direct child knowledge-area folders
   - count direct manual files
   - attach direct synced-file state counts
   - attach insight stats
   - attach journal stats
7. Return nodes in depth-first order, alphabetical within siblings.

### MCP Surface

Add a new MCP tool in `interfaces/mcp/server.py`:

```python
@server.tool(
    name="brain_sync_tree",
    description=(
        "Return the full visible folder skeleton under knowledge/ with per-node metadata. "
        "Read-only. Returns the semantic knowledge-area tree used by brain-sync "
        "for regeneration and summaries, with direct manual file counts, direct "
        "synced-file counts by state, and available "
        "brain-sync managed data such as insights and journal coverage."
    ),
)
def brain_sync_tree(ctx: Context) -> dict:
    ...
```

The result shape is:

- `status`
- `nodes`
- `total_nodes`
- `max_depth`

### CLI Surface

Add a new CLI command:

```text
brain-sync tree
```

Default output:

- indented tree
- one line per folder
- compact metadata per line

Example shape:

```text
knowledge/  folders=3 manual=0 synced[a=0,m=0,s=0,ms=0] insights[summary=no,artifacts=0,last_regen=-] journals[count=0,first=-,last=-]
  _core/  folders=2 manual=1 synced[a=0,m=0,s=0,ms=0] insights[summary=yes,artifacts=1,last_regen=2026-03-27T08:15:00+00:00] journals[count=0,first=-,last=-]
  initiatives/  folders=2 manual=0 synced[a=0,m=0,s=0,ms=0] insights[summary=yes,artifacts=1,last_regen=2026-03-27T08:17:00+00:00] journals[count=2,first=2026-03-20,last=2026-03-27]
    platform/  folders=1 manual=0 synced[a=0,m=2,s=1,ms=0] insights[summary=yes,artifacts=1,last_regen=2026-03-27T08:17:00+00:00] journals[count=1,first=2026-03-27,last=2026-03-27]
      aaa/  folders=2 manual=1 synced[a=1,m=3,s=0,ms=1] insights[summary=yes,artifacts=1,last_regen=2026-03-26T19:02:00+00:00] journals[count=3,first=2026-03-11,last=2026-03-26]
```

Optional machine-readable output:

```text
brain-sync tree --json
```

Representative JSON shape:

```json
{
  "status": "ok",
  "total_nodes": 5,
  "max_depth": 3,
  "nodes": [
    {
      "path": "",
      "name": "knowledge",
      "depth": 0,
      "child_folder_count": 3,
      "manual_file_count": 0,
      "synced_files": {
        "awaiting": 0,
        "materialized": 0,
        "stale": 0,
        "missing": 0
      },
      "insights": {
        "artifact_names": [],
        "summary_present": false,
        "last_regen_utc": null
      },
      "journals": {
        "entry_count": 0,
        "first_entry_date": null,
        "last_entry_date": null
      }
    },
    {
      "path": "initiatives/platform/aaa",
      "name": "aaa",
      "depth": 3,
      "child_folder_count": 2,
      "manual_file_count": 1,
      "synced_files": {
        "awaiting": 1,
        "materialized": 3,
        "stale": 0,
        "missing": 1
      },
      "insights": {
        "artifact_names": ["summary.md"],
        "summary_present": true,
        "last_regen_utc": "2026-03-26T19:02:00+00:00"
      },
      "journals": {
        "entry_count": 3,
        "first_entry_date": "2026-03-11",
        "last_entry_date": "2026-03-26"
      }
    }
  ]
}
```

Notes on the compact CLI format:

- `a`, `m`, `s`, and `ms` mean `awaiting`, `materialized`, `stale`, and
  `missing`
- `artifacts` is the number of user-facing insight artifacts in the
  `insights/` directory
- `-` means the field is absent or unknown

### Caching

Dedicated caching is out of scope for this revision.

Phase 1 should implement the tree command directly and prove correctness
first. If later profiling shows the MCP surface needs caching, a follow-on
revision can add a stale-aware cache with explicit invalidation rules.

## Sequencing

1. Add the application-layer data model and `tree_brain()` in
   `application/structure.py`.
2. Add MCP tool `brain_sync_tree`.
3. Add CLI command `brain-sync tree` with human-readable and `--json`
   output.
4. Add unit and integration coverage.

## Acceptance Criteria

1. `brain_sync_tree` returns the complete semantic knowledge-area tree under
   `knowledge/` with no truncation.
2. The tree includes `_core/`, the root `knowledge/` node, and parent folders
   that qualify via descendant knowledge areas.
3. The tree excludes directories that contain neither readable files nor
   descendant knowledge areas.
4. Every node includes:
   - `path`
   - `name`
   - `depth`
   - `child_folder_count`
   - `manual_file_count`
   - synced-file counts by state
   - insight stats
   - journal stats
5. `manual_file_count` excludes synced managed markdown files.
6. Synced-file counts are broken down by `awaiting`, `materialized`, `stale`,
   and `missing`, using manifest state.
7. `insights.summary_present` is correct and `insights.artifact_names`
   excludes `insight-state.json`.
8. `journals.entry_count`, `first_entry_date`, and `last_entry_date` are
   correct for current journal layout.
9. CLI command `brain-sync tree` exists and supports `--json`.
10. MCP tool `brain_sync_tree` exists and returns the same underlying data
    model as the CLI JSON form.
11. The implementation is read-only: no mutations to the brain, runtime DB,
    or filesystem.

## Risks

- **Semantic-tree-only scope may omit empty scaffolding folders**: this is an
  intentional simplification for phase 1. Mitigation: document that
  `brain_sync_tree` returns the semantic knowledge-area tree, not every visible
  empty folder on disk.
- **Manual-file miscounting**: synced markdown looks like normal readable
  content. Mitigation: explicitly exclude managed synced files using managed
  identity extraction.
- **Manifest-state interpretation**: `missing` and `awaiting` are registered
  source states, not on-disk-present file counts. Mitigation: document the
  state semantics in the tool contract.
- **Journal scan cost**: recursive journal counting adds I/O. Mitigation:
  acceptable for phase 1; optimize later only if profiling shows need.
- **Caching pressure in long-lived MCP sessions**: repeated whole-tree calls
  may become expensive for large brains. Mitigation: defer cache design until
  there is actual performance evidence.

## Authoritative Inputs

- `docs/GLOSSARY.md` and `docs/RULES.md` for knowledge-area semantics and
  managed namespace rules
- `docs/brain/SCHEMAS.md` for manifest and insight-state schema semantics
- `src/brain_sync/application/browse.py` for current capped area-listing
  behavior and walk-order precedent
- `src/brain_sync/brain/tree.py` for existing knowledge-area discovery
  primitives
- `src/brain_sync/brain/managed_markdown.py` for synced-file identity
  detection
- `src/brain_sync/brain/manifest.py` for source manifest and `target_path`
  semantics
- `src/brain_sync/brain/sidecar.py` for portable insight-state loading
- `src/brain_sync/brain/layout.py` for managed directory layout
- `src/brain_sync/interfaces/mcp/server.py` for MCP tool registration patterns
- `src/brain_sync/interfaces/cli/parser.py` and
  `src/brain_sync/interfaces/cli/handlers.py` for CLI command patterns

---

This file is not approval. The next required action is for a reviewer to
evaluate this plan revision and produce either a review artifact (if changes
are required) or an approval artifact (if acceptable).

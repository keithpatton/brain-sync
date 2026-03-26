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
  whether the knowledge-area tree is shaped in a way that supports the user's
  thinking.

This means an agent cannot cheaply answer:

- "What does my brain look like right now?"
- "Where are the synced files versus manual files?"
- "Which branches have brain-sync managed data such as insights or journals?"

For this first phase, the product need is narrower than "structural health":
provide one complete tree command with enough metadata for a client reasoning
agent to reason about the brain's semantic structure.

This revision also optimizes the public wire contract for token efficiency. The
goal is to preserve reasoning quality while reducing payload size by omitting
fields whose default meaning can be inferred safely and explicitly.

## Goals

1. Expose the full semantic knowledge-area tree under `knowledge/` in one
   transport-neutral application call.
2. Provide both MCP and CLI parity for that tree surface.
3. Include enough per-node metadata for an external reasoning agent to reason
   about structure, file mix, and managed brain-sync data without needing
   follow-up discovery walks.
4. Keep the command read-only, deterministic, and cheap. No LLM calls, no
   mutations.
5. Minimize wire size without degrading reasoning ability by using a sparse
   contract with explicit default semantics.

## Non-Goals

- Structural linting or advisory findings in this phase.
- Extending `doctor` in this phase.
- Taxonomy parsing or taxonomy-based checks in this phase.
- Auto-fixing or suggested actions in this phase.
- Returning raw filesystem folders that are not semantic knowledge areas.
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
   for direct children of that node only. Reasoning agents can derive subtree
   totals if needed.

6. **No taxonomy in v1.** `taxonomy.md` is out of scope for this phase.

7. **Application module placement: `application/structure.py`.** The
   transport-neutral tree export lives in a new application module. This keeps
   it separate from `browse.py`, which is optimized for capped content
   navigation, while avoiding confusion with the existing brain-layer
   `brain/tree.py` primitives.

8. **Snapshot-oriented output only.** Phase 1 does not include historical
   comparison fields. Raw `content_hash` and `structure_hash` are omitted from
   the public tree contract because they are low-value in a single-snapshot
   response.

9. **Sparse public contract.** The MCP response and CLI `--json` output omit
   zero, null, false, and empty values where the omitted default can be defined
   safely and explicitly in the contract.

10. **No `name` field on the wire.** `name` is derivable from the last segment
    of `path`; for the root node, `path=""` identifies the knowledge root. The
    human-readable CLI output may still render the folder label.

11. **Insight artifacts use `artifact_count`, not `artifact_names`.** The tree
    tool exposes enough metadata to reason about coverage and richness without
    serializing per-node artifact filenames. If exact names are needed later,
    the client can drill into a more specific surface.

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

### Internal Data Model

The application layer may use a richer internal model than the public wire
shape so implementation stays explicit and testable.

```python
@dataclass(frozen=True)
class SyncedFileCounts:
    awaiting: int = 0
    materialized: int = 0
    stale: int = 0
    missing: int = 0


@dataclass(frozen=True)
class InsightStats:
    artifact_count: int = 0
    summary_present: bool = False
    last_regen_utc: str | None = None


@dataclass(frozen=True)
class JournalStats:
    entry_count: int = 0
    first_entry_date: str | None = None
    last_entry_date: str | None = None


@dataclass(frozen=True)
class TreeNode:
    path: str
    depth: int
    child_folder_count: int = 0
    manual_file_count: int = 0
    synced_files: SyncedFileCounts = SyncedFileCounts()
    insights: InsightStats = InsightStats()
    journals: JournalStats = JournalStats()


@dataclass(frozen=True)
class TreeResult:
    nodes: list[TreeNode]
    total_nodes: int
    max_depth: int
```

### Semantics Of Counts

#### `child_folder_count`

Count direct child knowledge areas only:

- include direct child directories that qualify as knowledge areas
- exclude empty structural folders that are not knowledge areas
- derive the count from the discovered semantic area set or an equivalent
  semantic predicate
- do not derive the count from raw visible directory listing alone

#### `manual_file_count`

Count direct readable files in the node that are **not** synced managed
markdown files.

Implementation must not rely on `is_readable_file()` alone, because synced
markdown files also satisfy that predicate. Managed synced markdown must be
excluded by checking for managed identity, for example via
`extract_source_id(path)`.

#### `synced_files`

Count registered synced sources by effective area path and manifest state.

The effective area path is the parent of manifest `knowledge_path`.

Use the manifest `knowledge_state` breakdown:

- `awaiting`
- `materialized`
- `stale`
- `missing`

This is a registry-level state breakdown, not an "actually present files on
disk" count. The distinction is intentional and must be documented in the tool
description.

If implementation uses `SourceManifest.target_path`, treat that as an internal
convenience only. The public contract remains defined in terms of the parent of
`knowledge_path`.

### Managed Brain-Sync Data

#### Insights

Expose whether user-facing insight artifacts exist for the node.

For v1:

- `summary_present` reflects whether `summary.md` exists
- `artifact_count` counts user-facing insight artifacts in the node's
  `insights/` directory
- `artifact_count` must exclude `insight-state.json`, because that file is
  portable baseline state rather than a user-facing insight artifact
- `last_regen_utc` comes from `read_all_regen_meta`

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
3. Build an effective-area-path index from manifests by grouping each source
   under the parent of its `knowledge_path`, broken down by `knowledge_state`.
4. Preload regen sidecars with `read_all_regen_meta(knowledge_root(root))`.
5. Discover the semantic knowledge-area paths using existing helpers.
6. For each node:
   - count direct child knowledge areas
   - count direct manual files
   - attach direct synced-file state counts
   - attach insight stats
   - attach journal stats
7. Serialize to the sparse public contract by omitting default-valued fields.
8. Return nodes in depth-first order, alphabetical within siblings.

### Exact Public JSON Contract

Both MCP `brain_sync_tree` and CLI `brain-sync tree --json` must return the
same sparse JSON field set and naming.

Top-level shape:

```json
{
  "status": "ok",
  "nodes": [],
  "total_nodes": 0,
  "max_depth": 0
}
```

Node shape:

```json
{
  "path": "initiatives/platform/aaa",
  "depth": 3,
  "child_folder_count": 2,
  "manual_file_count": 1,
  "synced_files": {
    "awaiting": 1,
    "materialized": 3,
    "missing": 1
  },
  "insights": {
    "summary_present": true,
    "artifact_count": 1,
    "last_regen_utc": "2026-03-26T19:02:00+00:00"
  },
  "journals": {
    "entry_count": 3,
    "first_entry_date": "2026-03-11",
    "last_entry_date": "2026-03-26"
  }
}
```

Sparse default semantics:

- `path` is always present
- `depth` is always present
- `child_folder_count` absent means `0`
- `manual_file_count` absent means `0`
- `synced_files` absent means all synced-file states are `0`
- inside `synced_files`, an absent state field means `0`
- `insights` absent means:
  - `summary_present = false`
  - `artifact_count = 0`
  - `last_regen_utc = null`
- inside `insights`:
  - absent `summary_present` means `false`
  - absent `artifact_count` means `0`
  - absent `last_regen_utc` means `null`
- `journals` absent means:
  - `entry_count = 0`
  - `first_entry_date = null`
  - `last_entry_date = null`
- inside `journals`:
  - absent `entry_count` means `0`
  - absent `first_entry_date` means `null`
  - absent `last_entry_date` means `null`
- `name` is never present on the wire; consumers derive it from the last path
  segment, with `path=""` representing the knowledge root

Omission rules:

- omit fields whose value is the documented default above
- omit empty objects that would contain only default-valued fields
- do not omit `path` or `depth`
- do not omit top-level `nodes`, `total_nodes`, or `max_depth`

### Reasoning-Quality Assessment

The sparse contract is acceptable for phase 1 because the omitted fields are
not ambiguous:

- zero counts are structurally uninteresting and are recoverable from the
  explicit defaults above
- absent insights/journals blocks mean "none", not "unknown"
- `name` is purely derivable from `path`
- `artifact_count` is sufficient for snapshot reasoning; exact artifact names
  are low-value at tree scope and can be obtained from a more specific surface
  if needed

This should reduce token cost without materially degrading the ability of a
reasoning agent to infer structure, density, freshness, and content mix.

### MCP Surface

Add a new MCP tool in `interfaces/mcp/server.py`:

```python
@server.tool(
    name="brain_sync_tree",
    description=(
        "Return the full semantic knowledge-area tree under knowledge/ with per-node metadata. "
        "Read-only. Returns the knowledge-area tree used by brain-sync for regeneration and "
        "summaries, with direct manual file counts, direct synced-file counts by state, and "
        "available brain-sync managed data such as insights and journal coverage. "
        "This response is sparse: omitted fields mean the documented default values."
    ),
)
def brain_sync_tree(ctx: Context) -> dict:
    ...
```

The MCP response must conform exactly to the sparse JSON contract above.

### CLI Surface

Add a new CLI command:

```text
brain-sync tree
```

Required CLI wiring:

- parser entry in `src/brain_sync/interfaces/cli/parser.py`
- handler in `src/brain_sync/interfaces/cli/handlers.py`
- command dispatch in `src/brain_sync/__main__.py`

Default output:

- indented tree
- one line per node
- compact metadata per line

Compact human-readable example:

```text
knowledge/  folders=3 synced[a=0,m=0,s=0,ms=0] insights[summary=no,artifacts=0,last_regen=-] journals[count=0,first=-,last=-]
  _core/  folders=2 manual=1 insights[summary=yes,artifacts=1,last_regen=2026-03-27T08:15:00+00:00]
  initiatives/  folders=2 insights[summary=yes,artifacts=1,last_regen=2026-03-27T08:17:00+00:00] journals[count=2,first=2026-03-20,last=2026-03-27]
    platform/  folders=1 synced[m=2,s=1] insights[summary=yes,artifacts=1,last_regen=2026-03-27T08:17:00+00:00] journals[count=1,first=2026-03-27,last=2026-03-27]
      aaa/  folders=2 manual=1 synced[a=1,m=3,ms=1] insights[summary=yes,artifacts=1,last_regen=2026-03-26T19:02:00+00:00] journals[count=3,first=2026-03-11,last=2026-03-26]
```

Optional machine-readable output:

```text
brain-sync tree --json
```

CLI `--json` output must conform exactly to the same sparse JSON contract as
MCP.

Notes on the compact CLI format:

- `a`, `m`, `s`, and `ms` mean `awaiting`, `materialized`, `stale`, and
  `missing`
- `artifacts` is the number of user-facing insight artifacts in the
  `insights/` directory
- `-` means the field is absent or unknown in the human rendering
- the human rendering may show explicit zeroes for readability even though the
  JSON/MCP wire contract is sparse

### Caching

Dedicated caching is out of scope for this revision.

Phase 1 should implement the tree command directly and prove correctness
first. If later profiling shows the MCP surface needs caching, a follow-on
revision can add a stale-aware cache with explicit invalidation rules.

## Sequencing

1. Add the application-layer data model and `tree_brain()` in
   `application/structure.py`.
2. Add MCP tool `brain_sync_tree` in `interfaces/mcp/server.py`.
3. Add CLI parser, handler, and dispatch wiring for `brain-sync tree`.
4. Add unit coverage for `tree_brain()`.
5. Add MCP coverage for `brain_sync_tree`.
6. Add CLI surface coverage for `brain-sync tree --json` and the default
   human-readable form.

## Acceptance Criteria

1. `brain_sync_tree` returns the complete semantic knowledge-area tree under
   `knowledge/` with no truncation.
2. The tree includes `_core/`, the root `knowledge/` node, and parent folders
   that qualify via descendant knowledge areas.
3. The tree excludes directories that contain neither readable files nor
   descendant knowledge areas.
4. MCP and CLI `--json` return the exact same sparse JSON schema.
5. Every node in MCP and CLI `--json` output always includes:
   - `path`
   - `depth`
6. Every other node field follows the sparse default semantics defined in this
   plan.
7. The only allowed JSON node fields in phase 1 are:
   - `path`
   - `depth`
   - `child_folder_count`
   - `manual_file_count`
   - `synced_files.awaiting`
   - `synced_files.materialized`
   - `synced_files.stale`
   - `synced_files.missing`
   - `insights.summary_present`
   - `insights.artifact_count`
   - `insights.last_regen_utc`
   - `journals.entry_count`
   - `journals.first_entry_date`
   - `journals.last_entry_date`
8. `manual_file_count` excludes synced managed markdown files.
9. Synced-file counts are broken down by `awaiting`, `materialized`, `stale`,
   and `missing`, using `knowledge_state`, and grouped by the effective area
   path derived from the parent of manifest `knowledge_path`.
10. `insights.artifact_count` excludes `insight-state.json`.
11. `journals.entry_count`, `first_entry_date`, and `last_entry_date` are
    correct for current journal layout.
12. CLI command `brain-sync tree` exists with:
   - parser wiring
   - handler wiring
   - `__main__` dispatch wiring
   - default human-readable output
   - `--json` output
13. Tests prove:
   - application behavior
   - MCP surface behavior
   - CLI `--json` surface behavior
   - sparse omission/default semantics
14. The implementation is read-only: no mutations to the brain, runtime DB,
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
- **Sparse omission misunderstood by clients**: if default semantics are not
  explicit, omission could look like uncertainty. Mitigation: make default
  meanings normative in the contract and cover them with tests.
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
- `src/brain_sync/brain/manifest.py` for source manifest and `knowledge_path`
  semantics
- `src/brain_sync/brain/sidecar.py` for portable insight-state loading
- `src/brain_sync/brain/layout.py` for managed directory layout
- `src/brain_sync/interfaces/mcp/server.py` for MCP tool registration patterns
- `src/brain_sync/interfaces/cli/parser.py`,
  `src/brain_sync/interfaces/cli/handlers.py`, and
  `src/brain_sync/__main__.py` for CLI command wiring patterns

---

This file is not approval. The next required action is for a reviewer to
evaluate this plan revision and produce either a review artifact (if changes
are required) or an approval artifact (if acceptable).

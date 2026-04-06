# PLAN: Structural Health (brain_sync_tree + brain_sync_health)

## Problem

The brain-sync doctor command provides comprehensive **integrity** checking:
manifest/file match, identity headers, orphan attachments, DB consistency, path
normalization, insight state coherence, and regen change detection. These are
plumbing health checks that answer "is the brain internally consistent?"

There is no tool surface for **structural** health: reasoning about the shape,
depth, naming conventions, staleness, overlap, and taxonomy compliance of the
knowledge tree itself. An agent using brain-sync today cannot answer questions
like:

- "What does my brain look like right now?" (without 5+ MCP calls and mental
  reconstruction from truncated area listings)
- "Are there areas that overlap or could be consolidated?"
- "Which areas are stale, orphaned, or over-nested?"
- "Does my tree match my taxonomy?"
- "How has the shape of the brain changed?"

The `get_brain_context` and `query_brain` functions return area listings, but
these are truncated at `MAX_AREAS_LISTED` (50), carry minimal metadata
(`path`, `has_summary` only), and are designed for content navigation, not
structural review.

## Goals

1. Expose the full knowledge tree skeleton with per-node metadata in a single
   MCP call (`brain_sync_tree`).
2. Provide advisory structural health findings via a separate MCP tool
   (`brain_sync_health`) with a severity model distinct from doctor's
   deterministic integrity checks.
3. Keep both tools read-only and cheap. No LLM calls, no mutations.
4. Enable agents to render the tree visually and walk users through
   consolidation recommendations conversationally.

## Non-Goals

- Auto-fixing structural issues. These are advisory; the user decides.
- Replacing doctor. Doctor remains the integrity tool. Health is the
  metacognition tool.
- Taxonomy enforcement. Health flags drift from taxonomy conventions but does
  not block or require compliance.
- Performance optimization of large brains. The initial implementation targets
  brains with up to ~500 areas.
- Suggesting actions. The MCP layer provides the metacognition layer of
  understanding only. The client agent consuming the tool results is
  responsible for reasoning about what to suggest to the user. Including
  `suggested_action` fields in findings would neuter the client agent's
  reasoning role.

## Design Decisions

These decisions were made by the brain owner during planning and are not open
for re-evaluation by the reviewer:

1. **taxonomy.md is optional.** `knowledge/_core/taxonomy.md` is a
   user-authored convention, not a brain-sync requirement. If it exists, health
   checks use it as human-guided metacognition rules for interpreting the brain
   structure (naming patterns, declared domains, hierarchy expectations). If it
   does not exist, all checks operate purely against the tree itself. Taxonomy
   checks that depend on the file are skipped with an INFO finding when the
   file is absent.

2. **Module placement: `application/structure.py` (new module).** `tree_brain`
   and the tree data model live in a new `application/structure.py` module, not
   in `browse.py`. The consumer profile is different (structural review vs
   content navigation) and duplication is avoided by reusing shared primitives
   from `brain/tree.py` rather than sharing higher-level functions. The
   reviewer should evaluate whether the proposed module boundary is clean and
   whether `structure.py` is the right name, or whether `tree.py` at the
   application layer would be clearer (noting that `brain/tree.py` already
   exists at the brain layer).

3. **No `suggested_action` field.** Health findings provide observations and
   structured details only. The MCP layer returns the metacognition layer of
   understanding; the client agent does the reasoning about what changes to
   suggest. This preserves the client agent's role as the conversational
   advisor rather than reducing it to a relay for pre-computed suggestions.

4. **Full tree only.** `brain_sync_tree` always returns the complete tree. No
   subtree scoping parameter. Subtree scoping can be added later if
   performance requires it.

## Design

### Phase 1: `tree_brain()` in `application/structure.py`

#### Data Model

```python
@dataclass(frozen=True)
class TreeNode:
    """One node in the knowledge tree skeleton."""
    path: str                        # knowledge-relative, e.g. "initiatives/Platform/AAA"
    name: str                        # leaf folder name, e.g. "AAA"
    depth: int                       # 0 for top-level domains
    has_summary: bool                # insight summary exists
    child_count: int                 # direct content children
    source_count: int                # synced sources (from manifests) targeting this area
    local_file_count: int            # non-synced readable files in area dir
    last_regen_utc: str | None       # from insight-state sidecar
    content_hash: str | None         # from insight-state sidecar


@dataclass(frozen=True)
class TreeResult:
    """Full knowledge tree skeleton."""
    nodes: list[TreeNode]
    total_nodes: int
    max_depth: int
    taxonomy_domains: list[str] | None  # declared top-level domains from taxonomy.md, None if file absent
    actual_domains: list[str]           # actual top-level dirs under knowledge/ (excluding _core)
```

#### Implementation

`tree_brain(root: Path) -> TreeResult`

Walk the knowledge tree using existing `brain/tree.py` primitives
(`get_child_dirs`, `is_content_dir`, `is_readable_file`). For each area:

- Count direct children via `get_child_dirs(area_path)`
- Count synced sources by pre-building a `{target_path: count}` index from
  `read_all_source_manifests(root)` (one pass, reuse across all nodes)
- Count local files via `is_readable_file` on `iterdir_paths(area_dir)`
- Read insight state from the pre-built `read_all_regen_meta` index for
  `last_regen_utc` and `content_hash`
- If `knowledge/_core/taxonomy.md` exists, parse it for declared top-level
  domains. If absent, set `taxonomy_domains` to `None`.

No truncation. Return all nodes. The skeleton is lightweight metadata only
(no summary text, no file content). A brain with 500 areas produces ~500
small objects.

Sort: depth-first, alphabetical within siblings (matching the existing
`_collect_areas` walk order).

#### Taxonomy Parsing

`taxonomy.md` is a user-authored markdown file. The parser should be
conservative and resilient:

- Look for the top-level `knowledge/` code block or the `### Current Top-Level
  Domains` section for declared domain folder names.
- If the file exists but cannot be parsed, set `taxonomy_domains` to `None`
  and let the health check emit an INFO finding explaining the parse failure.
- Do not attempt to extract deeper structural expectations from the taxonomy
  in this iteration. Domain-level compliance is sufficient for v1.

#### Shared Primitives

`tree_brain` reuses from `brain/tree.py`: `get_child_dirs`, `is_content_dir`,
`is_readable_file`, `normalize_path`. It reuses from `brain/sidecar.py`:
`read_all_regen_meta`. It reuses from `brain/manifest.py`:
`read_all_source_manifests`. It does not import from or duplicate
`browse._collect_areas`.

### Phase 2: `health_brain()` in `application/health.py` (new module)

#### Severity Model

```python
class HealthSeverity(enum.Enum):
    INFO = "INFO"             # Observation, no action needed
    SUGGESTION = "SUGGESTION" # Advisory, user may want to act
    REVIEW = "REVIEW"         # Likely needs attention
    ANOMALY = "ANOMALY"       # Unusual, warrants investigation
```

```python
@dataclass
class HealthFinding:
    check: str                 # check identifier
    severity: HealthSeverity
    message: str
    knowledge_path: str | None = None
    details: dict | None = None  # check-specific structured data
```

```python
@dataclass
class HealthResult:
    findings: list[HealthFinding]
    tree: TreeResult              # the tree used to derive findings
    checked_at_utc: str
```

#### Checks

Each check is a pure function `(TreeResult, root: Path) -> list[HealthFinding]`
so they are independently testable. Checks that depend on taxonomy.md data
must handle `TreeResult.taxonomy_domains is None` gracefully (skip with an
INFO finding or operate without taxonomy context).

##### 1. `check_depth_anomalies`

Flag areas deeper than a configurable threshold (default: 4 levels). Extra
severity when the leaf node name looks like an auto-generated ID (regex:
matches `^[a-f0-9]{8,}` or `^c\d{10,}`).

- Severity: `SUGGESTION` for depth > threshold, `REVIEW` for ID-like leaves.
- Details: `{"depth": N, "looks_like_id": bool}`

##### 2. `check_naming_consistency`

When taxonomy.md is available: for each direct child of `initiatives/`, check
whether the folder name matches one of the taxonomy naming patterns
(`Platform - X`, `ACME - X`, `Product - X`, or the shorthand prefix-less form
used when initiatives are nested under a domain subfolder). Flag
inconsistencies.

Regardless of taxonomy.md: flag mixed case siblings (`Meetings` vs `meetings`
under the same parent) and date-subfolder patterns that create depth without
conceptual boundaries (pattern: folder name matches `^\d{4}-\d{2}$`).

- Severity: `SUGGESTION` for naming drift, `INFO` for date subfolders.
- Details: `{"expected_pattern": str, "actual_name": str}` (taxonomy-based),
  `{"pattern": "date_subfolder" | "case_mismatch", "siblings": [...]}` (tree-based)

##### 3. `check_cross_domain_overlap`

Find area names (leaf folder names) that appear under multiple top-level
domains. For example, `customers/ACME` and `initiatives/ACME`.

- Severity: `SUGGESTION`
- Details: `{"name": str, "locations": [str, str, ...]}`

##### 4. `check_summary_staleness`

For each area with a `last_regen_utc`, compare against the median
`last_regen_utc` of its siblings. Flag areas that are more than N days older
than the sibling median (configurable, default: 14 days). Only applies to
areas where at least 2 siblings have regen timestamps.

- Severity: `SUGGESTION`
- Details: `{"last_regen_utc": str, "sibling_median_utc": str, "days_behind": int}`

##### 5. `check_empty_scaffolding`

Flag areas with no synced sources, no local files, and no children that have
content. These are structural scaffolding that was created but never
populated.

- Severity: `SUGGESTION`
- Details: `{"source_count": 0, "local_file_count": 0, "child_count": 0}`

##### 6. `check_taxonomy_compliance`

When `TreeResult.taxonomy_domains` is not None: compare actual top-level
directories under `knowledge/` (excluding `_core`) against the declared
domains. Flag undeclared top-level directories and declared domains that don't
exist on disk.

When `TreeResult.taxonomy_domains` is None: skip this check entirely with a
single INFO finding noting that no taxonomy.md was found.

- Severity: `REVIEW` for undeclared directories, `INFO` for declared but
  missing.
- Details: `{"domain": str, "state": "undeclared" | "missing_on_disk"}`

##### 7. `check_summary_coverage`

Report the percentage of areas that have insight summaries. Flag areas without
summaries when their siblings do have them (suggests a regen gap rather than
a deliberately unsummarized area).

- Severity: `INFO` for the global coverage stat, `SUGGESTION` for individual
  gaps where siblings have summaries.
- Details: `{"coverage_pct": float}` for the global finding,
  `{"siblings_with_summary": int, "siblings_without": int}` for individual.

#### Orchestration

```python
def health_brain(root: Path, *, max_depth: int = 4, staleness_days: int = 14) -> HealthResult:
    tree = tree_brain(root)
    findings: list[HealthFinding] = []
    findings.extend(check_depth_anomalies(tree, root, max_depth=max_depth))
    findings.extend(check_naming_consistency(tree, root))
    findings.extend(check_cross_domain_overlap(tree, root))
    findings.extend(check_summary_staleness(tree, root, staleness_days=staleness_days))
    findings.extend(check_empty_scaffolding(tree, root))
    findings.extend(check_taxonomy_compliance(tree, root))
    findings.extend(check_summary_coverage(tree, root))
    return HealthResult(findings=findings, tree=tree, checked_at_utc=_utc_now())
```

### Phase 3: MCP Tools in `interfaces/mcp/server.py`

#### `brain_sync_tree`

```python
@server.tool(
    name="brain_sync_tree",
    description=(
        "Return the full knowledge tree skeleton with per-node metadata. "
        "Lightweight: returns structure only, no summary text or file content. "
        "Use for structural review, visualization, or as input to brain_sync_health."
    ),
)
def brain_sync_tree(ctx: Context) -> dict:
    rt = _runtime(ctx)
    result = tree_brain(rt.root)
    return {"status": "ok", **asdict(result)}
```

#### `brain_sync_health`

```python
@server.tool(
    name="brain_sync_health",
    description=(
        "Run advisory structural health checks on the knowledge tree. "
        "Returns observations about depth anomalies, naming drift, "
        "cross-domain overlap, staleness, empty scaffolding, taxonomy "
        "compliance, and summary coverage. Findings are metacognitive "
        "observations with structured details, not prescriptive actions. "
        "The client agent is responsible for interpreting findings and "
        "suggesting changes to the user."
    ),
)
def brain_sync_health(
    ctx: Context,
    max_depth: int = 4,
    staleness_days: int = 14,
) -> dict:
    rt = _runtime(ctx)
    result = health_brain(rt.root, max_depth=max_depth, staleness_days=staleness_days)
    return {
        "status": "ok",
        "findings": [asdict(f) for f in result.findings],
        "summary": {
            "info": sum(1 for f in result.findings if f.severity == HealthSeverity.INFO),
            "suggestion": sum(1 for f in result.findings if f.severity == HealthSeverity.SUGGESTION),
            "review": sum(1 for f in result.findings if f.severity == HealthSeverity.REVIEW),
            "anomaly": sum(1 for f in result.findings if f.severity == HealthSeverity.ANOMALY),
        },
        "tree_stats": {
            "total_nodes": result.tree.total_nodes,
            "max_depth": result.tree.max_depth,
        },
        "checked_at_utc": result.checked_at_utc,
    }
```

### CLI Surface

Add `brain-sync health` as a CLI command mirroring the existing `doctor`
pattern. The CLI renders findings grouped by severity, with color coding where
supported.

Add `brain-sync tree` for a quick terminal dump of the tree skeleton. Default
output: indented tree with node metadata. Optional `--json` for machine
consumption.

## Sequencing

1. **Phase 1**: `TreeNode`, `TreeResult`, `tree_brain()` in
   `application/structure.py`. Unit tests against fixture brains.
2. **Phase 2**: `HealthSeverity`, `HealthFinding`, `HealthResult`, individual
   check functions, `health_brain()` in `application/health.py`. Unit tests
   per check function.
3. **Phase 3**: MCP tools `brain_sync_tree` and `brain_sync_health` in
   `interfaces/mcp/server.py`. MCP integration tests. CLI commands.

Phases 1 and 2 can be implemented together. Phase 3 depends on both.

## Acceptance Criteria

1. `brain_sync_tree` returns all areas in a brain with no truncation, including
   `depth`, `child_count`, `source_count`, `local_file_count`,
   `last_regen_utc`, and `content_hash` per node.
2. `brain_sync_health` returns findings for all seven check categories with
   correct severity classification.
3. Both tools are read-only: no mutations to the brain, runtime DB, or
   filesystem.
4. Each check function is independently unit-testable with a fixture brain.
5. `health.py` does not import from doctor.py and doctor.py does not import
   from health.py. These are independent capabilities.
6. When `knowledge/_core/taxonomy.md` exists, the tree result includes parsed
   `taxonomy_domains`. When absent, `taxonomy_domains` is `None` and
   taxonomy-dependent checks are skipped gracefully.
7. Health findings contain structured `details` dicts with check-specific data
   but do not contain suggested actions. The tool provides observations; the
   client agent provides advice.
8. CLI commands `brain-sync tree` and `brain-sync health` exist and produce
   human-readable output.

## Risks

- **Taxonomy parsing brittleness**: `taxonomy.md` is user-authored and its
  structure may vary. Mitigation: parse conservatively, treat parse failures
  as `taxonomy_domains = None`, and emit an INFO finding. The tool degrades
  gracefully to tree-only checks.
- **Performance on very large brains**: `read_all_source_manifests` and the
  full tree walk are O(n) in areas and sources. For brains with thousands of
  areas this could be slow. Mitigation: acceptable for initial scope (targets
  brains up to ~500 areas); subtree scoping deferred.
- **Sidecar read cost**: Reading `insight-state.json` for every area adds I/O.
  Mitigation: `read_all_regen_meta` already does a single `rglob` pass; reuse
  that rather than per-node reads.

## Authoritative Inputs

- `application/doctor.py` for severity model precedent and finding structure
- `application/browse.py` for existing tree walking and area listing patterns
- `brain/tree.py` for `get_child_dirs`, `is_readable_file`, `is_content_dir`
- `brain/sidecar.py` for `read_all_regen_meta`
- `brain/manifest.py` for `read_all_source_manifests`
- `brain/layout.py` for path constants
- `interfaces/mcp/server.py` for MCP tool registration patterns

---

This file is not approval. The next required action is for a reviewer to
evaluate this plan and produce either a review artifact (if changes are
required) or an approval artifact (if acceptable).

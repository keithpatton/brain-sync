# Review

Plan under review: `docs/plans/plan_structural-health_2_2026-03-27.md`
Reviewer: codex-gpt-5
Date: 2026-03-27

## Summary

This revision is much closer than the root plan. Narrowing the scope to
`brain_sync_tree`, grounding it in the semantic knowledge-area tree, and
separating it from doctor/health heuristics are all good changes.

I am not approving it yet because three contract issues are still open enough
to create implementation drift:

- the plan still mixes "semantic knowledge-area tree" language with "visible
  folder" language
- synced-file counting is specified against retired `target_path` terminology
  instead of the authoritative `knowledge_path` model
- the CLI/MCP output contract is not yet specific enough to guarantee parity
  without implementer guesswork

## Findings

### 1. The plan still conflates the semantic area tree with the visible folder tree

The approved contract needs to say one thing consistently: this tool returns
the semantic knowledge-area tree, not the raw visible folder tree.

Right now the revision says that clearly in some places, but then reopens the
question in others:

- it says the tree models the semantic knowledge-area tree only
- it says `child_folder_count` is "direct visible child folders"
- it describes the MCP tool as returning the "full visible folder skeleton"
- it also says child counts should exclude empty structural folders

Those statements are not equivalent under the current implementation model.
`docs/GLOSSARY.md` and `docs/RULES.md` define knowledge areas semantically:
directories under `knowledge/` qualify only if they contain readable files or
descendant knowledge areas. `src/brain_sync/brain/tree.py` reflects that split:
`get_child_dirs()` returns visible content directories, while
`find_all_content_paths()` is the helper that actually filters to semantic
knowledge areas.

If the implementer follows the visible-folder wording or uses
`get_child_dirs()` directly for `child_folder_count`, empty structural folders
will leak into the result and the tool will stop matching the documented area
topology.

Required revision:

- make the public contract semantic-only everywhere
- redefine `child_folder_count` as direct child knowledge areas, not visible
  child folders
- explicitly say the count must be derived from the discovered area set or an
  equivalent semantic predicate, not from raw visible directories alone

### 2. Synced-file counts are anchored to retired `target_path` terminology instead of the authoritative manifest contract

The revision currently says synced-file counts should be computed by matching
manifest `target_path` to the node path and it cites `manifest.py` for
"`target_path` semantics".

That is not the authoritative portable contract anymore. `docs/brain/SCHEMAS.md`
states that `target_path` is a retired field and that `knowledge_path` is the
durable source-path anchor. The same doc also states that the parent of
`knowledge_path` is the effective area path. In code,
`SourceManifest.target_path` exists only as an in-memory convenience property
derived from `knowledge_path`.

That distinction matters here because this plan is defining a new public read
surface. Approval should not encode a retired manifest field name into the new
surface's semantics, even if the implementation happens to use the convenience
property internally.

Required revision:

- rewrite the synced-file-count contract in terms of the effective area path,
  meaning the parent of manifest `knowledge_path`
- keep `knowledge_state` as the authoritative state breakdown
- if the implementation wants to use `manifest.target_path` as a helper,
  describe that as an internal convenience rather than as the schema contract

### 3. The CLI/MCP parity contract is still too underspecified and internally inconsistent

The plan says CLI and MCP should share one underlying model, but the public
examples and acceptance criteria do not yet pin that down tightly enough.

The clearest inconsistency is in `InsightStats`:

- the data model includes `content_hash` and `structure_hash`
- the representative JSON output omits both fields
- the compact CLI example omits them too
- the acceptance criteria only say "insight stats" without naming the exact
  fields that must appear on the wire

That leaves the implementer to guess whether those hashes are part of the
public `brain_sync_tree` result, CLI `--json` output, both, or neither.

There is also a sequencing gap for CLI parity. The current CLI wiring lives
across `src/brain_sync/interfaces/cli/parser.py`,
`src/brain_sync/interfaces/cli/handlers.py`, and `src/brain_sync/__main__.py`.
The plan mentions the new command in general terms, but it does not make the
required wiring explicit or require proof at the CLI surface beyond "exists and
supports `--json`".

Required revision:

- make the public JSON contract exact, not representative
- either include `content_hash` and `structure_hash` in the public examples and
  acceptance criteria, or remove them from the model for this phase
- explicitly say that CLI `--json` and MCP return the same field set and naming
- call out the required CLI parser, handler, and `__main__` dispatch work so
  parity is not left implicit
- strengthen proof requirements so the plan requires MCP coverage and CLI
  surface coverage for the new command, not just application-level tests

## Verdict

Changes required.

Create a new plan revision that resolves the findings in this review.
This review artifact does not approve the plan and does not authorize
implementation.

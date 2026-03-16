# plan_windows-long-paths_2: Windows Long-Path Read Correctness

## Status

Planning artifact only. This document revises
`docs/plans/PLAN_windows-long-paths.md` after review feedback in
`docs/plans/plan_windows-long-paths_review_1_2026-03-16.md`.

This revision closes the two blocking gaps called out in review:

1. correctness-critical watcher and reconciliation paths are now explicitly in
   scope
2. the outward-facing path contract is now fixed so internal `\\?\` forms
   never leak into portable state or user-visible diagnostics

This stage does **not** implement the fix. It records the approved scope,
boundaries, workstreams, and verification gates for a later implementation
stage.

## Objective

Make Windows path handling read-correct for portable brains whose materialized
knowledge files, summaries, or managed artifacts exceed the ordinary `260`
character path boundary.

The implementation must ensure that:

- `brain-sync doctor` does not report false `NEEDS FETCH` for files that exist
- `brain-sync doctor` does not report false `NEEDS REGEN` when unchanged areas
  only differ by Windows path resolution behavior
- startup reconcile, live watcher handling, and doctor share one consistent
  view of the same knowledge tree on Windows
- rediscovery and identity extraction continue to work for overlong paths
- all portable manifest fields and user-visible diagnostics remain in normal
  non-prefixed path form
- the fix preserves current behavior on non-Windows platforms

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/brain-format/README.md`
- `docs/brain-format/RULES.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`

Implementation must also align with the current code seams that already own
portable manifests, identity, content discovery, reconcile correctness,
watcher/runtime decisions, regen hashing, and Windows-safe writes:

- `src/brain_sync/fileops.py`
- `src/brain_sync/fs_utils.py`
- `src/brain_sync/manifest.py`
- `src/brain_sync/pipeline.py`
- `src/brain_sync/reconcile.py`
- `src/brain_sync/__main__.py`
- `src/brain_sync/regen.py`
- `src/brain_sync/commands/doctor.py`
- `src/brain_sync/commands/sources.py`

## Context

The current system already has a Windows long-path helper:
`win_long_path()` in `fileops.py`.

That helper is already used for key write paths, but the confirmed failure is
in read/existence behavior:

- a source manifest records a valid portable `materialized_path`
- the plain Windows path lands at length `260`
- ordinary `Path.is_file()` and `os.path.exists()` return false
- the same path succeeds when rewritten with the `\\?\` extended-length prefix

This produces false machine-local diagnosis for an otherwise valid portable
brain:

- `doctor` reports `NEEDS FETCH` because the manifest's `materialized_path`
  appears missing
- rediscovery may fail to find the same file
- regen change detection may treat the area as changed because one readable
  file effectively disappears from hashing on that machine

Because `fs_utils`, `reconcile`, and the daemon watcher path also participate
in the filesystem truth model, a partial fix limited to doctor and selected
regen reads would still leave the runtime with a different view of the same
brain than doctor has.

## Confirmed Diagnosis

The confirmed diagnosis to preserve during implementation review is:

1. `materialized_path` is portable manifest state loaded from
   `.brain-sync/sources/*.json`, not runtime DB state.
2. The false `NEEDS FETCH` case is reproducible when a materialized file exists
   but only the `win_long_path()` form can see it.
3. The same class of bug affects or can affect rediscovery, identity reads,
   content discovery, reconcile, watcher change classification, and regen
   hashing because those paths rely on ordinary `Path`, `open()`, globbing, or
   directory iteration behavior.
4. The existing `DRIFT` findings for missing `regen_locks` are a separate
   runtime-DB portability issue and are not the root cause of the false
   fetch/regen findings described in this plan.

## Scope

In scope for the implementation stage:

- Windows-safe existence checks for manifest-targeted files
- Windows-safe rediscovery scans for canonical-prefix matching
- Windows-safe identity extraction reads
- Windows-safe content discovery in `fs_utils.py`
- Windows-safe startup reconcile behavior in `reconcile.py`
- Windows-safe live watcher change classification and daemon decision paths in
  `__main__.py` via shared helpers used by `classify_folder_change()`
- Windows-safe regen hashing and summary discovery for overlong paths
- a fixed outward-path contract for helper return values, persisted state, and
  diagnostics
- regression tests that reproduce the false-doctor and false-dirty behavior on
  Windows
- review of CLI hint wording for runtime-DB drift vs rebuild-db recovery

## Non-goals

- no Brain Format schema change
- no portable manifest field change
- no rewrite of placement or identity rules
- no silent invocation of `doctor --rebuild-db` from `doctor --fix`
- no broad redesign of filesystem abstractions beyond what is needed for
  Windows read correctness
- no change to non-Windows path semantics except shared helper refactors that
  preserve behavior
- no user-visible adoption of `\\?\` path forms

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material architectural problem.

### 1. Treat this as a cross-cutting path-access bug, not a doctor-only bug

The observed false `NEEDS FETCH` happens in doctor, but the underlying defect
is broader: Windows-safe writes exist while Windows-safe reads, scans, and
runtime content discovery are inconsistent.

The implementation must fix the shared path-access layer used by doctor,
rediscovery, `fs_utils`, reconcile, watcher-sensitive reads, and regen rather
than applying a doctor-specific exception.

### 2. Reuse `win_long_path()` rather than inventing a second Windows policy

The repository already has a Windows extended-length helper. The fix should
build on that primitive and extend its use to read/existence operations.

If implementation needs better ergonomics, it may add a thin shared helper
layer on top of `win_long_path()`, but it should remain small, explicit, and
constrained to filesystem access behavior.

### 3. Manifest `materialized_path` remains authoritative portable state

The bug must not be "fixed" by weakening doctor's contract around
`materialized_path`.

Portable manifest state remains:

- durable
- committable
- relative to `knowledge/`
- directly checked by doctor

The fix is to make Windows correctly observe existing files at that path.

### 4. Filesystem truth readers must share one Windows-safe view

The architecture treats filesystem truth as authoritative. Therefore the
correctness-critical readers that derive state from that filesystem truth must
share one coherent Windows-safe view of readable files and content folders.

For this fix set, that explicitly includes:

- doctor manifest/file validation
- rediscovery and identity extraction
- `fs_utils` content discovery
- startup reconcile folder discovery and change classification
- live watcher change classification paths
- regen hashing and child-summary discovery

Leaving any of those paths on plain-path semantics would preserve correctness
split-brain on Windows.

### 5. Extended-length prefixes are internal-only

Windows extended-length path forms such as `\\?\C:\...` are an internal access
mechanism only.

The implementation must follow this outward-path contract:

- helpers may use `\\?\`-prefixed paths internally for existence, read, glob,
  and iteration operations
- any path returned across module boundaries must be converted back to the
  normal non-prefixed form expected by callers
- any path persisted to manifests or compared as portable state must remain
  root-relative and normalized with forward slashes under the existing Brain
  Format contract
- user-visible diagnostics must not print `\\?\` forms

This rule is required to preserve portability while fixing Windows visibility.

### 6. Regen correctness must be restored from the same root cause

False `NEEDS REGEN` findings caused by overlong-path invisibility should be
eliminated by fixing file enumeration and reads in shared content discovery and
regen/hash code, not by suppressing doctor findings.

### 7. CLI guidance should become more specific, but remain explicit

The current doctor hinting is too generic for the runtime-DB drift case.

The follow-up improvement should:

- keep `doctor --fix` and `doctor --rebuild-db` as distinct operations
- suggest `--rebuild-db` when the unfixed finding class requires it
- avoid silently escalating from a narrow fix path to a broader runtime reset

## Planned Workstreams

### Workstream 1: Shared Windows-safe read access

Audit and update path reads that currently use plain `Path` or `open()` calls
for knowledge/manifests-managed files.

Likely touchpoints:

- `fileops.py`
- `pipeline.py`
- `regen.py`
- `doctor.py`
- `commands/sources.py`

Expected outcomes:

- existence checks use a Windows-safe path form
- direct file reads use a Windows-safe path form
- recursive scans that can encounter overlong descendants are performed from a
  Windows-safe root when needed
- helper return values are converted back to caller-expected normal forms

### Workstream 2: Shared content-discovery correctness

Update content discovery so Windows overlong paths do not disappear from the
authoritative filesystem view used by reconcile and regen-sensitive logic.

This includes:

- `fs_utils.is_readable_file()`
- `fs_utils.is_content_dir()`
- `fs_utils.get_child_dirs()`
- `fs_utils.find_all_content_paths()`

Acceptance target:

- overlong readable files and content directories remain visible to shared
  discovery helpers on Windows

### Workstream 3: Doctor and reconcile correctness

Update doctor and source-reconcile checks so valid files beyond the ordinary
Windows boundary are treated as present and rediscoverable.

This includes:

- `check_manifest_file_match()`
- doctor fallback rediscovery
- identity-header validation reads
- `commands/sources.reconcile_sources()` tier-1, tier-2, and tier-3 lookup
  behavior
- portable outward path handling when materialized paths are repaired or
  updated

Acceptance target:

- a valid portable brain on Windows does not report false `NEEDS FETCH` solely
  because a materialized path crosses the extended-length threshold

### Workstream 4: Runtime watcher and regen/hash correctness

Update startup reconcile, watcher-adjacent change classification, and regen
hashing so overlong readable files are not silently dropped from dirty/clean
decisions.

This includes:

- `reconcile.py`
- `__main__.py` paths that depend on `classify_folder_change()`
- `_compute_content_hash()`
- `_compute_structure_hash()`
- `_collect_child_summaries()`
- `classify_folder_change()`

Acceptance target:

- unchanged areas with overlong readable files do not produce false startup or
  live dirty detection and do not emit false `NEEDS REGEN`

### Workstream 5: Tests

Add targeted regression tests that prove the Windows long-path issue is fixed.

Candidate coverage:

- unit: Windows-safe helper behavior for exists/read/glob/iteration
- unit or integration: `rediscover_local_path()` finds an overlong file while
  still returning a normal caller-safe path
- unit or integration: `extract_source_id()` works for an overlong markdown
  file
- integration or system: doctor does not emit false `WOULD_TRIGGER_FETCH`
- integration: reconcile and `classify_folder_change()` remain clean for
  unchanged overlong content
- integration or system: user-visible diagnostics and persisted manifest values
  never contain `\\?\`

Tests must use placeholder paths and fictional source IDs only.

### Workstream 6: CLI hint follow-up

Review the doctor summary hinting so runtime-DB drift classes that require
`doctor --rebuild-db` are not summarized only as "run `doctor --fix`".

This should be treated as a related UX correction, not as the primary bug fix.

## Proposed Implementation Strategy

1. Introduce or extend a small shared helper pattern for Windows-safe
   exists/read/glob/iteration operations.
2. Define and enforce the outward-path contract so helper results return in
   normal caller-safe form.
3. Convert doctor, source reconciliation, rediscovery, and identity extraction
   to use that pattern.
4. Convert shared content-discovery helpers in `fs_utils.py`.
5. Audit startup reconcile, watcher-sensitive change classification, and
   regen/hash code for overlong-path blind spots and convert those reads and
   iterations.
6. Add Windows-only regression tests around the exact failure mode and the
   outward-path boundary.
7. Review doctor summary wording for rebuild-db-specific drift findings.

## Verification

The implementation is complete only when all of the following hold:

1. A Windows test case with an overlong materialized markdown path is visible
   to doctor without using ad hoc script-only checks.
2. `doctor` does not emit `WOULD_TRIGGER_FETCH` for an existing overlong file.
3. `rediscover_local_path()` can rediscover an overlong file by canonical
   prefix and still returns a normal non-prefixed path form safe for callers.
4. `extract_source_id()` can read identity from an overlong markdown file.
5. Shared content discovery in `fs_utils.py` sees overlong readable files and
   directories consistently.
6. Startup reconcile does not misclassify unchanged overlong content as missing
   or dirty.
7. Live watcher-adjacent change classification does not produce false
   dirty/rename decisions solely because a file crosses the Windows path
   boundary.
8. Unchanged knowledge areas whose files exceed the ordinary Windows path
   boundary do not emit false `WOULD_TRIGGER_REGEN`.
9. Persisted manifest values remain root-relative portable paths without
   `\\?\` prefixes.
10. User-visible diagnostics do not print `\\?\` path forms.
11. Existing non-Windows tests remain green.
12. Any new Windows-only tests are explicit about why they are gated.

## Risks and Review Focus

Reviewers should pay particular attention to:

- whether `Path.iterdir()` and recursive globbing remain reliable when only the
  root is extended-length prefixed
- whether helper changes accidentally alter non-Windows path normalization
- whether the fix covers both existence checks and actual file reads
- whether doctor, reconcile, watcher decisions, and regen truly share one
  coherent view of readable files
- whether helper return values ever escape in prefixed or absolute form
- whether the CLI hint wording change stays precise and does not imply
  destructive or broader-than-requested repair behavior

## Open Questions

These should be resolved during review before implementation begins:

1. Is `win_long_path()` sufficient for all affected recursive scans, or should
   the implementation add a thin wrapper for "safe exists/read/glob/iterdir" to
   keep call sites uniform?
2. Should the CLI hinting improvement ship in the same change as the path fix,
   or as a small follow-up once the correctness issue is landed?

Watcher/reconcile participation and the outward-path contract are no longer
open questions in this revision.

## Expected Documentation Impact

No Brain Format spec change is expected.

If implementation remains strictly within runtime/path-access behavior, updates
to `docs/brain-format/` should not be needed. A small architecture or user
documentation note may be appropriate only if the final implementation adds a
new shared filesystem-access convention that future contributors must follow.

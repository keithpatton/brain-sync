# PLAN_windows-long-paths: Windows Long-Path Read Correctness

## Status

Planning artifact only. This document defines the implementation plan for
fixing false `brain-sync doctor` findings on Windows when valid brain content
crosses the legacy `MAX_PATH` boundary for ordinary path APIs.

This stage does **not** implement the fix. It records the diagnosis, intended
scope, workstreams, and acceptance gates for review and later implementation.

## Objective

Make Windows path handling read-correct for portable brains whose materialized
knowledge files, summaries, or managed artifacts exceed the ordinary `260`
character path boundary.

The implementation must ensure that:

- `brain-sync doctor` does not report false `NEEDS FETCH` for files that exist
- `brain-sync doctor` does not report false `NEEDS REGEN` when unchanged areas
  only differ by Windows path resolution behavior
- rediscovery and identity extraction continue to work for overlong paths
- the fix preserves current behavior on non-Windows platforms

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/brain-format/README.md`
- `docs/brain-format/RULES.md`
- `docs/brain-format/SCHEMAS.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`

Implementation must also align with the current code seams that already own
portable manifests, identity, regen hashing, and Windows-safe writes:

- `src/brain_sync/fileops.py`
- `src/brain_sync/manifest.py`
- `src/brain_sync/pipeline.py`
- `src/brain_sync/regen.py`
- `src/brain_sync/commands/doctor.py`
- `src/brain_sync/fs_utils.py`

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

This explains why one Windows machine can report a clean doctor result while a
second Windows machine with a longer user/profile path reports fetch/regen
issues against the same pulled brain.

## Confirmed Diagnosis

The confirmed diagnosis to preserve during implementation review is:

1. `materialized_path` is portable manifest state loaded from
   `.brain-sync/sources/*.json`, not runtime DB state.
2. The false `NEEDS FETCH` case is reproducible when a materialized file exists
   but only the `win_long_path()` form can see it.
3. The same class of bug likely affects rediscovery, identity reads, and regen
   hashing because those code paths also rely on ordinary `Path` or `open()`
   access.
4. The existing `DRIFT` findings for missing `regen_locks` are a separate
   runtime-DB portability issue and are not the root cause of the false
   fetch/regen findings described in this plan.

## Scope

In scope for the implementation stage:

- Windows-safe existence checks for manifest-targeted files
- Windows-safe rediscovery scans for canonical-prefix matching
- Windows-safe identity extraction reads
- Windows-safe regen hashing and summary discovery for overlong paths
- regression tests that reproduce the false-doctor behavior on Windows
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

## Fixed Design Decisions

These decisions should be treated as settled unless a review artifact finds a
material architectural problem.

### 1. Treat this as a cross-cutting path-access bug, not a doctor-only bug

The observed false `NEEDS FETCH` happens in doctor, but the underlying defect
is broader: Windows-safe writes exist while Windows-safe reads and path
enumeration are inconsistent.

The implementation should fix the shared path-access layer used by doctor,
rediscovery, and regen-sensitive reads rather than applying a doctor-specific
exception.

### 2. Reuse `win_long_path()` rather than inventing a second Windows policy

The repository already has a Windows extended-length helper. The fix should
build on that primitive and extend its use to read/existence operations.

If review finds repeated call-site noise, a small helper layer may be added,
but it should remain thin and explicit.

### 3. Manifest `materialized_path` remains authoritative portable state

The bug must not be "fixed" by weakening doctor's contract around
`materialized_path`.

Portable manifest state remains:

- durable
- committable
- directly checked by doctor

The fix is to make Windows correctly observe existing files at that path.

### 4. Regen correctness must be restored from the same root cause

False `NEEDS REGEN` findings caused by overlong-path invisibility should be
eliminated by fixing file enumeration and reads in regen/hash code, not by
suppressing doctor findings.

### 5. CLI guidance should become more specific, but remain explicit

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

Expected outcomes:

- existence checks use a Windows-safe path form
- direct file reads use a Windows-safe path form
- directory scans that can encounter overlong descendants are performed from a
  Windows-safe root when needed

### Workstream 2: Doctor correctness

Update doctor checks so valid files beyond the ordinary Windows boundary are
treated as present.

This includes:

- `check_manifest_file_match()`
- any fallback rediscovery used by doctor
- any identity-header validation path that reads the candidate file

Acceptance target:

- a valid portable brain on Windows does not report false `NEEDS FETCH` solely
  because a materialized path crosses the extended-length threshold

### Workstream 3: Regen/hash correctness

Update regen-side file discovery and hashing so overlong readable files are not
silently dropped from area content or structure detection.

Likely touchpoints:

- `_compute_content_hash()`
- `_compute_structure_hash()`
- `_collect_child_summaries()`
- `classify_folder_change()`
- any helper used to iterate readable files within a knowledge area

Acceptance target:

- unchanged areas with overlong readable files do not produce false
  `NEEDS REGEN`

### Workstream 4: Tests

Add targeted regression tests that prove the Windows long-path issue is fixed.

Candidate coverage:

- unit: `win_long_path()` read/existence behavior helpers
- unit or integration: `rediscover_local_path()` finds an overlong file
- unit or integration: `extract_source_id()` works for an overlong markdown file
- system or integration: doctor does not emit false `WOULD_TRIGGER_FETCH`
- integration: doctor/regen change detection stays clean for unchanged content

Tests must use placeholder paths and fictional source IDs only.

### Workstream 5: CLI hint follow-up

Review the doctor summary hinting so runtime-DB drift classes that require
`doctor --rebuild-db` are not summarized only as "run `doctor --fix`".

This should be treated as a related UX correction, not as the primary bug fix.

## Proposed Implementation Strategy

1. Introduce or extend a small shared helper pattern for Windows-safe
   read/existence operations.
2. Convert doctor's manifest and rediscovery checks to use that pattern.
3. Convert identity extraction and any other direct managed-file reads to use
   the same pattern.
4. Audit regen hashing and folder-change classification for overlong-path
   blind spots and convert those reads/enumerations.
5. Add Windows-only regression tests around the exact failure mode.
6. Review doctor summary wording for rebuild-db-specific drift findings.

## Verification

The implementation is complete only when all of the following hold:

1. A Windows test case with an overlong materialized markdown path is visible
   to doctor without using ad hoc script-only checks.
2. `doctor` does not emit `WOULD_TRIGGER_FETCH` for an existing overlong file.
3. `rediscover_local_path()` can rediscover an overlong file by canonical
   prefix.
4. `extract_source_id()` can read identity from an overlong markdown file.
5. Unchanged knowledge areas whose files exceed the ordinary Windows path
   boundary do not emit false `WOULD_TRIGGER_REGEN`.
6. Existing non-Windows tests remain green.
7. Any new Windows-only tests are explicit about why they are gated.

## Risks and Review Focus

Reviewers should pay particular attention to:

- whether `Path.iterdir()` and recursive globbing remain reliable when only the
  root is extended-length prefixed
- whether helper changes accidentally alter non-Windows path normalization
- whether the fix covers both existence checks and actual file reads
- whether doctor and regen still share one coherent view of readable files
- whether the CLI hint wording change stays precise and does not imply
  destructive or broader-than-requested repair behavior

## Open Questions

These should be resolved during review before implementation begins:

1. Is `win_long_path()` sufficient for all affected recursive scans, or should
   the implementation add a thin wrapper for "safe exists/read/glob" to keep
   call sites uniform?
2. Should the CLI hinting improvement ship in the same change as the path fix,
   or as a small follow-up once the correctness issue is landed?
3. Do any existing watcher or reconciliation paths need the same treatment, or
   is doctor/regen/read-path coverage enough for the first fix set?

## Expected Documentation Impact

No Brain Format spec change is expected.

If implementation remains strictly within runtime/path-access behavior, updates
to `docs/brain-format/` should not be needed. A small architecture or user
documentation note may be appropriate only if the final implementation adds a
new shared filesystem-access convention that future contributors must follow.

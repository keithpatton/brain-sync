# PLAN_runtime-failure-hardening: Runtime Failure Hardening Review Bundle

## Status

Planning artifact only. This document defines a single review plan for four
runtime failure classes observed in local `brain-sync` logs during recent sync
and regen activity.

This stage does **not** implement the remaining fixes. It records the bug
bundle, investigation anchors, proposed workstreams, sequencing, and acceptance
criteria for later review and implementation.

## Objective

Reduce recurring runtime failures that currently make sync and regen brittle on
real machines, especially Windows machines with concurrent processes, synced
folders, and long-running source activity.

The implementation and review should make these four failure classes
predictable and diagnosable:

- log rotation should not fail the active run when another process is holding
  the shared log file open
- duplicate logical writes should not fail with SQLite uniqueness violations
- filesystem lock or permission pressure should degrade gracefully instead of
  causing avoidable retry storms or partial work
- upstream missing-content conditions should be classified and handled without
  looking like unexplained product failure

## Authoritative Inputs

The implementation must treat these documents as the primary constraints:

- `docs/RULES.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/GLOSSARY.md`
- `docs/runtime/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`
- `docs/plans/README.md`

It must also align with the current runtime, sync, source, and regen seams:

- `src/brain_sync/util/logging.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sync/attachments.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/lifecycle.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/sources/confluence/attachments.py`
- `src/brain_sync/sources/confluence/rest.py`
- `src/brain_sync/sources/googledocs/rest.py`
- `src/brain_sync/interfaces/cli/handlers.py`

## Investigation Anchors

### Local log file inspected

Use the machine-local runtime log at:

- `%USERPROFILE%\.brain-sync\logs\brain-sync.log`

At inspection time on `2026-03-18`, this file contained the evidence used to
assemble this plan. The current file had grown to the configured size limit and
contained entries spanning multiple prior days.

### Date windows reviewed

The following windows in `%USERPROFILE%\.brain-sync\logs\brain-sync.log`
were used to identify the bug bundle and representative failure modes:

- `2026-03-18T13:31:31` through `2026-03-18T13:32:22`
  - active sync run near the log size boundary
  - shared-log rollover failure on Windows during HTTP-heavy attachment sync
- `2026-03-09T18:17:29` through `2026-03-09T18:18:55`
  - SQLite uniqueness failures on `insight_state.knowledge_path`
- `2026-03-13T18:18:08`
  - SQLite uniqueness failure on `documents.url`
- `2026-03-09T18:01:33` through `2026-03-09T18:01:59`
  - filesystem `Access is denied` failures during regen
- `2026-03-12T07:10:06` through `2026-03-12T07:11:36`
  - repeated filesystem `Access is denied` failures under an `emails/journal`
    subtree
- `2026-03-10T21:03:19`
  - upstream fetch failures surfacing as `404 Not Found` during source
    processing

These timestamps should be treated as the initial repro and evidence anchors
for later investigation. Another agent should begin with these windows before
searching for additional adjacent failures.

## Confirmed Findings

The current investigation established the following facts.

### 1. Shared log rotation can fail on Windows under concurrent writers

The log contains a `PermissionError` raised from Python's
`logging.handlers.RotatingFileHandler.doRollover()` while attempting to rename
`brain-sync.log` to `brain-sync.log.1`.

The failure occurred exactly when the active log reached the configured size
limit, which strongly suggests a second process still had the shared file open
at rollover time.

This is not just noisy logging. It emits a traceback in the middle of normal
sync activity and risks dropping the triggering record.

### 2. Some runtime writes are not idempotent enough under duplicate or racing work

The log contains:

- `sqlite3.IntegrityError: UNIQUE constraint failed: insight_state.knowledge_path`
- `sqlite3.IntegrityError: UNIQUE constraint failed: documents.url`

These are strong signals that at least some logical writes still assume a fresh
insert when they should instead:

- reuse the existing row
- update in place
- use an explicit upsert or conflict policy
- or serialize work to prevent duplicate insert races

These failures look product-shaped because they indicate missing idempotency or
concurrency discipline in normal runtime flows rather than purely external
environment noise.

### 3. Filesystem pressure in synced folders can repeatedly break regen work

The log contains repeated Windows `Access is denied` failures against
machine-local paths under a user-managed brain checkout and a later recurring
failure under an `emails/journal/2026-03` subtree.

The evidence is consistent with one or more of:

- another process temporarily holding a directory or file handle
- OneDrive or similar sync tooling interacting with the same tree
- antivirus or indexer interference
- write ordering that is too eager around locked targets

These may not all be pure product bugs, but the product still needs a clearer
classification and retry policy so routine lock contention does not look like
unexplained failure.

### 4. Upstream missing-content conditions currently surface as noisy processing errors

The log contains source-processing failures rooted in upstream `404 Not Found`
responses during content fetches and version checks.

Some of these may reflect genuinely deleted or moved remote content. Even so,
the product should classify that state intentionally, record the canonical id,
and decide whether to:

- mark the source missing
- detach it from active processing
- preserve enough state for diagnosis
- or surface an operator-facing warning without repeated noisy retries

## Scope

In scope for the implementation stage:

- hardening shared log rollover behavior for concurrent Windows writers
- auditing duplicate-write paths for `insight_state` and `documents`
- adding idempotent or conflict-aware persistence where required
- tightening lock and permission failure classification for regen and sync work
- improving source-missing handling for upstream `404` cases
- focused test coverage for each failure class
- runtime observability improvements needed to make later diagnosis faster

## Non-goals

- no broad redesign of the entire runtime persistence model
- no general-purpose distributed locking system
- no attempt to eliminate every possible environmental file lock
- no assumption that every upstream `404` is a product bug
- no portable-brain contract change unless a later design review proves one is
  required

## Fixed Design Decisions

These decisions should be treated as settled unless a later review artifact
finds a material problem.

### 1. Keep this as one review plan and multiple likely implementation changes

The four bugs are related enough to review together because they all affect
runtime robustness, but implementation should remain free to land in separate
changes if the code paths stay distinct.

### 2. Idempotency is the default expectation for runtime persistence

If the same logical document, attachment, or insight path is discovered twice,
runtime persistence should prefer safe idempotent behavior over a failing blind
insert.

### 3. Environmental contention must become a first-class runtime state

Windows permission or lock contention should be classified explicitly rather
than surfacing only as raw exceptions and generic retries.

### 4. Missing remote content must become an intentional product state

An upstream `404` should be treated as a meaningful source lifecycle event, not
just an opaque fetch failure.

### 5. Logging failure handling must preserve non-Windows behavior

Any rollover hardening must preserve the current normal path on macOS and Linux
and only change behavior when rollover is actually blocked.

## Workstreams

### Workstream 1: Shared Log Rollover Hardening

Goals:

- prevent Windows shared-log rollover from surfacing a logging traceback during
  otherwise healthy sync or regen activity
- preserve ordinary rotating-log behavior on platforms that do not block the
  rename

Implementation requirements:

- confirm the actual writer topology for CLI, daemon, and MCP entrypoints
- decide whether the durable fix is:
  - fallback-to-run-specific log file on rollover failure
  - a different Windows-safe handler strategy
  - or a narrower single-writer ownership model
- ensure the triggering record is not dropped
- surface a concise diagnostic when fallback behavior is used

Primary modules:

- `src/brain_sync/util/logging.py`
- `src/brain_sync/__main__.py`
- `src/brain_sync/interfaces/mcp/server.py`

Acceptance targets:

- concurrent or overlapping writers do not emit a rollover traceback during
  size-based rotation on Windows
- normal single-process rotation remains intact on macOS and Linux

### Workstream 2: SQLite Idempotency and Conflict Discipline

Goals:

- eliminate avoidable uniqueness failures for repeated logical items
- make duplicate or racing work deterministic

Implementation requirements:

- identify the write paths that persist:
  - `insight_state.knowledge_path`
  - `documents.url`
- determine whether the root cause is:
  - duplicate discovery
  - retry replay
  - concurrent writers
  - missing upsert behavior
  - or stale uniqueness assumptions
- adopt an explicit conflict policy per table and caller
- add tests that reproduce the same logical item being written twice

Primary modules:

- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/attachments.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/regen/lifecycle.py`
- any table-owning repository helpers identified during review

Acceptance targets:

- duplicate logical writes no longer fail with `UNIQUE constraint failed`
- tests cover repeated writes and, where practical, racing writes

### Workstream 3: Filesystem Lock and Permission Classification

Goals:

- separate transient environmental contention from durable product failure
- reduce repeated noisy failures when Windows-synced folders are under
  temporary lock pressure

Implementation requirements:

- audit the paths that currently surface raw `PermissionError` or
  `Access is denied`
- decide which operations should:
  - retry with bounded backoff
  - classify as locked and defer
  - skip with an explicit event or warning
  - or fail immediately
- ensure the classification preserves disk-before-DB authority rules
- verify the product does not partially record success when the filesystem
  write failed

Primary modules:

- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/sync/pipeline.py`

Acceptance targets:

- transient permission pressure does not produce unbounded noisy retries
- logs and runtime status distinguish lock contention from logic failure
- partial-success drift is not introduced

### Workstream 4: Upstream Missing-Content Handling

Goals:

- treat upstream `404` responses as intentional source lifecycle conditions
- improve diagnosis for missing or deleted remote content

Implementation requirements:

- identify which source adapters currently surface raw `404` failures
- decide the canonical handling for missing remote content:
  - mark missing in runtime state
  - preserve last-known local content with warning
  - or remove/deactivate the source under explicit rules
- ensure repeated processing does not keep producing the same opaque warning
- improve log messages to include canonical id and chosen classification

Primary modules:

- `src/brain_sync/sources/confluence/rest.py`
- `src/brain_sync/sources/confluence/__init__.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/pipeline.py`

Acceptance targets:

- upstream `404` cases are classified consistently
- repeated runs do not keep surfacing the same missing source as an unstructured
  fetch error

## Proposed Sequencing

1. Finish and land the logging hardening first because it stabilizes diagnosis
   for the other three workstreams.
2. Investigate and fix SQLite idempotency next because those failures are the
   most product-shaped and can corrupt normal task flow.
3. Tighten filesystem lock classification after the DB write semantics are
   clearer.
4. Harden upstream missing-content handling last, unless earlier investigation
   shows it shares a common classification seam with filesystem errors.

## Validation Strategy

The implementation stage should include:

- focused unit tests for logging fallback behavior
- unit or integration tests for duplicate logical writes
- tests that simulate permission failures without touching real user folders
- source-adapter tests for upstream missing-content classification
- at least one targeted runtime-path validation that exercises the relevant
  repository or pipeline seam rather than only helper-level behavior

## Risks and Review Focus

Reviewers should pay particular attention to:

- whether the SQLite fixes preserve disk-before-DB authority and do not hide a
  deeper duplicate-discovery bug
- whether lock-handling changes accidentally turn real corruption or write
  failure into silent skips
- whether `404` classification could incorrectly suppress genuinely actionable
  source regressions
- whether the logging fix is truly cross-platform-safe and only changes the
  failure path

## Exit Criteria

This plan should be considered ready for approval only when a reviewer can
confirm that it:

- keeps the four bug classes clearly separated while still reviewable as one
  bundle
- points later investigators to the exact local log file and timestamp windows
  used during triage
- preserves repository rules around runtime authority, testing, and append-only
  planning artifacts
- defines acceptance targets strong enough that implementation is not left to
  guesswork

If review feedback identifies issues, the planner should create a revised plan
artifact rather than editing this file in place.

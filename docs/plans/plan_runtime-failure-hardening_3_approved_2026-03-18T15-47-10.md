# Approval

Approved: 2026-03-18T15-47-10
Approved by: codex-gpt-5

Notes:
- no unresolved reviewer findings remain
- plan is ready for implementation handoff

---

# plan_runtime-failure-hardening_3: Runtime Failure Hardening Review Bundle

## Status

Approved plan revision 3. This artifact preserves
`docs/plans/plan_runtime-failure-hardening_3_2026-03-18.md` as the approved
implementation handoff and supersedes
`docs/plans/plan_runtime-failure-hardening_2_2026-03-18.md` for execution
purposes.

## Objective

Reduce recurring runtime failures that currently make sync and regen brittle on
real Windows machines with concurrent processes, synced folders, and long-lived
source activity, while preserving:

- filesystem authority
- disk-before-DB write discipline
- existing missing-source lifecycle semantics
- guarded regen ownership semantics
- append-only planning workflow

The implementation bundle remains one review topic, but each workstream must be
able to land independently without duplicated behavior or semantic drift.

## Authoritative Inputs

Implementation must treat these as primary constraints:

- `docs/RULES.md`
- `docs/VERSIONING.md`
- `docs/COMPATIBILITY.md`
- `docs/GLOSSARY.md`
- `docs/runtime/README.md`
- `docs/architecture/ARCHITECTURE.md`
- `AGENTS.md`
- `docs/plans/README.md`

It must also align with current code reality in:

- `src/brain_sync/util/logging.py`
- `tests/unit/test_logging.py`
- `src/brain_sync/application/insights.py`
- `src/brain_sync/application/source_state.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/brain/repository.py`
- `src/brain_sync/runtime/repository.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sync/attachments.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/sources/confluence/rest.py`
- `src/brain_sync/sources/googledocs/rest.py`
- `src/brain_sync/interfaces/cli/handlers.py`

## Current Code Reality

The revised plan is scoped against the code that exists today, not the code
that existed when the first evidence was collected.

### 1. Shared-log rollover mitigation already exists

`src/brain_sync/util/logging.py` already defines
`ResilientRotatingFileHandler`, catches `PermissionError` during rollover, and
falls back to a per-run log file. `tests/unit/test_logging.py` already covers
that fallback path.

This means logging is no longer a net-new primary fix. The remaining work is
validation, observability, and any narrow residual gaps discovered while
validating the current implementation against the cited Windows evidence.

### 2. `knowledge_path` runtime writes now live in `regen_locks`, not `insight_state`

Current runtime lifecycle writes for knowledge paths are mediated through
`save_regen_lock()` and stored in `regen_locks.knowledge_path` with an upsert.
Guarded ownership acquisition, however, is not generic last-writer-wins:
`acquire_regen_ownership()` only transfers ownership when the row is unowned,
already ours, or stale. `release_owned_running_states()` and stale reclaim are
the complementary ownership-release paths.

The historical `insight_state.knowledge_path` uniqueness evidence is still
relevant, but the active workstream must target the current `regen_locks`
owner and preserve the guarded ownership model rather than weakening it.

### 3. Active source progress writes use `sync_cache`

Current application source state composes manifests with `sync_cache` rows via
`application/source_state.py` and `runtime/repository.py`. The `documents`
table remains part of the runtime schema, but the current code scan did not
find a normal sync or regen write path that actively inserts into
`documents.url`.

The `documents.url` evidence must therefore be treated as one of:

- a live caller outside the currently obvious seams that must be identified
- a migration or legacy path that still needs a narrow fix
- or a stale or obsolete work item that should be reduced to a guardrail rather
  than expanded into a new runtime write surface

### 4. Missing-source lifecycle already exists

`application/sources.py` already implements:

- manifest fallback for missing-status sources
- two-stage missing handling in reconcile
- reappearance clearing
- eventual delete after the grace period

Any upstream `404` hardening in this bundle must feed that lifecycle instead of
creating a second missing-state model.

## Investigation Anchors

### Local evidence source

Use the machine-local runtime log at:

- `%USERPROFILE%\.brain-sync\logs\brain-sync.log`

When available, also inspect:

- stderr or console capture for the relevant run
- any per-run fallback log file under `%USERPROFILE%\.brain-sync\logs\`

### Evidence anchors by failure class

#### A. Logging rollover fallback validation

- shared-log run anchor: `run_id=720ebb`
- shared-log window: `2026-03-18T13:31:31` through at least `2026-03-18T13:32:11`
- adjacent shared-log messages:
  - repeated `httpx HTTP Request` attachment-download lines
  - `brain_sync.sync.pipeline Fetched ... (no content change)`
- decisive evidence source: stderr, not the shared log
- stderr message to search for:
  - `brain-sync: shared log rotation was blocked; continuing this run in ...`

Important clarification: the shared log identifies the run and surrounding
activity, but the rollover-fallback diagnostic itself is currently emitted to
stderr. A future investigator must not assume the shared log alone is
sufficient for this case.

#### B. Historical `knowledge_path` uniqueness failure

- traceback anchor: `sqlite3.IntegrityError: UNIQUE constraint failed: insight_state.knowledge_path`
- reviewed window: `2026-03-09T18:17:29` through `2026-03-09T18:18:55`
- adjacent messages:
  - the traceback ends with the uniqueness error
  - immediately after, the shared log resumes with `run_id=8bd000`
  - the next operator-facing record is `ERROR ... Regen failed`

This is a historical anchor. The implementation plan must map it to the
current `regen_locks.knowledge_path` owner rather than reintroducing
`insight_state` semantics.

#### C. `documents.url` uniqueness failure

- traceback anchor: `sqlite3.IntegrityError: UNIQUE constraint failed: documents.url`
- timestamp anchor: `2026-03-13T18:18:08`
- adjacent messages:
  - surrounding run activity includes attachment and inline-image processing
  - nearby records include `brain_sync.attachments Added inline image: ...`

The plan intentionally treats this as a contract-definition problem first and a
scope-validation problem second because the current live caller is not yet
obvious from the active source, sync, and runtime seams.

#### D. Filesystem permission or lock pressure

- historical traceback anchors:
  - `PermissionError: [WinError 5] Access is denied`
  - reviewed window: `2026-03-09T18:01:33` through `2026-03-09T18:01:59`
  - adjacent run starts: `run_id=e6ec34`, `run_id=33fa5f`
- recurring queue anchor:
  - `run_id=0eaaed`
  - warnings at `2026-03-12T07:10:06`, `2026-03-12T07:10:36`, and `2026-03-12T07:11:36`
  - adjacent message pattern:
    - `brain_sync.regen_queue Regen failed for .../emails: [WinError 5] Access is denied`

These anchors are sufficient to validate bounded retry behavior because they
show repeated failure against the same logical subtree within a single daemon
run.

#### E. Upstream `404` missing-content case

- run anchor: `run_id=a8192e`
- timestamp anchor: `2026-03-10T21:03:19`
- adjacent messages:
  - `httpx HTTP Request: GET ... "HTTP/1.1 404 Not Found"`
  - `brain_sync.confluence_rest Version check failed for page 12345: Client error '404 Not Found'`
  - `WARNING ... Error processing confluence:12345: Client error '404 Not Found'`
  - later operator action begins with `run_id=4aba4c` and `Removing source: confluence:12345`

This is the primary remote-missing case for this plan revision.

## Scope

In scope for the implementation stage:

- validating the existing Windows log-rollover fallback and closing any
  residual observability gaps
- defining and enforcing explicit conflict contracts for:
  - `regen_locks.knowledge_path`
  - `documents.url`
- adding a concrete bounded retry and defer policy for WinError 5 filesystem
  contention in regen and adjacent write flows
- classifying Confluence `404` responses into the existing missing-source
  lifecycle
- focused tests and observability improvements needed to prove each contract

Out of scope:

- no broad runtime persistence redesign
- no new generic distributed lock system
- no new parallel missing-source state model
- no silent ownership reassignment for conflicting document identity
- no broadening of blind `save_regen_lock()` semantics into a generic ownership
  transfer mechanism
- no expansion of `documents` into a new normal-path write owner unless a live
  caller is first identified and justified
- no change to portable brain contract unless a later design review requires it

## Fixed Design Decisions

### 1. The bundle stays combined, but workstreams must remain independently landable

The four runtime-hardening concerns remain in one plan because they share a
review context, but each workstream must define its own owner, contract,
acceptance criteria, and stopping point.

### 2. Workstream 1 is validation-first, not implementation-first

Because the rollover fallback already exists, Workstream 1 may complete with:

- no code changes
- test additions only
- observability-only changes
- or a narrow fix if validation proves the current fallback insufficient

The plan must not assume a replacement strategy unless validation justifies it.

### 3. Disk-before-DB remains authoritative

Portable writes remain authoritative over runtime state. When a workflow spans
portable and runtime planes, the runtime plane may reflect lifecycle or failure
classification, but it must not claim success for a portable write that did not
durably complete.

### 4. Adapter classification is allowed; durable missing-state ownership is not

Source adapters may classify a remote condition as "missing", but only the
existing application or repository source lifecycle may persist missing status.

### 5. Identity collisions are not replay-safe

The plan distinguishes between:

- idempotent replay of the same logical row
- and an identity collision where two incompatible logical owners claim the
  same unique key

Only the first class may auto-resolve.

### 6. `owner_id` is guarded ownership state, not a generic lifecycle field

For `regen_locks`, `owner_id` is special. It must only move through guarded
ownership paths such as acquire, release, and stale reclaim. The plan must not
permit an implementation to treat conflicting live-owner writes as replay-safe
just because they target the same normalized `knowledge_path`.

## Workstreams

### Workstream 1: Shared Log Rollover Validation and Residual Gaps

Goals:

- validate that the current `ResilientRotatingFileHandler` already covers the
  Windows rollover failure mode observed on `2026-03-18`
- close any remaining evidence or observability gaps without replacing the
  current strategy unnecessarily

Implementation requirements:

- confirm the handler is used by the CLI, daemon, and MCP entrypoints that
  share the runtime log
- validate the current fallback against the `run_id=720ebb` evidence window and
  a targeted reproduced rollover-failure test
- decide whether any residual gap remains in:
  - triggering-record preservation
  - fallback-file naming
  - run correlation
  - stderr/shared-log diagnostics
- if the current implementation is sufficient, explicitly close the workstream
  with no handler replacement

Primary modules:

- `src/brain_sync/util/logging.py`
- `tests/unit/test_logging.py`
- `src/brain_sync/__main__.py`
- `src/brain_sync/interfaces/mcp/server.py`

Acceptance targets:

- Windows rollover-block conditions do not emit a logging traceback
- the triggering record is preserved in either the shared log or fallback file
- the fallback diagnostic is correlated to a run ID or fallback filename in a
  way future investigators can recover
- if no code change is needed, the validation result and residual-gap decision
  are still documented in implementation notes or tests

### Workstream 2: Runtime Identity and Conflict Discipline

Goals:

- eliminate implementer guesswork around duplicate logical writes
- make replay-safe behavior distinct from invariant-violation behavior

#### Contract A: `regen_locks.knowledge_path`

Logical identity:

- normalized `knowledge_path`

Ownership terms:

- "same-owner update" means the incoming write carries the same `owner_id` as
  the existing row, or the row is unowned and the write does not claim a new
  owner
- "non-ownership lifecycle write" means a write that does not change `owner_id`
- "guarded ownership transfer" means transfer through the existing ownership
  paths:
  - `acquire_regen_ownership()`
  - release by the current owner
  - stale reclaim
- "conflicting live-owner write" means an attempted `owner_id` change while a
  non-stale row is still owned by a different live owner

Conflict policy:

- replay of the same normalized path is replay-safe for:
  - same-owner updates
  - non-ownership lifecycle writes that preserve the existing `owner_id`
- runtime lifecycle state may be updated in place via upsert only when that
  upsert does not bypass guarded ownership semantics
- `regen_status`, `regen_started_utc`, and `error_reason` may be updated by
  same-owner or owner-preserving lifecycle writes
- `owner_id` may change only through guarded ownership transfer paths
- a conflicting live-owner write is **not** replay-safe and must be rejected or
  surfaced as an ownership invariant violation, not treated as last-writer-wins
- `save_regen_lock()` may remain the generic lifecycle persistence helper only
  for same-owner or owner-preserving writes; it must not silently become a
  second ownership transfer path

Invariant-violation boundary:

- if duplicate discovery reveals that two different logical areas normalize to
  the same runtime path after a portable write decision, the implementation
  must classify and surface that as a bug rather than silently masking it
- if a second live owner attempts to claim an actively owned, non-stale row
  outside guarded ownership transfer, that attempt must be rejected or
  classified as an ownership invariant violation

Disk-before-DB rule:

- portable insight state writes remain first
- runtime lifecycle upsert happens only after the portable write path has
  succeeded or when the operation is lifecycle-only
- if the portable write fails, runtime may record failure state, but must not
  record successful completion

Acceptance targets:

- repeated writes to the same normalized `knowledge_path` do not fail with a
  uniqueness error
- tests cover replay of the same path with changed lifecycle fields by the same
  owner
- tests prove a non-ownership lifecycle write cannot silently change
  `owner_id`
- tests prove a second live owner cannot silently overwrite `owner_id` for an
  actively owned, non-stale `knowledge_path`
- tests prove ownership transfer still works through guarded paths only:
  acquire, release, and stale reclaim
- tests prove a portable-write failure does not produce a false runtime-success
  state

#### Contract B: `documents.url`

Logical identity:

- canonical document ownership is `canonical_id`
- `url` is a secondary unique identity claim that must remain consistent with
  the owning `canonical_id`

Conflict policy:

- replay of the same `(canonical_id, url)` pair is replay-safe and may update
  mutable columns in place
- if a row already exists for `url` and it points at the same `canonical_id`,
  update-in-place is allowed
- if a row already exists for `url` and it points at a different
  `canonical_id`, that is an invariant violation, not a winner-selection case
- the implementation must not silently reassign a URL from one canonical owner
  to another

Scope gate:

- before code changes, identify the live caller that still writes
  `documents.url`, or prove the evidence comes from a legacy or migration-only
  path
- if the failure is legacy-only, land a narrow fix at that path and do not
  reintroduce `documents` as a normal sync or regen write surface

Acceptance targets:

- same-owner replay on `documents.url` is deterministic and non-failing
- conflicting-owner duplicates raise a classified invariant violation with
  clear diagnostics
- the chosen fix names the table owner and caller explicitly
- no implementation invents a new normal-path `documents` write flow just to
  satisfy the test

Primary modules:

- `src/brain_sync/application/insights.py`
- `src/brain_sync/runtime/repository.py`
- any live `documents` caller identified during implementation

### Workstream 3: WinError 5 Lock Classification and Bounded Deferral

Goals:

- stop repeated lock contention from looking like unstructured product failure
- prevent hot-loop retries and partial-success drift

Concrete policy:

| Operation class | First owner | Immediate retry policy | Exhaustion policy | Deferred owner |
|---|---|---|---|---|
| queue-driven regen of one `knowledge_path` | `regen/queue.py` | max 3 retries in the same queue lifetime, using existing 30s / 60s / 120s backoff for classified WinError 5 lock contention | stop retrying in the active queue, record classified failure state, do not keep hot-looping | next watcher event, explicit regen invocation, or next startup reconcile or session |
| portable-brain file replacement or delete during regen | `brain/repository.py` called by regen | no inner unbounded retry loop inside repository; raise a classified lock error to queue or orchestrator | leave portable state unchanged, allow caller to record failure or defer state | queue or orchestrator |
| sync attachment or materialization filesystem write | sync workflow | one local attempt only unless the workflow already owns a bounded retry loop | classify and surface as lock contention; do not spin | next normal sync cycle |

Implementation requirements:

- classify WinError 5 or `PermissionError` lock pressure separately from
  generic logic failures
- keep the existing queue retry budget bounded to 3 attempts for the same
  `knowledge_path` within one active queue lifetime
- after exhaustion, record a durable runtime classification that indicates
  lock contention rather than generic repeated failure
- do not mark portable writes successful when the filesystem mutation did not
  durably complete
- ensure later processing is deferred to a new event or new run rather than
  immediately re-entering the same locked subtree indefinitely

Evidence to prove no partial-success drift:

- repository-level tests that simulate filesystem failure and assert managed
  files are unchanged after failure
- queue or integration tests that show no more than three attempts for one path
  in a single active run
- runtime-state assertions that exhausted lock contention is recorded as failed
  or deferred, not successful

Primary modules:

- `src/brain_sync/brain/repository.py`
- `src/brain_sync/regen/queue.py`
- `src/brain_sync/regen/engine.py`
- `src/brain_sync/sync/pipeline.py`

Acceptance targets:

- the `run_id=0eaaed` class of repeated lock failure no longer produces
  unbounded retry noise
- one logical path receives at most three queue-owned retries before deferral
- portable files are unchanged when the failed operation never completed
- logs or operational events distinguish lock contention from logic failure

### Workstream 4: Upstream `404` Classification Into Existing Missing Lifecycle

Goals:

- classify remote `404` as intentional missing-content state
- route that classification into the existing missing-source lifecycle

Scope for this revision:

- Confluence is in scope
- Google Docs is out of scope except for non-regression of its current
  adapter-local `404` handling

Ownership model:

- adapter layer owns first classification of a remote response as "missing"
- sync or application layer owns translation of that classification into
  durable source lifecycle changes
- persistent missing state must reuse the existing manifest or reconcile
  missing path rather than inventing a second state machine

Implementation requirements:

- add or reuse a typed missing-content classification for Confluence version
  checks and body fetches
- ensure the durable action reuses the existing missing-source machinery
  (`mark missing`, `reappear`, grace-period delete) instead of a parallel
  source-specific branch
- include canonical ID in diagnostics and operational events
- define what remains out of scope for Google Docs and any other adapters

Primary modules:

- `src/brain_sync/sources/confluence/rest.py`
- `src/brain_sync/sync/pipeline.py`
- `src/brain_sync/sync/daemon.py`
- `src/brain_sync/application/sources.py`
- `src/brain_sync/brain/repository.py`

Acceptance targets:

- the `run_id=a8192e` Confluence `404` case is classified as missing rather
  than surfacing only as an opaque fetch error
- durable missing state reuses the existing two-stage lifecycle
- repeated runs do not emit the same unstructured warning forever
- Google Docs keeps its current `404` behavior unless intentionally revised in a
  separate plan

## Proposed Sequencing

1. Validate Workstream 1 first, because it may close with no code change and it
   sharpens the evidence story for the remaining work.
2. Resolve Workstream 2 next, because conflict contracts affect what counts as
   replay-safe versus bug-shaped behavior elsewhere.
3. Implement Workstream 3 after conflict contracts are explicit, so lock or
   defer handling does not accidentally mask identity or ownership bugs.
4. Implement Workstream 4 after the above, unless a narrow shared
   classification abstraction is required earlier.

## Validation Strategy

The implementation stage should include:

- unit validation of the current resilient logging fallback
- tests that exercise `regen_locks.knowledge_path` replay behavior against the
  current owner
- tests that explicitly separate same-owner updates from conflicting
  live-owner overwrite attempts
- a scope-validation test or focused diagnostic for the live `documents.url`
  caller before changing behavior there
- queue or integration tests for bounded WinError 5 retries and deferred
  re-entry
- adapter or pipeline tests that prove Confluence `404` classification feeds
  the existing missing-source lifecycle
- at least one targeted end-to-end-ish runtime-path validation per workstream
  at the repository or workflow seam, not only helper-level tests

## Review Focus

Reviewers should pay particular attention to:

- whether Workstream 1 really stays validation-first
- whether the `knowledge_path` contract targets the current `regen_locks`
  owner rather than the removed `insight_state` table
- whether the `owner_id` contract preserves guarded ownership transfer and does
  not widen `save_regen_lock()` into a second acquisition path
- whether the `documents.url` contract avoids inventing a new live write path
- whether the WinError 5 policy is truly bounded and assigns deferred ownership
  clearly
- whether `404` handling reuses the existing missing-source lifecycle instead
  of creating a parallel state path
- whether evidence anchors are recoverable from run IDs plus adjacent message
  patterns, including the stderr-only logging symptom

## Exit Criteria

This revision is approved for implementation with the following confirmed
properties:

- reflects current code reality for logging and `knowledge_path` ownership
- defines explicit replay-safe versus invariant-violation behavior for
  `regen_locks.knowledge_path` and `documents.url`
- preserves guarded ownership transfer for `regen_locks.owner_id`
- states a concrete bounded retry and defer policy for Windows lock handling
- attaches Confluence `404` handling to the existing missing-source lifecycle
- tightens evidence anchors with run IDs, adjacent messages, and stderr or
  shared-log ownership notes
- leaves no material behavior decision to implementer guesswork

# AGENTS.md — Repository Rules for brain-sync

This file defines repository-wide engineering rules for humans and AI agents
working in this repository.

## Documentation Governance

brain-sync uses subject-based documentation authority. Use the most specific
document for the subject you are changing.

| Document | Purpose | Must contain | Must not contain |
|---|---|---|---|
| `docs/brain/` | Portable brain reference | Portable schemas, generated artifact templates, brain version scope | Runtime-only details, tutorials, architectural rationale |
| `docs/runtime/` | Runtime reference | Runtime schemas, DB/config/daemon shapes | Portable brain contract, tutorials, architectural rationale |
| `docs/sync/` | Sync lifecycle explanation | Synced-source lifecycle models, daemon/watcher/reconcile/poll flows, sync-specific diagrams and scenario matrices | Normative invariants, field-level schema tables, user how-tos |
| `docs/GLOSSARY.md` | Shared ontology reference | Canonical terms, definitions, and concept boundaries | Architecture rationale, workflows, tutorials |
| `docs/RULES.md` | Normative system rules | Cross-cutting invariants, guarantees, precedence rules, and behavioural constraints | Implementation rationale, deep module design, tutorials |
| `docs/VERSIONING.md` | Versioning reference | Version scope, versioning policy, and upgrade/version relations | Architecture rationale, coding workflow, tutorials |
| `docs/COMPATIBILITY.md` | Compatibility reference | Supported compatibility surfaces, shims, compatibility guarantees, and removal policy | General architecture rationale, coding workflow, tutorials |
| `docs/architecture/` | System explanation | Design, module responsibilities, state models, rationale, technical debt | Normative on-disk schema definitions, user how-tos |
| `AGENTS.md` | Repository working rules | Coding standards, testing guidance, git hygiene, privacy rules | Deep architecture explanation, format spec detail, user tutorials |
| `README.md` | User guide | Install, configure, operate, update | Contributor-only rules, deep internals, schema detail |

Update triggers:

- Update `docs/brain/` when the portable brain contract changes.
- Update `docs/runtime/` when machine-local runtime schema or runtime artifact
  shape changes.
- Update `docs/sync/` when synced-source lifecycle behavior, daemon/reconcile
  flow explanations, or sync-focused diagrams and scenario models change.
- Update root `docs/*.md` shared references when cross-cutting ontology,
  rules, versioning, or compatibility policy changes.
- Update `docs/architecture/` when responsibilities, dependencies, or system
  design change.
- Update `AGENTS.md` when long-lived repository workflow rules change.
- Update `README.md` when user-facing setup or operation changes.

Prefer a single authoritative home for detailed rules. Use summary-plus-link
here when the detailed procedure already lives in a more specific document.
Avoid copying volatile bullet lists into multiple docs; duplicate only stable
headings or short summaries that are unlikely to change when the linked
document evolves.

For cross-cutting system behavior, keep normative invariants, guarantees,
and precedence rules in `docs/RULES.md`. Keep `docs/architecture/` focused on
explanation: module responsibilities, rationale, tradeoffs, and technical
debt. When architecture needs to mention a rule, summarize it briefly and link
to the authoritative rule rather than restating the full constraint.

Keep `docs/sync/` focused on synced-source lifecycle explanation: event models,
state transitions, process-flow explanation, and agent-facing test reasoning.
When sync docs need to mention a rule or schema, summarize it briefly and link
to `docs/RULES.md`, `docs/brain/`, or `docs/runtime/` rather than restating it
normatively.

Package `__init__.py` docstrings should be concise summaries of the owning
subsystem's role: responsibility, what belongs, and what does not. They should
help readers classify code locally, but they are not the authoritative home
for the full package ontology or dependency matrix.

## Plan Approval Workflow

When using the `docs/plans/` workflow, agents must preserve separate planner,
reviewer, and approver artifacts.

Follow [`docs/plans/README.md`](docs/plans/README.md) for the approval gate,
artifact naming, and the rule that implementation must not skip the approval
artifact unless the user explicitly asks to bypass the planning trail.

## Documentation Entry Points

If you need portable brain structure, start with
[`docs/brain/README.md`](docs/brain/README.md).

If you need runtime DB/config/daemon details, start with
[`docs/runtime/README.md`](docs/runtime/README.md).

If you need synced-source lifecycle behavior, daemon/watch/reconcile/poll
flows, or sync-specific diagrams, start with
[`docs/sync/README.md`](docs/sync/README.md).

If you need shared ontology, state rules, versioning, or compatibility, go to:

- [`docs/GLOSSARY.md`](docs/GLOSSARY.md)
- [`docs/RULES.md`](docs/RULES.md)
- [`docs/VERSIONING.md`](docs/VERSIONING.md)
- [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md)

If you need system-level design rationale or module responsibilities, go to
[`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md).

## Version Bumps

When the user asks to bump only the packaged app version, keep the update
minimal and avoid version-sprawl:

- `pyproject.toml` is the authoritative app-version source
- `docs/COMPATIBILITY.md` should carry the explicit supported app-version rows
  and, if useful, one canonical compatibility statement for the current row
- `docs/VERSIONING.md` should describe version domains and point to the
  authoritative source/compatibility row rather than repeating the exact app
  version in multiple places
- keep at most one explicit app-version assertion in compatibility-focused
  tests unless a second assertion proves a distinct invariant

If a version bump also changes Brain Format or runtime DB schema, update
`docs/VERSIONING.md`, `docs/COMPATIBILITY.md`, and the related migration or
compatibility tests intentionally together.

## Brain Contract

Before making portable brain changes:

1. Check the spec docs first.
2. If code and spec disagree, treat the spec as authoritative unless the task
   is explicitly to revise the spec.
3. If the portable contract changes, update versioning and compatibility
   intentionally rather than implicitly.

## Source Code Hygiene

No real company names, employer names, client names, or production identifiers
may appear anywhere in the repository.

No personal identifying information may be committed.

This applies to:

- source code
- tests
- documentation
- comments
- commit messages
- configuration files

Use placeholders:

| Instead of | Use |
|---|---|
| Real company domain | `acme.atlassian.net`, `acme.example.com` |
| Real brain folder name | `acme-brain/`, `my-brain/` |
| Real email address | `you@example.com`, `test@example.com` |
| Real person name | `Alice`, `Bob`, generic role names |
| Real page/doc IDs | Fictional numeric IDs like `123` or `456789` |

All test data must use fictional or placeholder values.

## Engineering Conventions

- Python `3.11+`
- Format with `ruff`
- Type check with `pyright`
- Line length `120`

Before commit:

```bash
ruff check
pyright
python -m pytest -n auto -m "unit or integration or external or mcp" --timeout=30
```

Before push to main:

```bash
python -m pytest -n auto --timeout=120
```

## Testing

Testing uses `pytest` with tier markers.

Each test file must declare a tier immediately after imports:

```python
pytestmark = pytest.mark.<tier>
```

### Test Tiers

| Tier | Directory | Process model | LLM mode | Primary purpose |
|---|---|---|---|---|
| `unit` | `tests/unit/` | In-process | patched shim | Pure logic |
| `integration` | `tests/integration/` | In-process | `FakeBackend` | State transitions and pipeline flows |
| `external` | `tests/external/` | In-process | patched | External client mocking |
| `mcp` | `tests/mcp/` | In-process | patched | MCP tool behavior |
| `system` | `tests/system/` | CLI subprocess | fake backend env | CLI parsing and exit behavior |
| `e2e` | `tests/e2e/` | Daemon + CLI subprocesses | fake backend env | Lifecycle, concurrency, watcher behavior |

### Running Tests

```bash
python -m pytest -n auto -m "unit or integration or external or mcp" --timeout=30
python -m pytest tests/system/ -v --timeout=30
python -m pytest tests/e2e/ -v --timeout=120
python -m pytest -n auto --timeout=120
```

### Test Structure

Keep the tier matrix as the primary test structure. Choose `unit`,
`integration`, `external`, `mcp`, `system`, or `e2e` based first on process
model and test scope.

Within a tier, prefer subsystem-aligned placement and naming when a test
mostly belongs to one stable ownership seam such as `brain`, `runtime`,
`regen`, `sync`, `query`, `sources`, `application`, or `interfaces`.
Do not force a source-tree mirror when the clearer truth is a cross-cutting
behavior, lifecycle flow, or compatibility surface.

Use additional subsystem markers only sparingly. Tier markers remain the
primary classification. If a file is predominantly about one stable seam, it
may also use a single subsystem marker to aid filtering. Cross-cutting tests
do not need subsystem markers.

Compatibility tests should remain clearly separated from seam-owned tests.
When a test intentionally validates public compatibility behavior,
prefer placing or keeping it under `tests/compat/` or another clearly named
compatibility-focused location rather than mixing that concern into subsystem
coverage by default.

### xdist

Tests are expected to be `xdist`-safe by default. Prefer `-n auto`.

If a future test must run serially, mark it explicitly and document why.

### LLM Backend Rules

- Unit tests: patch `brain_sync.regen.invoke_claude`.
- Integration tests: pass `FakeBackend` explicitly.
- System and E2E tests: use `BRAIN_SYNC_LLM_BACKEND=fake`.

### Test Isolation

Each test should use isolated filesystem state via `tmp_path`. Do not depend
on shared state between tests.

Tests must not read from or write to the real `~/.brain-sync/` directory, the
real user home directory, or a real brain checkout. In-process tests should
rely on the shared test harness isolation; subprocess harnesses must set
isolated `BRAIN_SYNC_CONFIG_DIR` and home-directory environment variables.

Treat temporary brain roots and temporary machine-local runtime state as a
single isolation bundle. If a test, repro, or harness uses a temp brain root,
it must also use an isolated temp runtime via `BRAIN_SYNC_CONFIG_DIR` and the
corresponding home-directory environment variables. Do not mix a temp brain
with the real machine-local runtime.

For ad hoc local repros and full-suite runs, prefer an explicitly isolated
runtime/home bundle rather than relying on your live shell environment.

PowerShell example:

```powershell
$tmp = Join-Path $env:TEMP ('brain-sync-test-' + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
$env:BRAIN_SYNC_CONFIG_DIR = (Join-Path $tmp 'config')
$env:HOME = $tmp
$env:USERPROFILE = $tmp
python -m pytest -n auto --timeout=120
```

Bash example:

```bash
tmp="$(mktemp -d)"
export BRAIN_SYNC_CONFIG_DIR="$tmp/config"
export HOME="$tmp"
export USERPROFILE="$tmp"
python -m pytest -n auto --timeout=120
```

On Windows, set both `HOME` and `USERPROFILE`. On Unix-like systems, setting
`USERPROFILE` as well is harmless and keeps subprocess behavior aligned across
platforms.

### Failure Classification

Classify failures into:

- harness issue
- timing misunderstanding
- product behavior violation

Prefer waiting on eventual state over fixed sleeps.

## State Authority

Disk before DB on all state mutations.

Portable brain writes under the brain root must be mediated through
`src/brain_sync/brain/repository.py`.

Runtime-state writes under `~/.brain-sync/` must be mediated through
`src/brain_sync/runtime/repository.py`.

`brain/manifest.py`, `brain/sidecar.py`, and `brain/fileops.py` remain
lower-level primitives beneath those boundaries. They may still contain write
helpers, but normal runtime application code must not use them directly for
portable-brain semantics.

Narrow exceptions are allowed only for:

- bootstrap / init code
- one-off migration code
- tests and SUT-style harness code

Portable-brain read centralization is a future-state goal. Write mediation is
the enforced rule now. See `docs/architecture/ARCHITECTURE.md` for the fuller
state authority model.

## Filesystem Access Rule

brain-sync must treat filesystem access under the brain root as a
correctness-critical portability boundary, especially on Windows where normal
`pathlib` calls can fail for overlong paths.

For knowledge-tree, manifest-targeted, and managed `.brain-sync/` filesystem
access, do not introduce new uses of:

- `Path.exists()`
- `Path.is_file()`
- `Path.is_dir()`
- `Path.iterdir()`
- `Path.glob()`
- `Path.rglob()`
- plain `open()` reads

Use the shared helpers in `src/brain_sync/brain/fileops.py` instead, such as:

- `path_exists()`
- `path_is_file()`
- `path_is_dir()`
- `iterdir_paths()`
- `glob_paths()`
- `rglob_paths()`
- `read_bytes()`
- `read_text()`

For normal runtime code, do not stop at "use `fileops.py`." If the operation
is a portable-brain write or write-adjacent authority decision, route it
through `brain/repository.py` instead. For runtime DB / daemon / token state,
route it through `runtime/repository.py`.

This is a repository-specific engineering standard, not a style preference.
Using raw path operations in these code paths can cause false `NEEDS FETCH`,
false `NEEDS REGEN`, reconcile drift, and machine-specific bugs when the same
portable brain is used on Windows machines with longer checkout paths.

## Module Dependency Rule

Follow the normative package-boundary and dependency-direction rules in
`docs/RULES.md`.

Use `docs/architecture/ARCHITECTURE.md` for explanatory rationale,
module responsibilities, and tradeoffs behind those boundaries.

In general, lower-level domain packages must not import upward into
`application`, `interfaces`, or entrypoint code. If shared behavior is needed,
move it to the owning lower-level package or to a truly neutral helper.

Canonical package paths are the supported in-repo import surface. Do not
reintroduce root-module or legacy package aliases without an explicit
compatibility decision documented in `docs/COMPATIBILITY.md` and explained in
`docs/architecture/ARCHITECTURE.md`.

Architecture boundary tests should enforce these seams where practical. Do not
weaken an existing boundary test to accommodate a new import without updating
the architecture contract intentionally. The executable fitness test lives in
`tests/unit/test_architecture_boundaries.py`.

## Source Adapter Architecture

Source-specific behavior belongs only in adapter modules under
`src/brain_sync/sources/<type>/`.

Shared modules must remain source-type-agnostic. Extend adapter capabilities
or interfaces instead of adding source-type conditionals in shared code.

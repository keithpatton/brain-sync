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
| `docs/{RULES,VERSIONING,COMPATIBILITY,GLOSSARY}.md` | Shared cross-cutting reference | Shared ontology, state rules, version/support relations | Tutorials, coding workflow, deep architecture rationale |
| `docs/architecture/` | System explanation | Design, module responsibilities, state models, rationale, technical debt | Normative on-disk schema definitions, user how-tos |
| `AGENTS.md` | Repository working rules | Coding standards, testing guidance, git hygiene, privacy rules | Deep architecture explanation, format spec detail, user tutorials |
| `README.md` | User guide | Install, configure, operate, update | Contributor-only rules, deep internals, schema detail |

Update triggers:

- Update `docs/brain/` when the portable brain contract changes.
- Update `docs/runtime/` when machine-local runtime schema or runtime artifact
  shape changes.
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

If you need shared ontology, state rules, versioning, or compatibility, go to:

- [`docs/GLOSSARY.md`](docs/GLOSSARY.md)
- [`docs/RULES.md`](docs/RULES.md)
- [`docs/VERSIONING.md`](docs/VERSIONING.md)
- [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md)

If you need design rationale or module responsibilities, go to
[`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md).

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

Core and library modules must not import from CLI, interface adapters, or
entrypoint modules.

Allowed direction:

`interfaces / cli -> application`

`application -> brain / runtime / sync / regen / query / sources / llm / util`

`entrypoints -> application / interfaces / sync`

If shared behavior is needed, move it to a neutral module.

Legacy root modules and `commands/` may remain only as compatibility shims once
their package homes exist. New logic must live under the owning package.

## Source Adapter Architecture

Source-specific behavior belongs only in adapter modules under
`src/brain_sync/sources/<type>/`.

Shared modules must remain source-type-agnostic. Extend adapter capabilities
or interfaces instead of adding source-type conditionals in shared code.

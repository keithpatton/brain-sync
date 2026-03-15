# AGENTS.md — Repository Rules for brain-sync

This file defines repository-wide engineering rules for humans and AI agents
working in this repository.

## Documentation Governance

brain-sync uses four documentation layers with a strict authority order:

`docs/brain-format/` > `docs/architecture/` > `AGENTS.md` > `README.md`

Use the most specific document that answers the question.

| Document | Purpose | Must contain | Must not contain |
|---|---|---|---|
| `docs/brain-format/` | Portable contract and specification | Filesystem rules, schemas, versioning, compatibility | Tutorials, coding workflow, architectural rationale |
| `docs/architecture/` | System explanation | Design, module responsibilities, state models, rationale, technical debt | Normative on-disk schema definitions, user how-tos |
| `AGENTS.md` | Repository working rules | Coding standards, testing guidance, git hygiene, privacy rules | Deep architecture explanation, format spec detail, user tutorials |
| `README.md` | User guide | Install, configure, operate, update | Contributor-only rules, deep internals, schema detail |

Update triggers:

- Update `docs/brain-format/` when the portable brain contract changes.
- Update `docs/architecture/` when responsibilities, dependencies, or system
  design change.
- Update `AGENTS.md` when long-lived repository workflow rules change.
- Update `README.md` when user-facing setup or operation changes.

Prefer a single authoritative home for detailed rules. Use summary-plus-link
here when the detailed procedure already lives in a more specific document.
Avoid copying volatile bullet lists into multiple docs; duplicate only stable
headings or short summaries that are unlikely to change when the linked
document evolves.

## Plan Approval Workflow

When using the `docs/plans/` workflow, agents must preserve separate planner,
reviewer, and approver artifacts.

Follow [`docs/plans/README.md`](docs/plans/README.md) for the approval gate,
artifact naming, and the rule that implementation must not skip the approval
artifact unless the user explicitly asks to bypass the planning trail.

## Brain Format Contract

For format questions, the highest authority is the Brain Format spec index:
[`docs/brain-format/README.md`](docs/brain-format/README.md).

Before making format-affecting changes:

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

`manifest.py` and `sidecar.py` are the canonical modules for durable
authority writes. See `docs/architecture/ARCHITECTURE.md` for the fuller
state authority model.

## Module Dependency Rule

Core and library modules must not import from CLI, command wiring, or
entrypoint modules.

Allowed direction:

`core -> utilities`

`commands / CLI -> core`

`entrypoints -> commands`

If shared behavior is needed, move it to a neutral module.

## Source Adapter Architecture

Source-specific behavior belongs only in adapter modules under
`src/brain_sync/sources/<type>/`.

Shared modules must remain source-type-agnostic. Extend adapter capabilities
or interfaces instead of adding source-type conditionals in shared code.

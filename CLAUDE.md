# CLAUDE.md — Repository Rules for brain-sync

This file defines **repository-wide engineering rules** that both humans and AI agents must follow when modifying the codebase.

---

# Source Code Hygiene

No real company names, employer names, client names, or production identifiers may appear anywhere in the repository.

No personal identifying information (PII) may be committed.

This applies to:

- source code
- tests
- documentation
- comments
- commit messages
- configuration files

Supported file types include Python, Markdown, YAML, TOML, JSON, and any other format in the repo.

---

## Placeholders to Use

| Instead of | Use |
|---|---|
| Real company domain | `acme.atlassian.net`, `acme.example.com` |
| Real brain folder name | `acme-brain/`, `my-brain/` |
| Real email address | `you@example.com`, `test@example.com` |
| Real person name | `Alice`, `Bob`, generic role names |
| Real page/doc IDs | Fictional numeric IDs (`123`, `456789`) |

---

## Test Fixtures

All test data must use **fictional or placeholder values**.

Never copy:

- real URLs  
- real page titles  
- real document content  
- production identifiers  

from external systems into test files.

---

# Engineering Conventions

## Tooling

- Python **3.11+**
- Code formatted with **ruff**
- Type checking with **pyright**
- Line length: **120**

All code must pass before commit:

```bash
ruff check
pyright
python -m pytest -n auto -m "unit or integration or external or mcp" --timeout=30
```

---

## Testing

Testing uses **pytest** with:

```toml
asyncio_mode = "auto"
```

Each test file must declare a **test tier** immediately after imports:

```python
pytestmark = pytest.mark.<tier>
```

### Test Tiers and Directories

| Tier | Directory | Process Model | LLM | What it catches |
|---|---|---|---|---|
| `unit` | `tests/unit/` | In-process, mocked deps | Patched `invoke_claude` | Pure logic |
| `integration` | `tests/integration/` | In-process, real FS + SQLite | `FakeBackend` (imported directly) | Pipeline logic, state transitions |
| `external` | `tests/external/` | In-process | Patched | REST API interaction mocking |
| `mcp` | `tests/mcp/` | In-process | Patched | MCP tool handler behaviour |
| `system` | `tests/system/` | Subprocess CLI | `BRAIN_SYNC_LLM_BACKEND=fake` | CLI parsing, exit codes |
| `e2e` | `tests/e2e/` | Daemon + CLI subprocesses | `BRAIN_SYNC_LLM_BACKEND=fake` | Lifecycle, concurrency, watcher |

### When to Run What

All test selection uses **markers** (not directory paths) for resilience to future moves.

**Before commit** (required, <30s target):

```bash
ruff check
pyright
python -m pytest -n auto -m "unit or integration or external or mcp" --timeout=30
```

**Before push to main** (<2min target):

```bash
python -m pytest -n auto --timeout=120
```

Runs everything including system and e2e.

**CI** (push to main): All tiers, all platforms (Linux/Windows/macOS), parallel execution via `.github/workflows/ci.yml`.

### Developer Shortcut Scripts

```bash
scripts/test-fast.sh   # Fast tiers only (<30s)
scripts/test-full.sh   # All tiers (<2min)
# Windows: scripts/test-fast.cmd, scripts/test-full.cmd
# Extra args pass through: scripts/test-fast.sh -v -k test_foo
```

### Running Tests

```bash
# All unit/integration/external/mcp tests (fast, parallel)
python -m pytest -n auto -m "unit or integration or external or mcp" --timeout=30

# Integration tests only (FakeBackend, real FS + SQLite)
python -m pytest tests/integration/ -v --timeout=30

# System tests (CLI subprocess, ~20s)
python -m pytest tests/system/ -v --timeout=30

# E2E tests (daemon lifecycle, ~60s)
python -m pytest tests/e2e/ -v --timeout=120

# Parallel execution (safe — each test fully isolated)
python -m pytest tests/e2e/ -n 4 --timeout=120
```

### Parallel Execution (xdist)

All tests are xdist-safe. Every test uses `tmp_path` for full isolation (own brain root, config dir, SQLite DB, prompt capture dir). Current evidence supports `pytest -n auto` as the default command for all tiers. No `xdist_group` markers are currently needed.

If a future test requires serial execution, mark it with `@pytest.mark.xdist_group("serial")` and document the reason.

### LLM Backend for Tests

- **Unit tests**: patch `brain_sync.regen.invoke_claude` directly (backward-compat shim routes through it).
- **Integration tests**: pass `FakeBackend` instance via the `backend=` parameter to `regen_single_folder`, `regen_path`, `regen_all`.
- **System/E2E tests**: set `BRAIN_SYNC_LLM_BACKEND=fake` in subprocess env (handled by `CliRunner` and `DaemonProcess` harness classes).

`FakeBackend` modes: `stable` (deterministic hash-based output), `rewrite`, `fail`, `timeout`, `malformed`, `partial-stream`, `large-output`.

### E2E Harness

Reusable helpers in `tests/e2e/harness/`:

- `brain.py` — `create_brain()`, `seed_knowledge_tree()`, `seed_sources()`
- `cli.py` — `CliRunner` subprocess runner with isolated env
- `daemon.py` — `DaemonProcess` lifecycle manager (cross-platform shutdown)
- `wait.py` — `wait_for_file()`, `wait_for_db()`, `wait_for_condition()` polling helpers
- `assertions.py` — `assert_summary_exists()`, `assert_no_orphan_insights()`, etc.
- `artifacts.py` — pytest plugin capturing diagnostics on test failure

### Test Isolation

Each test gets its own `tmp_path` containing isolated brain root, config dir, SQLite DB, and prompt capture dir. No shared state. `BRAIN_SYNC_CONFIG_DIR` env var overrides `~/.brain-sync` for subprocess tests.

### Adding New Tests

1. Choose the appropriate tier based on what you're testing.
2. Place the test in the correct directory.
3. Add `pytestmark = pytest.mark.<tier>` after imports.
4. For regen tests, prefer passing `FakeBackend` directly over patching `invoke_claude`.
5. Regression tests from bug fixes go in `tests/e2e/regressions/` with naming `test_<description>.py`.
6. E2E assertions must check **eventual state** (via `wait_for_*` helpers), never event sequences or log output.

### Test Failure Classification

When test failures occur, classify into three buckets:

| Bucket | Action | Examples |
|---|---|---|
| **Harness issue** | Fix test | Race due to fixed sleep, daemon readiness not detected, incorrect fixture setup |
| **Timing misunderstanding** | Adjust test logic, not timeouts | Debounce window, eventual consistency delay — fix by waiting on state, not time |
| **Product behaviour violation** | Do NOT modify test — report bug | UNCHANGED source writes file, duplicate regen sessions, orphan insights, stale DB state |

Never assume regen occurs within N seconds — only that it **eventually** occurs. Use `wait_for_file()` or `wait_for_condition()`, never fixed sleeps.

---

## State Authority

- `.brain-sync/sources/*.json` manifests are authoritative for source registration intent
- `insights/**/.regen-meta.json` sidecars are authoritative for regen hashes
- `sync_cache` and `regen_locks` are non-authoritative DB cache, rebuildable from disk
- Write disk (manifest/sidecar) before DB on all state mutations
- `manifest.py` and `sidecar.py` are the canonical modules for reading/writing disk authority

---

## Module Dependency Rule

Library modules must not import from CLI or entrypoint modules.

Allowed direction of dependencies:

```
core modules → utilities
commands / CLI → core modules
entrypoints (__main__, CLI wiring) → commands
```

Disallowed:

```
core modules importing from commands, __main__, or CLI layers
```

If shared functionality is needed, it must be moved to a neutral module such as:

```
utils
services
core
```

---

## Source Adapter Architecture

Synced sources (Confluence, Google Docs, etc.) are a core extensibility feature. New source types will be added over time.

All code that operates on sources must use the adapter/plugin pattern:

- Source-specific logic belongs **only** in adapter modules under `src/brain_sync/sources/<type>/`.
- Commands, pipeline, state, fileops, and other shared modules must be **source-type-agnostic**. They must not branch on source type strings (e.g., `if confluence:` / `if gdoc:`).
- Use existing abstractions for source-type dispatch: `canonical_prefix()`, `canonical_filename()`, `SourceType` enum, adapter capabilities.
- When new per-source behaviour is needed, extend the adapter interface (`SourceCapabilities`, adapter methods) rather than adding conditionals in shared code.

---

## Architecture

Agents must update `docs/architecture/ARCHITECTURE.md` whenever a change modifies:

- module responsibilities
- dependency direction
- architectural phases
- structural constraints

The document must remain concise and represent the current architecture and intended direction.

---

# CLAUDE.md Governance

`CLAUDE.md` may only be modified to introduce **persistent repository rules**.

Do **not** add:

- implementation plans  
- task instructions  
- temporary refactoring steps  
- one-off development notes  

Updates to this file must represent **long-term engineering constraints** that future contributors and agents must follow.
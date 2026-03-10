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
pytest
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

Valid tiers:

- `unit`
- `integration`
- `external`
- `mcp`

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
# Contributing to brain-sync

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pre-commit install
```

## Running tests

```bash
pytest
```

## Code style

- **ruff** for linting and formatting (line length 120)
- **pyright** for type checking
- **pre-commit** hooks enforce both on commit

## Pull requests

- Keep PRs focused — one logical change per PR
- All tests must pass
- New functionality should include tests

## Source code hygiene

Read `CLAUDE.md` before contributing. Key rule: **no real company names,
employer names, or personal identifying information** in any committed file.
Use generic placeholders (`acme`, `you@example.com`, etc.).

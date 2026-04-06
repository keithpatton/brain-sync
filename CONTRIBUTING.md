# Contributing to brain-sync

Thanks for taking an interest in brain-sync.

## Before You Start

- Bugs, questions, and small improvements are welcome.
- For larger changes, please open an issue first so we can align on scope and direction before you invest time in a big PR.
- The project is still evolving quickly, so maintainers may decline unsolicited large changes even when they are well executed.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\activate on Windows
pip install -e ".[dev]"
pre-commit install
```

## Checks

Run the standard checks before opening a PR:

```bash
ruff check
pyright
python -m pytest -n auto -m "unit or integration or external or mcp" --timeout=30
```

For deeper changes, run the full suite:

```bash
python -m pytest -n auto --timeout=120
```

## Pull Requests

- Keep PRs focused: one logical change per PR.
- Add or update tests when behavior changes.
- Update docs when user-facing behavior, contracts, or workflows change.
- Follow the repository-specific rules in `AGENTS.md`.

## Source Code Hygiene

Do not commit real company names, employer names, or personal identifying information anywhere in the repository. Use generic placeholders such as `acme.atlassian.net`, `acme.example.com`, and `you@example.com`.

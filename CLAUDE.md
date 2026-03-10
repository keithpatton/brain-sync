# CLAUDE.md — Agent Instructions for brain-sync

## Source Code Hygiene

**No real company names, employer names, or client names** may appear anywhere in
the repository — source code, tests, documentation, comments, commit messages, or
configuration files.

**No personal identifying information (PII)** — real names, personal email
addresses, usernames, or account identifiers — may be committed.

### Placeholders to use

| Instead of | Use |
|---|---|
| Real company domain | `acme.atlassian.net`, `acme.example.com` |
| Real brain folder name | `acme-brain/`, `my-brain/` |
| Real email address | `you@example.com`, `test@example.com` |
| Real person name | `Alice`, `Bob`, generic role names |
| Real page/doc IDs | Fictional numeric IDs (`123`, `456789`) |

This applies to **all file types**: Python, Markdown, YAML, TOML, JSON, and any
other format in the repo.

### Test fixtures

All test data must use fictional or placeholder values. Never copy real URLs,
page titles, or content from production systems into test files.

## Project conventions

- Python 3.11+, formatted with **ruff**, type-checked with **pyright**
- Tests: `pytest` with `asyncio_mode = "auto"`. Every test file must set `pytestmark = pytest.mark.<tier>` after imports (`unit`, `integration`, `external`, or `mcp`)
- Line length: 120
- Entry point: `brain-sync` CLI via `brain_sync.__main__:main`

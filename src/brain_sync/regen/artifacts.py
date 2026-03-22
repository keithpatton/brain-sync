"""Artifact parsing and commit planning for REGEN outputs.

This module owns the fixed model-backed artifact contract for REGEN:
- a valid summary payload is required
- a journal payload is optional
- malformed or journal-only output is invalid
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from brain_sync.brain.repository import BrainRepository

_STRUCTURED_OUTPUT_RE = re.compile(
    r"\A\s*<summary>(?P<summary>.*?)</summary>\s*<journal>(?P<journal>.*?)</journal>\s*\Z",
    re.DOTALL,
)


class ArtifactContractError(ValueError):
    """Raised when model output violates the fixed summary/journal contract."""


@dataclass(frozen=True)
class ParsedArtifacts:
    """Validated structured output produced by one successful model call."""

    summary_text: str
    journal_text: str | None


@dataclass(frozen=True)
class ArtifactCommitPlan:
    """Durable artifact commit decision for one regen execution."""

    action: Literal["regenerated", "skipped_similarity"]
    summary_hash: str
    summary_text: str | None
    journal_text: str | None


def parse_structured_output(raw: str) -> ParsedArtifacts:
    """Parse and validate the required summary/journal XML envelope."""
    match = _STRUCTURED_OUTPUT_RE.fullmatch(raw.strip())
    if not match:
        raise ArtifactContractError("expected exactly one <summary>...</summary><journal>...</journal> XML envelope")

    summary = match.group("summary").strip()
    if not summary:
        raise ArtifactContractError("structured output is missing a non-empty <summary> payload")

    journal = match.group("journal").strip() or None
    return ParsedArtifacts(summary_text=summary, journal_text=journal)


def append_journal_entry(repository: BrainRepository, *, knowledge_path: str, journal_text: str) -> Path:
    """Append one journal entry through the portable-brain repository."""
    return repository.append_journal_entry(knowledge_path, journal_text)

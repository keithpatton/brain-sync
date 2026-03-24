"""Insight regeneration engine.

Deterministic incremental recomputation loop (Make/Bazel model):
- Every folder is treated identically: summary = readable files + child summaries
- Loop walks up ancestors, stops when summary hash is unchanged
- Similarity guard prevents trivial LLM rewording (>0.97 → discard)

Architectural boundary: Python handles all orchestration (context assembly,
hash comparison, scheduling, validation). The LLM is a pure function:
assembled context in → structured summary/journal artifacts out.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal
from uuid import uuid4

import brain_sync.runtime.config as runtime_config
from brain_sync.brain.fileops import (
    TEXT_EXTENSIONS,
    iterdir_paths,
    path_exists,
    path_is_dir,
    read_text,
)
from brain_sync.brain.repository import BrainRepository
from brain_sync.brain.sidecar import read_all_regen_meta
from brain_sync.brain.tree import (
    find_all_content_paths,
    get_child_dirs,
    is_content_dir,
    is_readable_file,
    normalize_path,
)
from brain_sync.llm import (
    BackendCapabilities,
    LlmBackend,
    LlmResult,
    get_backend,
    resolve_backend_capabilities,
)
from brain_sync.regen.artifacts import (
    ArtifactCommitPlan,
    ArtifactContractError,
    ParsedArtifacts,
    append_journal_entry,
    parse_structured_output,
)
from brain_sync.regen.evaluation import (
    ChangeEvent,
    FolderEvaluation,
    collect_child_summaries,
    compute_content_hash,
    compute_structure_hash,
    evaluate_folder_state,
)
from brain_sync.regen.evaluation import (
    classify_change as _classify_change,
)
from brain_sync.regen.prompt_planner import (
    JOURNAL_TEMPLATE,
    REGEN_INSTRUCTIONS,
    SUMMARY_TEMPLATE,
    PromptPlannerSettings,
    PromptResult,
    build_chunk_prompt,
    build_prompt,
    build_prompt_from_chunks,
    collect_global_context,
    first_heading,
    preprocess_content,
    resolve_effective_prompt_budget,
    split_markdown_chunks,
)
from brain_sync.regen.prompt_planner import (
    PROMPT_VERSION as _PROMPT_VERSION,
)
from brain_sync.regen.prompt_planner import (
    PromptBudgetError as _PromptBudgetError,
)
from brain_sync.regen.prompt_planner import (
    invalidate_global_context_cache as _invalidate_global_context_cache,
)
from brain_sync.regen.topology import compute_waves, parent_path, propagates_up, propagation_rule
from brain_sync.runtime.operational_events import OperationalEventType
from brain_sync.runtime.repository import (
    RegenLock,
    acquire_regen_ownership,
    delete_regen_lock,
    load_all_regen_locks,
    load_regen_lock,
    record_brain_operational_event,
    record_token_event,
    release_regen_ownership,
    save_regen_lock,
)
from brain_sync.util.retry import async_retry, claude_breaker

OP_REGEN = "regen"


@dataclass(frozen=True)
class RegenExecutionInput:
    """Execution request derived from a completed folder evaluation."""

    root: Path
    regen_id: str
    config: RegenConfig
    backend: LlmBackend
    capabilities: BackendCapabilities
    session_id: str | None
    owner_id: str | None
    evaluation: FolderEvaluation


class RegenFailed(Exception):
    """Raised when insight regeneration fails after retries."""

    def __init__(self, knowledge_path: str, reason: str):
        self.knowledge_path = knowledge_path
        self.reason = reason
        super().__init__(f"Regen failed for {knowledge_path}: {reason}")


log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.97
CLAUDE_TIMEOUT = 300  # seconds
LEGACY_MAX_PROMPT_TOKENS = 120_000  # estimated via len(text) // 3
MAX_PROMPT_TOKENS = LEGACY_MAX_PROMPT_TOKENS  # legacy override hook used by older tests
STANDARD_PROMPT_BUDGET_TOKENS = 160_000
EXTENDED_PROMPT_BUDGET_TOKENS = 320_000
MIN_CHILDREN = 5  # always include at least this many child summaries
CHUNK_TARGET_CHARS = 160_000  # ~53K tokens — max chars per chunk (leaves margin for prompt overhead)
MAX_CHUNKS = 30  # guard against pathological documents


# Aliases for backward compat within this module
_is_readable_file = is_readable_file
_is_content_dir = is_content_dir

PROMPT_VERSION = _PROMPT_VERSION
classify_change = _classify_change
invalidate_global_context_cache = _invalidate_global_context_cache
_REGEN_INSTRUCTIONS = REGEN_INSTRUCTIONS
PromptBudgetError = _PromptBudgetError
_SUMMARY_TEMPLATE = SUMMARY_TEMPLATE
_JOURNAL_TEMPLATE = JOURNAL_TEMPLATE
_first_heading = first_heading
_preprocess_content = preprocess_content
_compute_content_hash = compute_content_hash
_compute_structure_hash = compute_structure_hash
_collect_child_summaries = collect_child_summaries
_collect_global_context = collect_global_context


def _parse_structured_output(raw: str) -> tuple[str, str | None]:
    """Backward-compat wrapper around the strict artifact parser."""
    artifacts = parse_structured_output(raw)
    return artifacts.summary_text, artifacts.journal_text


def _write_journal_entry(insights_dir: Path, journal_text: str, regen_id: str, display_path: str) -> None:
    """Append a timestamped journal entry to the daily journal file."""
    managed_dir = insights_dir.parent
    area_dir = managed_dir.parent
    knowledge_root = (
        area_dir
        if area_dir.name == "knowledge"
        else next(parent for parent in area_dir.parents if parent.name == "knowledge")
    )
    root = knowledge_root.parent
    rel = area_dir.relative_to(knowledge_root)
    knowledge_path = "" if str(rel) == "." else normalize_path(rel)
    journal_path = append_journal_entry(BrainRepository(root), knowledge_path=knowledge_path, journal_text=journal_text)
    log.info("[%s] Wrote journal entry for %s at %s", regen_id, display_path, journal_path)


def _save_area_state(
    root: Path,
    repository: BrainRepository,
    *,
    knowledge_path: str,
    content_hash: str,
    summary_hash: str | None = None,
    structure_hash: str | None = None,
    summary_text: str | None = None,
    regen_started_utc: str | None = None,
    last_regen_utc: str | None = None,
    regen_status: str = "idle",
    owner_id: str | None = None,
    release_owner_id: str | None = None,
    error_reason: str | None = None,
) -> None:
    """Persist portable insight hashes through the repository and lifecycle in runtime state."""
    repository.persist_regen_portable_state(
        knowledge_path,
        content_hash=content_hash,
        summary_hash=summary_hash,
        structure_hash=structure_hash,
        last_regen_utc=last_regen_utc,
        summary_text=summary_text,
    )
    if release_owner_id is not None:
        released = release_regen_ownership(
            root,
            knowledge_path,
            release_owner_id,
            regen_status=regen_status,
            error_reason=error_reason,
        )
        if not released:
            raise RuntimeError(
                f"failed to release regen ownership for '{knowledge_path}' owned by '{release_owner_id}'"
            )
    else:
        save_regen_lock(
            root,
            RegenLock(
                knowledge_path=knowledge_path,
                regen_status=regen_status,
                regen_started_utc=regen_started_utc,
                owner_id=owner_id,
                error_reason=error_reason,
            ),
        )
    record_brain_operational_event(
        root,
        event_type=OperationalEventType.QUERY_INDEX_INVALIDATED,
        knowledge_path=knowledge_path,
        outcome="summary_written",
        details={"knowledge_paths": [knowledge_path]},
    )


def _claim_regen_ownership_or_raise(root: Path, knowledge_path: str, owner_id: str | None) -> None:
    """Require ownership before mutating portable regen state."""
    if owner_id is None:
        return
    if not acquire_regen_ownership(root, knowledge_path, owner_id):
        raise RegenFailed(knowledge_path or "(root)", f"regen already owned for '{knowledge_path or '(root)'}'")


def _persist_area_state_or_fail(
    root: Path,
    repository: BrainRepository,
    *,
    knowledge_path: str,
    session_id: str | None,
    owner_id: str | None,
    regen_started_utc: str | None,
    content_hash: str,
    summary_hash: str | None = None,
    structure_hash: str | None = None,
    summary_text: str | None = None,
    last_regen_utc: str | None = None,
    regen_status: str = "idle",
    release_owner_id: str | None = None,
    error_reason: str | None = None,
) -> None:
    """Persist portable state and convert write failures into regen failures."""
    try:
        _save_area_state(
            root,
            repository,
            knowledge_path=knowledge_path,
            content_hash=content_hash,
            summary_hash=summary_hash,
            structure_hash=structure_hash,
            summary_text=summary_text,
            regen_started_utc=regen_started_utc,
            last_regen_utc=last_regen_utc,
            regen_status=regen_status,
            owner_id=owner_id,
            release_owner_id=release_owner_id,
            error_reason=error_reason,
        )
    except Exception as exc:
        log.error("Failed to persist portable regen state for %s: %s", knowledge_path or "(root)", exc, exc_info=True)
        try:
            _save_terminal_regen_lock(
                root,
                knowledge_path=knowledge_path,
                owner_id=owner_id,
                regen_started_utc=regen_started_utc,
                regen_status="failed",
                error_reason=str(exc),
            )
        except Exception as db_err:
            log.error("Failed to persist 'failed' state for %s: %s", knowledge_path or "(root)", db_err)
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_FAILED,
            knowledge_path=knowledge_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="failed_portable_state",
            details={
                "error": str(exc),
                "reason": "portable_state_persist_failed",
                "phase": "portable_state",
            },
        )
        raise RegenFailed(knowledge_path or "(root)", str(exc)) from exc


def _commit_artifact_plan_or_fail(
    root: Path,
    repository: BrainRepository,
    *,
    knowledge_path: str,
    session_id: str | None,
    owner_id: str | None,
    regen_started_utc: str | None,
    content_hash: str,
    structure_hash: str,
    last_regen_utc: str,
    plan: ArtifactCommitPlan,
    regen_id: str,
) -> None:
    """Persist summary/journal artifacts and only finalize runtime state after both succeed."""
    try:
        repository.persist_regen_portable_state(
            knowledge_path,
            content_hash=content_hash,
            summary_hash=plan.summary_hash,
            structure_hash=structure_hash,
            last_regen_utc=last_regen_utc,
            summary_text=plan.summary_text,
        )
        if plan.journal_text:
            journal_path = append_journal_entry(
                repository,
                knowledge_path=knowledge_path,
                journal_text=plan.journal_text,
            )
            log.info("[%s] Wrote journal entry for %s at %s", regen_id, knowledge_path or "(root)", journal_path)
        _save_terminal_regen_lock(
            root,
            knowledge_path=knowledge_path,
            owner_id=owner_id,
            regen_started_utc=regen_started_utc,
            regen_status="idle",
        )
        record_brain_operational_event(
            root,
            event_type=OperationalEventType.QUERY_INDEX_INVALIDATED,
            knowledge_path=knowledge_path,
            outcome="summary_written",
            details={"knowledge_paths": [knowledge_path]},
        )
    except Exception as exc:
        log.error("Failed to commit regen artifacts for %s: %s", knowledge_path or "(root)", exc, exc_info=True)
        try:
            _save_terminal_regen_lock(
                root,
                knowledge_path=knowledge_path,
                owner_id=owner_id,
                regen_started_utc=regen_started_utc,
                regen_status="failed",
                error_reason=str(exc),
            )
        except Exception as db_err:
            log.error("Failed to persist 'failed' state for %s: %s", knowledge_path or "(root)", db_err)
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_FAILED,
            knowledge_path=knowledge_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="failed_artifact_commit",
            details={
                "error": str(exc),
                "action": plan.action,
                "reason": "artifact_commit_failed",
                "phase": "artifact_commit",
            },
        )
        raise RegenFailed(knowledge_path or "(root)", str(exc)) from exc


def _save_terminal_regen_lock(
    root: Path,
    *,
    knowledge_path: str,
    owner_id: str | None,
    regen_status: str,
    regen_started_utc: str | None,
    error_reason: str | None = None,
) -> None:
    """Persist a terminal runtime state while explicitly releasing ownership."""

    def _persist_unowned_terminal_state(existing_started_utc: str | None = None) -> None:
        save_regen_lock(
            root,
            RegenLock(
                knowledge_path=knowledge_path,
                regen_started_utc=existing_started_utc if existing_started_utc is not None else regen_started_utc,
                regen_status=regen_status,
                owner_id=None,
                error_reason=error_reason,
            ),
        )

    if owner_id is None:
        _persist_unowned_terminal_state()
        return

    released = release_regen_ownership(
        root,
        knowledge_path,
        owner_id,
        regen_status=regen_status,
        error_reason=error_reason,
    )
    if not released:
        current_lock = load_regen_lock(root, knowledge_path)
        if current_lock is None:
            _persist_unowned_terminal_state()
            return
        if current_lock.owner_id is None:
            _persist_unowned_terminal_state(current_lock.regen_started_utc)
            return
        raise RuntimeError(f"failed to release regen ownership for '{knowledge_path}' owned by '{owner_id}'")


def _delete_area_state(root: Path, repository: BrainRepository, knowledge_path: str) -> None:
    """Delete portable insight state and runtime lifecycle rows for one area."""
    repository.delete_portable_insight_state(knowledge_path)
    delete_regen_lock(root, knowledge_path)
    record_brain_operational_event(
        root,
        event_type=OperationalEventType.QUERY_INDEX_INVALIDATED,
        knowledge_path=knowledge_path,
        outcome="summary_deleted",
        details={"knowledge_paths": [knowledge_path]},
    )


@dataclass
class RegenConfig:
    """Configuration for the insights agent."""

    model: str = "claude-sonnet-4-6"
    effort: str = "low"  # low, medium, high — controls thinking budget
    timeout: int = CLAUDE_TIMEOUT
    max_turns: int = 6
    similarity_threshold: float = SIMILARITY_THRESHOLD

    @classmethod
    def load(cls) -> RegenConfig:
        """Load regen config from ~/.brain-sync/config.json."""
        config_file = runtime_config.config_file_path()
        if not config_file.exists():
            return cls()
        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
            regen = data.get("regen", {})
            if not isinstance(regen, dict):
                regen = {}
            return cls(
                model=regen.get("model", "claude-sonnet-4-6"),
                effort=regen.get("effort", "low"),
                timeout=regen.get("timeout", CLAUDE_TIMEOUT),
                max_turns=regen.get("max_turns", 6),
                similarity_threshold=regen.get("similarity_threshold", SIMILARITY_THRESHOLD),
            )
        except (json.JSONDecodeError, OSError):
            return cls()


def text_similarity(a: str, b: str) -> float:
    """Compute text similarity between two strings after normalising whitespace."""

    def normalise(s: str) -> str:
        return " ".join(s.split())

    return SequenceMatcher(None, normalise(a), normalise(b)).ratio()


# Backward-compat alias — existing tests import ``ClaudeResult`` from here.
ClaudeResult = LlmResult


class _InvokeClaudeShim:
    """Adapter that routes ``backend.invoke()`` through :func:`invoke_claude`.

    When no explicit backend is passed to regen functions, this shim is used
    so that existing tests that ``patch("brain_sync.regen.invoke_claude")``
    continue to intercept LLM calls.

    Once all tests migrate to passing ``FakeBackend`` directly, this shim
    can be removed.
    """

    async def invoke(
        self,
        prompt: str,
        cwd: Path,
        timeout: int = 300,
        model: str = "",
        effort: str = "",
        max_turns: int = 6,
        system_prompt: str | None = None,
        tools: str | None = None,
        is_chunk: bool = False,
    ) -> LlmResult:
        return await invoke_claude(
            prompt,
            cwd,
            timeout=timeout,
            model=model,
            effort=effort,
            max_turns=max_turns,
            system_prompt=system_prompt,
            tools=tools,
            is_chunk=is_chunk,
        )


def _parse_token_counts(stderr_text: str) -> tuple[int | None, int | None]:
    """Parse token counts from Claude CLI stderr output.

    Claude CLI outputs lines like:
      Input tokens: 12345
      Output tokens: 6789
    or combined cost lines. Try several patterns.
    """
    input_tokens = None
    output_tokens = None

    # Pattern: "Input tokens: 12345" / "Output tokens: 6789"
    m = re.search(r"[Ii]nput.?tokens[:\s]+(\d[\d,]*)", stderr_text)
    if m:
        input_tokens = int(m.group(1).replace(",", ""))
    m = re.search(r"[Oo]utput.?tokens[:\s]+(\d[\d,]*)", stderr_text)
    if m:
        output_tokens = int(m.group(1).replace(",", ""))

    return input_tokens, output_tokens


# ---------------------------------------------------------------------------
# Claude CLI invocation
# ---------------------------------------------------------------------------


@dataclass
class StreamParseResult:
    """Parsed output from Claude CLI ``--output-format stream-json``."""

    text: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    num_turns: int | None = None
    is_error: bool = False
    error_subtype: str | None = None


def _parse_stream_json(stdout_text: str) -> StreamParseResult:
    """Parse NDJSON stream from ``claude --output-format stream-json --verbose``.

    The CLI emits high-level events (not raw Anthropic API streaming events):

    - ``{"type":"assistant","message":{"usage":{...},"content":[...]}}``
      One per turn.  Contains per-turn usage and the assistant's text content.
    - ``{"type":"result","usage":{...},"num_turns":N,"is_error":false,...}``
      Final summary with aggregated usage across all turns.

    Token accounting (from the ``result`` event's aggregated usage):
    - **input_tokens** = input_tokens + cache_creation_input_tokens (billable).
      cache_read_input_tokens is logged for observability but excluded.
    - **output_tokens** = output_tokens from the result usage.

    Text is assembled from ``assistant`` events' ``message.content`` blocks,
    with the ``result.result`` field as a fallback.
    """
    text_parts: list[str] = []
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read: int = 0
    cache_creation: int = 0
    num_turns: int | None = None
    is_error = False
    error_subtype: str | None = None

    for line in stdout_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

        event_type = event.get("type")

        if event_type == "assistant":
            # Extract text from message.content blocks
            message = event.get("message", {})
            for block in message.get("content", []):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

        elif event_type == "result":
            num_turns = event.get("num_turns")
            is_error = bool(event.get("is_error"))
            subtype = event.get("subtype", "")
            if is_error or subtype.startswith("error"):
                is_error = True
                error_subtype = subtype or None

            # Extract aggregated usage from result event
            usage = event.get("usage", {})
            raw_input = usage.get("input_tokens")
            cc = usage.get("cache_creation_input_tokens") or 0
            cr = usage.get("cache_read_input_tokens") or 0
            out = usage.get("output_tokens")

            if raw_input is not None:
                cache_creation = cc
                cache_read = cr
                input_tokens = raw_input + cc
            output_tokens = out

            # Fallback: use result.result text if no assistant blocks found
            if not text_parts:
                result_text = event.get("result")
                if result_text:
                    text_parts.append(result_text)

    if input_tokens is not None:
        log.debug(
            "Stream-JSON tokens: input=%s cache_creation=%s cache_read=%s output=%s",
            input_tokens,
            cache_creation,
            cache_read,
            output_tokens,
        )

    return StreamParseResult(
        text="".join(text_parts),
        input_tokens=input_tokens or None,
        output_tokens=output_tokens,
        num_turns=num_turns,
        is_error=is_error,
        error_subtype=error_subtype,
    )


async def invoke_claude(
    prompt: str,
    cwd: Path,
    timeout: int = CLAUDE_TIMEOUT,
    model: str = "",
    effort: str = "",
    max_turns: int = 6,
    system_prompt: str | None = None,
    tools: str | None = None,
    session_id: str | None = None,
    operation_type: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    is_chunk: bool = False,
) -> ClaudeResult:
    """Backward-compat shim — delegates to the LLM backend.

    Existing tests that ``patch("brain_sync.regen.invoke_claude")`` continue
    to work.  New code should call ``backend.invoke()`` directly.

    Telemetry recording wraps the result when *session_id* is provided.
    """
    backend = get_backend()
    result = await backend.invoke(
        prompt,
        cwd,
        timeout=timeout,
        model=model,
        effort=effort,
        max_turns=max_turns,
        system_prompt=system_prompt,
        tools=tools,
        is_chunk=is_chunk,
    )

    # Record telemetry
    if session_id and operation_type:
        _record_telemetry(
            result,
            session_id=session_id,
            operation_type=operation_type,
            resource_type=resource_type,
            resource_id=resource_id,
            is_chunk=is_chunk,
            model=model,
        )

    return result


def _record_telemetry(
    result: LlmResult,
    *,
    session_id: str,
    operation_type: str,
    resource_type: str | None,
    resource_id: str | None,
    is_chunk: bool,
    model: str,
) -> None:
    """Record a token_events row for telemetry."""
    record_token_event(
        session_id=session_id,
        operation_type=operation_type,
        resource_type=resource_type,
        resource_id=resource_id,
        is_chunk=is_chunk,
        model=model or None,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        duration_ms=result.duration_ms,
        num_turns=result.num_turns,
        success=result.success,
    )


async def _invoke_execution_backend(
    execution_input: RegenExecutionInput,
    prompt: str,
    *,
    is_chunk: bool,
    max_turns: int,
) -> LlmResult:
    """Invoke the configured backend using the bounded capability contract."""

    invocation = execution_input.capabilities.invocation
    result = await async_retry(
        execution_input.backend.invoke,
        prompt,
        cwd=execution_input.root,
        timeout=execution_input.config.timeout,
        model=execution_input.config.model,
        effort=execution_input.config.effort,
        max_turns=max_turns,
        system_prompt=invocation.system_prompt,
        tools=invocation.tools,
        is_chunk=is_chunk,
        is_success=lambda r: r.success,
        breaker=claude_breaker,
    )
    if execution_input.session_id:
        _record_telemetry(
            result,
            session_id=execution_input.session_id,
            operation_type=OP_REGEN,
            resource_type="knowledge",
            resource_id=execution_input.evaluation.knowledge_path,
            is_chunk=is_chunk,
            model=execution_input.config.model,
        )
    return result


def _record_regen_event(
    *,
    root: Path,
    event_type: OperationalEventType,
    knowledge_path: str,
    session_id: str | None,
    owner_id: str | None,
    outcome: str,
    duration_ms: int | None = None,
    details: dict[str, object] | None = None,
) -> None:
    record_brain_operational_event(
        root,
        event_type=event_type,
        session_id=session_id,
        owner_id=owner_id,
        knowledge_path=knowledge_path,
        outcome=outcome,
        duration_ms=duration_ms,
        details=details,
    )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


def _estimate_tokens(text: str) -> int:
    """Return the planner's lightweight token estimate for *text*."""

    return len(text) // 3


def _effective_prompt_budget(capabilities: BackendCapabilities | None) -> tuple[int, str, int]:
    """Resolve the effective prompt budget for one prompt build."""

    return resolve_effective_prompt_budget(capabilities, _planner_settings())


def _planner_settings() -> PromptPlannerSettings:
    """Build prompt-planner settings from current engine constants."""

    return PromptPlannerSettings(
        instructions=_REGEN_INSTRUCTIONS,
        legacy_max_prompt_tokens=LEGACY_MAX_PROMPT_TOKENS,
        max_prompt_tokens=MAX_PROMPT_TOKENS,
        standard_prompt_budget_tokens=STANDARD_PROMPT_BUDGET_TOKENS,
        extended_prompt_budget_tokens=EXTENDED_PROMPT_BUDGET_TOKENS,
    )


def _build_chunk_prompt(
    chunk: str,
    chunk_idx: int,
    total_chunks: int,
    filename: str,
    first_heading_text: str,
) -> str:
    """Build a lightweight prompt for summarizing a single chunk."""

    return build_chunk_prompt(chunk, chunk_idx, total_chunks, filename, first_heading_text)


def _split_markdown_chunks(
    content: str,
    target_chars: int = CHUNK_TARGET_CHARS,
    *,
    _level: int | None = None,
) -> list[str]:
    """Split markdown content into chunks using the extracted planner seam."""

    return split_markdown_chunks(content, target_chars, _level=_level)


def _build_prompt_from_chunks(
    knowledge_path: str,
    chunk_summaries: dict[str, list[str]],
    child_summaries: dict[str, str],
    insights_dir: Path,
    root: Path,
    binary_names: list[str],
    *,
    capabilities: BackendCapabilities | None = None,
) -> PromptResult:
    """Build a merge prompt using chunk summaries instead of raw file content."""

    return build_prompt_from_chunks(
        knowledge_path,
        chunk_summaries,
        child_summaries,
        insights_dir,
        root,
        binary_names,
        capabilities=capabilities,
        settings=_planner_settings(),
        collect_global_context_fn=_collect_global_context,
    )


def _build_prompt(
    knowledge_path: str,
    knowledge_dir: Path,
    child_summaries: dict[str, str],
    insights_dir: Path,
    root: Path,
    *,
    capabilities: BackendCapabilities | None = None,
) -> PromptResult:
    """Build the prompt for regenerating an insight summary."""

    return build_prompt(
        knowledge_path,
        knowledge_dir,
        child_summaries,
        insights_dir,
        root,
        capabilities=capabilities,
        settings=_planner_settings(),
        preprocess_content_fn=_preprocess_content,
        collect_global_context_fn=_collect_global_context,
    )


_get_child_dirs = get_child_dirs
collect_child_summaries = _collect_child_summaries


def _persist_structure_hash_backfill(root: Path, evaluation: FolderEvaluation) -> None:
    """Persist the structure-hash backfill for a metadata-only evaluation result."""

    if evaluation.outcome != "metadata_backfill" or evaluation.meta is None:
        raise ValueError("structure-hash backfill requires a metadata_backfill evaluation")
    if evaluation.content_hash is None or evaluation.structure_hash is None:
        raise ValueError("metadata_backfill evaluation must carry current hashes")

    log.info("Backfilling structure_hash for %s (post-v18 migration)", evaluation.knowledge_path or "(root)")
    lock = load_regen_lock(root, evaluation.knowledge_path)
    _save_area_state(
        root,
        BrainRepository(root),
        knowledge_path=evaluation.knowledge_path,
        content_hash=evaluation.content_hash,
        summary_hash=evaluation.meta.summary_hash,
        structure_hash=evaluation.structure_hash,
        regen_started_utc=lock.regen_started_utc if lock else None,
        last_regen_utc=evaluation.meta.last_regen_utc,
        regen_status=lock.regen_status if lock else "idle",
        owner_id=lock.owner_id if lock else None,
        error_reason=lock.error_reason if lock else None,
    )


def classify_folder_change(
    root: Path,
    knowledge_path: str,
) -> tuple[ChangeEvent, str, str]:
    """Classify what changed in a knowledge folder vs cached insight state.

    Returns (event, new_content_hash, new_structure_hash).
    Used by the watcher and regen_path to decide whether to trigger regen.
    """
    evaluation = evaluate_folder_state(root, knowledge_path)
    if evaluation.outcome == "metadata_backfill":
        _persist_structure_hash_backfill(root, evaluation)
    event = evaluation.change
    return event, evaluation.content_hash or "", evaluation.structure_hash or ""


@dataclass
class SingleFolderResult:
    """Result of processing a single folder for regen."""

    action: Literal[
        "regenerated",  # Claude called, new summary written to disk
        "skipped_unchanged",  # content hash matched, no work needed
        "skipped_no_content",  # folder exists but empty (no files, no child dirs)
        "skipped_rename",  # structure-only change, no Claude call
        "skipped_similarity",  # similarity guard discarded rewrite
        "skipped_backfill",  # post-v18 migration backfill (hashes updated, no disk change)
        "cleaned_up",  # folder missing → stale insights/state actually deleted
    ]
    knowledge_path: str


# Actions that propagate dirtiness to parent in wave mode
# Actions that do NOT propagate:
# - skipped_unchanged:  nothing changed, ancestors stable
# - skipped_similarity: summary unchanged on disk, ancestors stable
# - skipped_backfill:   only DB metadata updated (structure_hash), no on-disk summary
#                       change — parent content_hash depends on child summaries on disk,
#                       not child state metadata, so no propagation needed


async def regen_single_folder(
    root: Path,
    knowledge_path: str,
    *,
    config: RegenConfig | None = None,
    owner_id: str | None = None,
    session_id: str | None = None,
    regen_id: str | None = None,
    backend: LlmBackend | None = None,
) -> SingleFolderResult:
    """Process a single knowledge folder for regen (no walk-up).

    Returns a ``SingleFolderResult`` describing what happened.
    Raises ``RegenFailed`` on Claude invocation failure.
    """
    if config is None:
        config = RegenConfig.load()
    if regen_id is None:
        regen_id = uuid4().hex[:6]
    if backend is None:
        backend = _InvokeClaudeShim()

    capabilities = resolve_backend_capabilities(backend, model=config.model)
    similarity_threshold = config.similarity_threshold
    evaluation = evaluate_folder_state(root, knowledge_path)
    execution_input = RegenExecutionInput(
        root=root,
        regen_id=regen_id,
        config=config,
        backend=backend,
        capabilities=capabilities,
        session_id=session_id,
        owner_id=owner_id,
        evaluation=evaluation,
    )
    current_path = evaluation.knowledge_path
    knowledge_dir = evaluation.knowledge_dir
    insights_dir = evaluation.insights_dir
    repository = BrainRepository(root)

    if evaluation.outcome == "missing_path":
        log.debug("[%s] Knowledge dir does not exist: %s", regen_id, knowledge_dir)
        try:
            repository.delete_portable_insight_state(current_path)
        except Exception:
            log.warning("Failed to delete sidecar for %s", current_path, exc_info=True)
        if path_is_dir(insights_dir):
            repository.clean_regenerable_insights(current_path)
            log.info("[%s] Cleaned up stale insights for %s", regen_id, current_path)
        delete_regen_lock(root, current_path)
        cleaned_up_rule = propagation_rule("cleaned_up")
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_COMPLETED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="cleaned_up",
            details={
                "reason": "knowledge_path_missing",
                "evaluation_outcome": evaluation.outcome,
                "propagates_up": cleaned_up_rule.propagate_upward,
                "parent_input_changed": cleaned_up_rule.parent_input_changed,
                "propagation_reason": cleaned_up_rule.dirty_reason,
                "propagation_explanation": cleaned_up_rule.explanation,
                "summary_written": False,
                "journal_written": False,
            },
        )
        return SingleFolderResult(action="cleaned_up", knowledge_path=current_path)

    if evaluation.outcome == "no_content":
        log.debug("[%s] No readable files or child dirs in %s, cleaning up", regen_id, current_path or "(root)")
        try:
            repository.delete_portable_insight_state(current_path)
        except Exception:
            log.warning("Failed to delete sidecar for %s", current_path, exc_info=True)
        if path_is_dir(insights_dir):
            repository.clean_regenerable_insights(current_path)
            log.info("[%s] Cleaned up stale insights for %s", regen_id, current_path or "(root)")
        delete_regen_lock(root, current_path)
        no_content_rule = propagation_rule("skipped_no_content")
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_COMPLETED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="skipped_no_content",
            details={
                "reason": "no_direct_files_or_child_summaries",
                "evaluation_outcome": evaluation.outcome,
                "propagates_up": no_content_rule.propagate_upward,
                "parent_input_changed": no_content_rule.parent_input_changed,
                "propagation_reason": no_content_rule.dirty_reason,
                "propagation_explanation": no_content_rule.explanation,
                "summary_written": False,
                "journal_written": False,
            },
        )
        return SingleFolderResult(action="skipped_no_content", knowledge_path=current_path)

    meta = evaluation.meta
    lock = load_regen_lock(root, current_path)
    child_summaries = evaluation.child_summaries
    new_content_hash = evaluation.content_hash
    new_structure_hash = evaluation.structure_hash
    if new_content_hash is None or new_structure_hash is None:
        raise RuntimeError(f"evaluation outcome {evaluation.outcome} must include current hashes")

    # Post-v18 migration backfill: recompute both hashes with current algorithm and set structure_hash
    if evaluation.outcome == "metadata_backfill" and meta is not None:
        log.info(
            "[%s] Backfilling structure_hash for %s (post-v18 migration)",
            regen_id,
            current_path or "(root)",
        )
        _claim_regen_ownership_or_raise(root, current_path, owner_id)
        if owner_id is not None:
            lock = load_regen_lock(root, current_path)
        _persist_area_state_or_fail(
            root,
            repository,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            regen_started_utc=lock.regen_started_utc if lock else None,
            content_hash=new_content_hash,
            summary_hash=meta.summary_hash,
            structure_hash=new_structure_hash,
            last_regen_utc=meta.last_regen_utc if meta else None,
            regen_status="idle",
            release_owner_id=owner_id,
            error_reason=lock.error_reason if lock else None,
        )
        backfill_rule = propagation_rule("skipped_backfill")
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_COMPLETED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="skipped_backfill",
            details={
                "reason": "metadata_backfill_only",
                "evaluation_outcome": evaluation.outcome,
                "propagates_up": backfill_rule.propagate_upward,
                "parent_input_changed": backfill_rule.parent_input_changed,
                "propagation_reason": backfill_rule.dirty_reason,
                "propagation_explanation": backfill_rule.explanation,
                "summary_written": False,
                "journal_written": False,
            },
        )
        return SingleFolderResult(action="skipped_backfill", knowledge_path=current_path)

    if evaluation.outcome == "unchanged":
        log.debug(
            "[%s] Content hash unchanged for %s (hash=%s)",
            regen_id,
            current_path or "(root)",
            new_content_hash[:12],
        )
        unchanged_rule = propagation_rule("skipped_unchanged")
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_COMPLETED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="skipped_unchanged",
            details={
                "reason": "content_hash_unchanged",
                "evaluation_outcome": evaluation.outcome,
                "propagates_up": unchanged_rule.propagate_upward,
                "parent_input_changed": unchanged_rule.parent_input_changed,
                "propagation_reason": unchanged_rule.dirty_reason,
                "propagation_explanation": unchanged_rule.explanation,
                "summary_written": False,
                "journal_written": False,
            },
        )
        return SingleFolderResult(action="skipped_unchanged", knowledge_path=current_path)

    if evaluation.outcome == "structure_only":
        # Rename only — persist updated structure_hash
        log.info(
            "[%s] Structure-only change for %s (rename), updating structure_hash",
            regen_id,
            current_path or "(root)",
        )
        _claim_regen_ownership_or_raise(root, current_path, owner_id)
        if owner_id is not None:
            lock = load_regen_lock(root, current_path)
        _persist_area_state_or_fail(
            root,
            repository,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            regen_started_utc=lock.regen_started_utc if lock else None,
            content_hash=meta.content_hash or new_content_hash if meta else new_content_hash,
            summary_hash=meta.summary_hash if meta else None,
            structure_hash=new_structure_hash,
            last_regen_utc=meta.last_regen_utc if meta else None,
            regen_status="idle",
            release_owner_id=owner_id,
        )
        rename_rule = propagation_rule("skipped_rename")
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_COMPLETED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="skipped_rename",
            details={
                "reason": "structure_only_change",
                "evaluation_outcome": evaluation.outcome,
                "propagates_up": rename_rule.propagate_upward,
                "parent_input_changed": rename_rule.parent_input_changed,
                "propagation_reason": rename_rule.dirty_reason,
                "propagation_explanation": rename_rule.explanation,
                "summary_written": False,
                "journal_written": False,
            },
        )
        return SingleFolderResult(action="skipped_rename", knowledge_path=current_path)

    if evaluation.outcome != "content_changed":
        raise RuntimeError(f"unexpected regen evaluation outcome: {evaluation.outcome}")

    log.debug(
        "[%s] Content hash changed for %s: %s -> %s",
        regen_id,
        current_path or "(root)",
        (meta.content_hash[:12] if meta and meta.content_hash else "none"),
        new_content_hash[:12],
    )

    try:
        # Build prompt
        prompt_result = _build_prompt(
            current_path,
            knowledge_dir,
            child_summaries,
            insights_dir,
            root,
            capabilities=capabilities,
        )
        prompt_diagnostics = prompt_result.diagnostics
    except Exception as e:
        started = datetime.now(UTC).isoformat()
        log.error("Prompt planning failed for %s: %s", current_path or "(root)", e, exc_info=True)
        try:
            _save_terminal_regen_lock(
                root,
                knowledge_path=current_path,
                owner_id=owner_id,
                regen_started_utc=started,
                regen_status="failed",
                error_reason=str(e),
            )
        except Exception as db_err:
            log.error("Failed to persist 'failed' state for %s: %s", current_path, db_err)
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_FAILED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="failed",
            details={
                "error": str(e),
                "reason": "prompt_planning_failed",
                "phase": "planning",
                "evaluation_outcome": evaluation.outcome,
            },
        )
        raise RegenFailed(current_path or "(root)", str(e)) from e

    # Prompt fingerprint for forensic tracing
    prompt_hash = hashlib.sha1(prompt_result.text.encode("utf-8")).hexdigest()[:8]

    # Read old summary for similarity check
    summary_path = insights_dir / "summary.md"
    old_summary = ""
    if path_exists(summary_path):
        old_summary = read_text(summary_path, encoding="utf-8")

    insights_dir.mkdir(parents=True, exist_ok=True)

    # Mark as running — keep old hash so crashes/failures don't block retries
    _claim_regen_ownership_or_raise(root, current_path, owner_id)
    started = datetime.now(UTC).isoformat()
    save_regen_lock(
        root,
        RegenLock(
            knowledge_path=current_path,
            regen_started_utc=started,
            regen_status="running",
            owner_id=owner_id,
        ),
    )
    _record_regen_event(
        root=root,
        event_type=OperationalEventType.REGEN_STARTED,
        knowledge_path=current_path,
        session_id=session_id,
        owner_id=owner_id,
        outcome="started",
        details={
            "reason": "content_changed",
            "evaluation_outcome": evaluation.outcome,
            "prompt_budget_class": prompt_diagnostics.prompt_budget_class if prompt_diagnostics else None,
            "capability_max_prompt_tokens": (
                prompt_diagnostics.capability_max_prompt_tokens if prompt_diagnostics else None
            ),
            "effective_prompt_tokens": prompt_diagnostics.effective_prompt_tokens if prompt_diagnostics else None,
            "prompt_overhead_tokens": prompt_diagnostics.prompt_overhead_tokens if prompt_diagnostics else None,
            "component_tokens": dict(prompt_diagnostics.component_tokens) if prompt_diagnostics else {},
            "deferred_file_count": len(prompt_diagnostics.deferred_files) if prompt_diagnostics else 0,
            "deferred_files": [decision.name for decision in prompt_diagnostics.deferred_files]
            if prompt_diagnostics
            else [],
            "omitted_child_summary_count": len(prompt_diagnostics.omitted_child_summaries) if prompt_diagnostics else 0,
            "omitted_child_summaries": list(prompt_diagnostics.omitted_child_summaries) if prompt_diagnostics else [],
        },
    )

    # Chunk-and-merge + final invoke — unified exception handler
    # ensures "failed" state is always saved on any error.
    chunked_files: list[str] = []
    chunk_count = 0
    try:
        # Chunk-and-merge for oversized files
        if prompt_result.oversized_files:
            chunk_summaries_map: dict[str, list[str]] = {}
            for filename, content in sorted(prompt_result.oversized_files.items()):
                chunks = _split_markdown_chunks(content)
                if len(chunks) > MAX_CHUNKS:
                    raise RegenFailed(
                        current_path or "(root)",
                        f"{filename}: {len(chunks)} chunks exceeds limit of {MAX_CHUNKS}",
                    )
                log.info("[%s] Chunking %s: %d chunks", regen_id, filename, len(chunks))
                chunked_files.append(filename)
                chunk_count += len(chunks)
                file_summaries: list[str] = []
                for i, chunk in enumerate(chunks, 1):
                    heading = _first_heading(chunk) or f"part {i}"
                    chunk_result = await _invoke_execution_backend(
                        execution_input,
                        _build_chunk_prompt(chunk, i, len(chunks), filename, heading),
                        is_chunk=True,
                        max_turns=1,
                    )
                    file_summaries.append(chunk_result.output.strip())
                    log.debug(
                        "[%s] Chunk %d/%d for %s: in=%s out=%s tokens",
                        regen_id,
                        i,
                        len(chunks),
                        filename,
                        chunk_result.input_tokens,
                        chunk_result.output_tokens,
                    )
                chunk_summaries_map[filename] = file_summaries

            # Collect binary_names from the original _build_prompt pass
            binary_names = [
                f.name
                for f in iterdir_paths(knowledge_dir)
                if _is_readable_file(f) and f.suffix.lower() not in TEXT_EXTENSIONS
            ]
            # Rebuild prompt with chunk summaries replacing raw content
            prompt_result = _build_prompt_from_chunks(
                current_path,
                chunk_summaries_map,
                child_summaries,
                insights_dir,
                root,
                binary_names,
                capabilities=capabilities,
            )

        # Invoke Claude in inference mode (minimal system prompt, no tools)
        log.info(
            "[%s] Generating insights: %s (model=%s prompt_hash=%s)",
            regen_id,
            current_path or "(root)",
            config.model,
            prompt_hash,
        )
        result = await _invoke_execution_backend(
            execution_input,
            prompt_result.text,
            is_chunk=False,
            max_turns=config.max_turns,
        )
    except Exception as e:
        log.error("Regen failed for %s: %s", current_path or "(root)", e, exc_info=True)
        try:
            _save_terminal_regen_lock(
                root,
                knowledge_path=current_path,
                owner_id=owner_id,
                regen_started_utc=started,
                regen_status="failed",
                error_reason=str(e),
            )
        except Exception as db_err:
            log.error("Failed to persist 'failed' state for %s: %s", current_path, db_err)
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_FAILED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="failed",
            details={
                "error": str(e),
                "reason": "execution_failed",
                "phase": "execution",
                "evaluation_outcome": evaluation.outcome,
                "chunk_count": chunk_count,
                "chunked_file_count": len(chunked_files),
                "chunked_files": list(chunked_files),
            },
        )
        raise RegenFailed(current_path or "(root)", str(e)) from e
    now = datetime.now(UTC).isoformat()

    # Parse structured output (summary required, journal optional)
    try:
        parsed_artifacts: ParsedArtifacts = parse_structured_output(result.output.strip() if result.output else "")
    except ArtifactContractError as exc:
        err_msg = f"invalid structured output: {exc}"
        try:
            _save_terminal_regen_lock(
                root,
                knowledge_path=current_path,
                owner_id=owner_id,
                regen_started_utc=started,
                regen_status="failed",
                error_reason=err_msg,
            )
        except Exception as db_err:
            log.error("Failed to persist 'failed' state for %s: %s", current_path, db_err)
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_FAILED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="failed_artifact_contract",
            details={
                "error": str(exc),
                "reason": "invalid_structured_output",
                "phase": "artifact_contract",
                "evaluation_outcome": evaluation.outcome,
            },
        )
        raise RegenFailed(current_path or "(root)", err_msg) from exc

    new_summary = parsed_artifacts.summary_text
    journal_text = parsed_artifacts.journal_text
    if len(new_summary) < 20:
        log.warning(
            "[%s] Claude returned empty/tiny output for %s (%d chars). Output: %s",
            regen_id,
            current_path or "(root)",
            len(new_summary),
            result.output[:500],
        )
        err_msg = "Claude returned empty or suspiciously small output"
        try:
            _save_terminal_regen_lock(
                root,
                knowledge_path=current_path,
                owner_id=owner_id,
                regen_started_utc=started,
                regen_status="failed",
                error_reason=err_msg,
            )
        except Exception as db_err:
            log.error("Failed to persist 'failed' state for %s: %s", current_path, db_err)
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_FAILED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="failed",
            details={
                "error": err_msg,
                "reason": "summary_too_small",
                "phase": "output_validation",
                "evaluation_outcome": evaluation.outcome,
            },
        )
        raise RegenFailed(current_path or "(root)", err_msg)

    # Similarity guard
    if old_summary and text_similarity(old_summary, new_summary) > similarity_threshold:
        log.info(
            "[%s] Summary for %s is >%.0f%% similar, discarding rewrite",
            regen_id,
            current_path or "(root)",
            similarity_threshold * 100,
        )
        _commit_artifact_plan_or_fail(
            root,
            repository,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            regen_started_utc=started,
            content_hash=new_content_hash,
            structure_hash=new_structure_hash,
            last_regen_utc=now,
            plan=ArtifactCommitPlan(
                action="skipped_similarity",
                summary_hash=hashlib.sha256(old_summary.encode("utf-8")).hexdigest(),
                summary_text=None,
                journal_text=journal_text,
            ),
            regen_id=regen_id,
        )
        skipped_similarity_rule = propagation_rule("skipped_similarity")
        _record_regen_event(
            root=root,
            event_type=OperationalEventType.REGEN_COMPLETED,
            knowledge_path=current_path,
            session_id=session_id,
            owner_id=owner_id,
            outcome="skipped_similarity",
            details={
                "reason": "similarity_guard_kept_existing_summary",
                "evaluation_outcome": evaluation.outcome,
                "propagates_up": skipped_similarity_rule.propagate_upward,
                "parent_input_changed": skipped_similarity_rule.parent_input_changed,
                "propagation_reason": skipped_similarity_rule.dirty_reason,
                "propagation_explanation": skipped_similarity_rule.explanation,
                "summary_written": False,
                "journal_written": bool(journal_text and journal_text.strip()),
                "chunk_count": chunk_count,
                "chunked_file_count": len(chunked_files),
                "chunked_files": list(chunked_files),
            },
        )
        return SingleFolderResult(action="skipped_similarity", knowledge_path=current_path)

    # Summary changed — repository owns durable summary persistence.
    _commit_artifact_plan_or_fail(
        root,
        repository,
        knowledge_path=current_path,
        session_id=session_id,
        owner_id=owner_id,
        regen_started_utc=started,
        content_hash=new_content_hash,
        structure_hash=new_structure_hash,
        last_regen_utc=now,
        plan=ArtifactCommitPlan(
            action="regenerated",
            summary_hash=hashlib.sha256(new_summary.encode("utf-8")).hexdigest(),
            summary_text=new_summary,
            journal_text=journal_text,
        ),
        regen_id=regen_id,
    )
    log.info(
        "[%s] Regenerated summary for %s (model=%s in=%s out=%s tokens turns=%s)",
        regen_id,
        current_path or "(root)",
        config.model,
        result.input_tokens,
        result.output_tokens,
        result.num_turns,
    )
    regenerated_rule = propagation_rule("regenerated")
    _record_regen_event(
        root=root,
        event_type=OperationalEventType.REGEN_COMPLETED,
        knowledge_path=current_path,
        session_id=session_id,
        owner_id=owner_id,
        outcome="regenerated",
        details={
            "reason": "summary_written",
            "evaluation_outcome": evaluation.outcome,
            "propagates_up": regenerated_rule.propagate_upward,
            "parent_input_changed": regenerated_rule.parent_input_changed,
            "propagation_reason": regenerated_rule.dirty_reason,
            "propagation_explanation": regenerated_rule.explanation,
            "summary_written": True,
            "journal_written": bool(journal_text and journal_text.strip()),
            "chunk_count": chunk_count,
            "chunked_file_count": len(chunked_files),
            "chunked_files": list(chunked_files),
        },
    )
    return SingleFolderResult(action="regenerated", knowledge_path=current_path)


async def regen_path(
    root: Path,
    knowledge_rel_path: str,
    *,
    max_depth: int = 10,
    config: RegenConfig | None = None,
    owner_id: str | None = None,
    session_id: str | None = None,
    backend: LlmBackend | None = None,
) -> int:
    """Run the deterministic incremental regen loop for a knowledge path.

    Starts at the given path, then walks ancestors only while the completed
    action changed a parent-visible input under the shared propagation matrix.

    Returns the number of summaries regenerated.
    """
    if config is None:
        config = RegenConfig.load()
    if backend is None:
        backend = _InvokeClaudeShim()

    regen_id = uuid4().hex[:6]
    regen_count = 0
    current_path = knowledge_rel_path

    for _ in range(max_depth):
        result = await regen_single_folder(
            root,
            current_path,
            config=config,
            owner_id=owner_id,
            session_id=session_id,
            regen_id=regen_id,
            backend=backend,
        )

        if result.action == "regenerated":
            regen_count += 1

        if propagates_up(result.action):
            # Walk up to parent (or break if at root)
            if not current_path:
                break
            parts = current_path.rsplit("/", 1)
            current_path = parts[0] if len(parts) > 1 else ""
            continue

        # Shared propagation contract says stop here.
        break

    return regen_count


async def regen_all(
    root: Path,
    *,
    config: RegenConfig | None = None,
    owner_id: str | None = None,
    session_id: str | None = None,
    backend: LlmBackend | None = None,
) -> int:
    """Regenerate insights for all knowledge paths using topological wave processing.

    Organizes paths into depth-ordered waves (deepest first) and processes each
    wave once. Dirty propagation ensures parents are only processed when at least
    one child actually changed. Each folder is processed at most once.

    Stale-state recovery is the caller's responsibility via ``regen_session``.
    """
    if config is None:
        config = RegenConfig.load()
    if backend is None:
        backend = _InvokeClaudeShim()

    knowledge_root = root / "knowledge"
    content_paths = find_all_content_paths(knowledge_root)

    if not content_paths:
        log.info("No knowledge paths found")
        return 0

    waves = compute_waves(content_paths)
    all_paths = {p for wave in waves for p in wave}

    log.info(
        "Wave regen: %d paths in %d waves (deepest-first)",
        len(all_paths),
        len(waves),
    )

    regen_id = uuid4().hex[:6]
    total = 0
    dirty: set[str] = set(content_paths)  # all leaves start dirty
    failed_paths: list[tuple[str, str]] = []

    for wave_idx, wave in enumerate(waves):
        log.debug("Processing wave %d/%d: %d paths", wave_idx + 1, len(waves), len(wave))

        for path in wave:
            if path not in dirty:
                continue

            log.info("Assessing insights generation: %s", path or "(root)")
            try:
                result = await regen_single_folder(
                    root,
                    path,
                    config=config,
                    owner_id=owner_id,
                    session_id=session_id,
                    regen_id=regen_id,
                    backend=backend,
                )
                if result.action == "regenerated":
                    total += 1
                if propagates_up(result.action) and path:
                    dirty.add(parent_path(path))
                # else: don't propagate — parent stays clean
            except KeyboardInterrupt:
                log.info("Interrupted during regen of %s, stopping batch", path or "(root)")
                raise
            except Exception as e:
                reason = f"{type(e).__name__}: {e}"
                log.warning("Skipping %s: %s", path or "(root)", reason, exc_info=True)
                failed_paths.append((path, reason))
                # Failed paths do NOT propagate dirtiness to parent

    if failed_paths:
        # Terse summary only — full stack traces already emitted per-path above
        log.warning(
            "Batch completed with %d/%d failures: %s",
            len(failed_paths),
            len(all_paths),
            ", ".join(fp or "(root)" for fp, _ in failed_paths),
        )

    # Clean up orphaned insight states whose knowledge dirs no longer exist
    content_path_set = set(content_paths)
    content_path_set.add("")  # root is always valid
    all_paths = set(read_all_regen_meta(root / "knowledge").keys()) | {
        lock.knowledge_path for lock in load_all_regen_locks(root)
    }
    repository = BrainRepository(root)
    orphaned = 0
    for kp in all_paths:
        knowledge_dir = root / "knowledge" / kp if kp else root / "knowledge"
        if not path_is_dir(knowledge_dir) and kp not in content_path_set:
            _delete_area_state(root, repository, kp)
            orphaned += 1
            log.info("Cleaned up orphaned insight state: %s", kp)
    if orphaned:
        log.info("Removed %d orphaned insight states", orphaned)

    return total

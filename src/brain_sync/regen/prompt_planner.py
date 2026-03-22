"""Prompt assembly, budgeting, and chunking helpers for REGEN."""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Literal

from brain_sync.brain.fileops import (
    TEXT_EXTENSIONS,
    iterdir_paths,
    path_exists,
    path_is_dir,
    path_is_file,
    read_bytes,
    read_text,
    rglob_paths,
)
from brain_sync.brain.layout import MANAGED_DIRNAME, area_summary_path
from brain_sync.brain.tree import is_readable_file
from brain_sync.llm import DEFAULT_SYSTEM_PROMPT, BackendCapabilities

log = logging.getLogger(__name__)


def _load_instruction(name: str) -> str:
    """Load an instruction file bundled with the package."""

    ref = resources.files("brain_sync.regen.resources").joinpath(name)
    return ref.read_text(encoding="utf-8")


PROMPT_VERSION = "insight-v2"
REGEN_INSTRUCTIONS = _load_instruction("INSIGHT_INSTRUCTIONS.md")
MINIMAL_SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT

HEADING_RE = re.compile(r"^#{1,6}\s+(.+)", re.MULTILINE)
_BASE64_DATA_URI_RE = re.compile(r"data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+")
_BASE64_MD_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+\)")


@dataclass
class _FileEntry:
    """A file read from the knowledge folder, pending inline/defer decision."""

    name: str
    content: str
    size: int
    inline: bool = True


@dataclass(frozen=True)
class DeferredFileDecision:
    """Why a file was deferred from direct inclusion to chunk fallback."""

    name: str
    estimated_tokens: int
    remaining_tokens_before_defer: int
    reason: str


@dataclass(frozen=True)
class PromptBudgetDiagnostics:
    """Explain how prompt budget was allocated for one regen prompt."""

    prompt_budget_class: str
    capability_max_prompt_tokens: int
    effective_prompt_tokens: int
    prompt_overhead_tokens: int
    component_tokens: dict[str, int]
    deferred_files: tuple[DeferredFileDecision, ...]
    omitted_child_summaries: tuple[str, ...]


@dataclass
class PromptResult:
    """Result from prompt construction."""

    text: str
    oversized_files: dict[str, str] | None = None
    diagnostics: PromptBudgetDiagnostics | None = None


@dataclass(frozen=True)
class PromptPlannerSettings:
    """Bounded prompt-planning settings supplied by the engine."""

    instructions: str
    legacy_max_prompt_tokens: int
    max_prompt_tokens: int
    standard_prompt_budget_tokens: int
    extended_prompt_budget_tokens: int


@dataclass
class _GlobalContextCache:
    """Cached global context for prompt assembly."""

    mode: Literal["core_raw", "core_summary"]
    content_hash: str
    compiled_text: str


_global_context_cache: _GlobalContextCache | None = None
_context_cache_lock = threading.Lock()


def first_heading(text: str) -> str | None:
    """Extract the first markdown heading from text."""

    match = HEADING_RE.search(text)
    return match.group(1).strip() if match else None


def preprocess_content(content: str, filename: str) -> str:
    """Preprocess file content before prompt assembly."""

    original_len = len(content)
    content = _BASE64_MD_IMAGE_RE.sub(
        lambda match: f"[diagram: {match.group(1)}]" if match.group(1) else "[image removed]",
        content,
    )
    content = _BASE64_DATA_URI_RE.sub("[image removed]", content)
    content = re.sub(r"\n{4,}", "\n\n\n", content)

    new_len = len(content)
    if new_len < original_len:
        reduction = (1 - new_len / original_len) * 100
        log.info("Preprocessed %s: %d → %d chars (%.0f%% reduction)", filename, original_len, new_len, reduction)

    return content


def _assemble_files_text(
    inlined: list[tuple[str, str]],
    oversized_names: list[str],
    binary_names: list[str],
) -> str:
    """Build the files section of the prompt."""

    parts: list[str] = []
    inlined_parts: list[str] = []
    for name, content in inlined:
        inlined_parts.append(f"### {name}\n```\n{content}\n```")
    for name in oversized_names:
        inlined_parts.append(f"### {name}\n(This file will be summarized in chunks — too large to inline)")
    if inlined_parts:
        parts.append("The knowledge folder contains these files:\n" + "\n\n".join(inlined_parts))
    if binary_names:
        file_list = "\n".join(f"- {name}" for name in binary_names)
        parts.append(f"The folder also contains these binary files (not inlined):\n{file_list}")
    return "\n\n".join(parts) + "\n" if parts else ""


def _assemble_prompt(
    instructions: str,
    global_context: str,
    files_text: str,
    children_text: str,
    existing_summary: str,
    display_path: str,
) -> str:
    """Assemble the full regen prompt."""

    output_directive = """Wrap your output in XML tags as shown below.
If nothing is journal-worthy, leave the journal section empty.
Return only the XML sections. Do not include any text outside the tags.

<summary>
…the updated summary…
</summary>

<journal>
…journal entry, or empty if nothing meaningful changed…
</journal>"""

    return f"""{instructions}

---

{global_context}

---

You are regenerating the insight summary for knowledge area: {display_path}
{files_text}{children_text}
{"The current summary is:" + chr(10) + existing_summary if existing_summary else "There is no existing summary yet."}

{output_directive}"""


def invalidate_global_context_cache() -> None:
    """Invalidate the cached global context."""

    global _global_context_cache
    with _context_cache_lock:
        _global_context_cache = None
    log.debug("Global context cache invalidated")


def _iter_core_raw_context_files(core_dir: Path):
    """Yield raw `_core` files eligible for inclusion in `_core` regen context."""

    if not path_is_dir(core_dir):
        return
    for path in rglob_paths(core_dir, "*"):
        if (
            path_is_file(path)
            and path.suffix.lower() in TEXT_EXTENSIONS
            and not path.name.startswith(("_", "."))
            and MANAGED_DIRNAME not in path.parts
        ):
            yield path


def _hash_core_raw_context(core_dir: Path) -> str:
    """Hash the raw `_core` files used when regenerating `_core` itself."""

    h = hashlib.sha256()
    for path in _iter_core_raw_context_files(core_dir):
        rel = path.relative_to(core_dir)
        h.update(str(rel).encode("utf-8"))
        h.update(read_bytes(path))
    return h.hexdigest()


def _hash_core_summary_context(summary_path: Path) -> str:
    """Hash the single `_core` summary file used for non-`_core` regen."""

    h = hashlib.sha256()
    if path_is_file(summary_path):
        h.update(b"summary.md")
        h.update(read_bytes(summary_path))
    return h.hexdigest()


def collect_global_context(root: Path, current_path: str) -> str:
    """Collect and inline global context from `_core` meaning."""

    global _global_context_cache

    core_dir = root / "knowledge" / "_core"
    core_summary_path = area_summary_path(root, "_core")
    mode: Literal["core_raw", "core_summary"] = "core_raw" if current_path == "_core" else "core_summary"
    content_hash = (
        _hash_core_raw_context(core_dir) if mode == "core_raw" else _hash_core_summary_context(core_summary_path)
    )

    with _context_cache_lock:
        if _global_context_cache is not None and _global_context_cache.mode == mode:
            if _global_context_cache.content_hash == content_hash:
                log.debug("Global context cache hit")
                return _global_context_cache.compiled_text

    log.debug("Global context cache miss, rebuilding")
    sections: list[str] = []

    if mode == "core_raw" and path_is_dir(core_dir):
        parts: list[str] = []
        count = 0
        for path in _iter_core_raw_context_files(core_dir):
            try:
                content = read_text(path, encoding="utf-8")
                rel = path.relative_to(core_dir)
                parts.append(f"### {rel}\n```\n{content}\n```")
                count += 1
            except (OSError, UnicodeDecodeError) as exc:
                log.debug("Skipping unreadable file %s: %s", path, exc)
        if parts:
            sections.append("## Global Context: knowledge/_core\n" + "\n\n".join(parts))
            log.debug("Global context: %d raw files from knowledge/_core for _core regen", count)

    if mode == "core_summary" and path_is_file(core_summary_path):
        try:
            content = read_text(core_summary_path, encoding="utf-8")
            sections.append(
                "## Global Context: knowledge/_core/.brain-sync/insights/summary.md\n"
                f"### summary.md\n```\n{content}\n```"
            )
            log.debug("Global context: loaded _core summary for non-_core regen")
        except (OSError, UnicodeDecodeError) as exc:
            log.debug("Skipping unreadable _core summary %s: %s", core_summary_path, exc)

    compiled = "\n\n".join(sections)
    with _context_cache_lock:
        _global_context_cache = _GlobalContextCache(mode=mode, content_hash=content_hash, compiled_text=compiled)

    total_chars = len(compiled)
    log.debug("Global context compiled: %d chars (~%d tokens est.)", total_chars, total_chars // 3)
    return compiled


def estimate_tokens(text: str) -> int:
    """Return the planner's lightweight token estimate for *text*."""

    return len(text) // 3


def resolve_effective_prompt_budget(
    capabilities: BackendCapabilities | None,
    settings: PromptPlannerSettings,
) -> tuple[int, str, int]:
    """Resolve the effective prompt budget for one prompt build."""

    if settings.max_prompt_tokens != settings.legacy_max_prompt_tokens:
        return settings.max_prompt_tokens, "legacy_override", settings.max_prompt_tokens
    if capabilities is None:
        return settings.legacy_max_prompt_tokens, "legacy_fixed", settings.legacy_max_prompt_tokens

    capability_max = capabilities.max_prompt_tokens
    if capabilities.prompt_budget_class == "extended_1m" or capability_max >= 1_000_000:
        return (
            min(capability_max, settings.extended_prompt_budget_tokens),
            capabilities.prompt_budget_class,
            capability_max,
        )
    if capability_max >= 200_000:
        return (
            min(capability_max, settings.standard_prompt_budget_tokens),
            capabilities.prompt_budget_class,
            capability_max,
        )
    return min(capability_max, settings.legacy_max_prompt_tokens), capabilities.prompt_budget_class, capability_max


def _pack_child_summaries(
    child_summaries: dict[str, str],
    *,
    remaining_tokens: int,
    display_path: str,
) -> tuple[str, tuple[str, ...], int]:
    """Pack child summaries into the remaining prompt budget."""

    if not child_summaries or remaining_tokens <= 0:
        omitted_names: tuple[str, ...] = (
            tuple(sorted(child_summaries)) if child_summaries and remaining_tokens <= 0 else ()
        )
        if omitted_names:
            log.info(
                "Omitted %d child summaries for %s (no budget remained after higher-priority context)",
                len(omitted_names),
                display_path,
            )
        return "", omitted_names, 0

    loaded_parts: list[str] = []
    omitted: list[str] = []
    used_tokens = 0
    for name, content in sorted(child_summaries.items()):
        child_part = f"\n### {name}\n{content}"
        child_tokens = estimate_tokens(child_part)
        if used_tokens + child_tokens > remaining_tokens:
            omitted.append(name)
            continue
        loaded_parts.append(child_part)
        used_tokens += child_tokens

    if omitted:
        log.info(
            "Omitted %d child summaries for %s (remaining prompt budget=%d tokens after higher-priority context)",
            len(omitted),
            display_path,
            remaining_tokens,
        )
    total = len(child_summaries)
    loaded = total - len(omitted)
    header = f"Sub-area summaries ({loaded} of {total} loaded):" if omitted else "Sub-area summaries:"
    footer = f"\n({len(omitted)} sub-area summaries omitted — prompt budget)" if omitted else ""
    children_text = f"\n{header}{''.join(loaded_parts)}{footer}\n" if loaded_parts else ""
    return children_text, tuple(omitted), used_tokens


def _pack_direct_files(
    entries: list[_FileEntry],
    *,
    remaining_tokens: int,
    display_path: str,
) -> tuple[list[tuple[str, str]], list[str], dict[str, str] | None, tuple[DeferredFileDecision, ...], int]:
    """Pack direct files into the remaining prompt budget before chunk fallback."""

    original_order = {entry.name: index for index, entry in enumerate(entries)}
    deferred: list[DeferredFileDecision] = []
    used_tokens = 0

    for entry in sorted(entries, key=lambda item: item.size, reverse=True):
        formatted_tokens = estimate_tokens(f"### {entry.name}\n```\n{entry.content}\n```")
        remaining_after_loaded = max(0, remaining_tokens - used_tokens)
        if formatted_tokens <= remaining_after_loaded:
            used_tokens += formatted_tokens
            continue
        entry.inline = False
        deferred.append(
            DeferredFileDecision(
                name=entry.name,
                estimated_tokens=formatted_tokens,
                remaining_tokens_before_defer=remaining_after_loaded,
                reason="exceeds_remaining_direct_file_budget",
            )
        )
        log.info(
            "Deferred %s (~%d tokens) to chunking for %s (remaining=%d effective budget tokens)",
            entry.name,
            formatted_tokens,
            display_path,
            remaining_after_loaded,
        )

    inlined = [
        (entry.name, entry.content)
        for entry in sorted(entries, key=lambda item: original_order[item.name])
        if entry.inline
    ]
    oversized_names = [
        entry.name for entry in sorted(entries, key=lambda item: original_order[item.name]) if not entry.inline
    ]
    oversized_files: dict[str, str] | None = {
        entry.name: entry.content
        for entry in sorted(entries, key=lambda item: original_order[item.name])
        if not entry.inline
    } or None
    return inlined, oversized_names, oversized_files, tuple(deferred), used_tokens


def build_chunk_prompt(
    chunk: str,
    chunk_idx: int,
    total_chunks: int,
    filename: str,
    first_heading_text: str,
) -> str:
    """Build a lightweight prompt for summarizing a single chunk."""

    return f"""Summarize this section while preserving all requirements, decisions,
technical constraints, and implementation details. Do not omit
substantive information. Maintain lists, structure, and terminology.

This document may contain [image removed] or [diagram: ...] placeholders.
Treat [image removed] and [diagram: ...] as references to diagrams or UI screenshots.
Preserve any functional meaning implied by surrounding text.
Do not attempt to reconstruct the images.

[Chunk {chunk_idx}/{total_chunks} — section: {first_heading_text}]
File: {filename}

---
{chunk}
---

Output a thorough summary of this section now."""


def split_markdown_chunks(
    content: str,
    target_chars: int,
    *,
    _level: int | None = None,
) -> list[str]:
    """Split markdown content into chunks at heading boundaries."""

    if len(content) <= target_chars:
        return [content]

    if _level is None:
        match = HEADING_RE.search(content)
        if match:
            _level = len(match.group(0).split()[0])
        else:
            _level = 1

    if _level <= 3:
        pattern = re.compile(rf"(?=^#{{1,{_level}}} )", re.MULTILINE)
        sections = [section for section in pattern.split(content) if section]
        if len(sections) > 1:
            chunks: list[str] = []
            current = ""
            for section in sections:
                if current and len(current) + len(section) > target_chars:
                    chunks.append(current)
                    current = section
                else:
                    current += section
            if current:
                chunks.append(current)

            result: list[str] = []
            for chunk in chunks:
                if len(chunk) > target_chars:
                    result.extend(split_markdown_chunks(chunk, target_chars, _level=_level + 1))
                else:
                    result.append(chunk)
            return result

    paragraphs = content.split("\n\n")
    if len(paragraphs) <= 1:
        return [content]

    chunks = []
    current = ""
    for paragraph in paragraphs:
        candidate = current + "\n\n" + paragraph if current else paragraph
        if current and len(candidate) > target_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def build_prompt(
    knowledge_path: str,
    knowledge_dir: Path,
    child_summaries: dict[str, str],
    insights_dir: Path,
    root: Path,
    *,
    capabilities: BackendCapabilities | None,
    settings: PromptPlannerSettings,
    preprocess_content_fn: Callable[[str, str], str] = preprocess_content,
    collect_global_context_fn: Callable[[Path, str], str] = collect_global_context,
) -> PromptResult:
    """Build the prompt for regenerating an insight summary."""

    instructions = settings.instructions
    global_context = collect_global_context_fn(root, knowledge_path)
    effective_prompt_tokens, prompt_budget_class, capability_max_prompt_tokens = resolve_effective_prompt_budget(
        capabilities,
        settings,
    )

    entries: list[_FileEntry] = []
    binary_names: list[str] = []
    files = [path for path in iterdir_paths(knowledge_dir) if is_readable_file(path)]
    for file_path in files:
        if file_path.suffix.lower() in TEXT_EXTENSIONS:
            try:
                content = read_text(file_path, encoding="utf-8")
                content = preprocess_content_fn(content, file_path.name)
                entries.append(_FileEntry(name=file_path.name, content=content, size=len(content)))
            except (OSError, UnicodeDecodeError):
                binary_names.append(file_path.name)
        else:
            binary_names.append(file_path.name)

    existing_summary = ""
    summary_path = insights_dir / "summary.md"
    if path_exists(summary_path):
        existing_summary = read_text(summary_path, encoding="utf-8")

    display_path = knowledge_path or "(root)"
    empty_files_text = _assemble_files_text([], [], binary_names)
    base_prompt_without_files_or_children = _assemble_prompt(
        instructions,
        global_context,
        empty_files_text,
        "",
        existing_summary,
        display_path,
    )
    remaining_for_direct_files = max(
        0,
        effective_prompt_tokens - estimate_tokens(base_prompt_without_files_or_children),
    )
    inlined, oversized_names, oversized_files, deferred_files, direct_file_tokens = _pack_direct_files(
        entries,
        remaining_tokens=remaining_for_direct_files,
        display_path=display_path,
    )

    files_text = _assemble_files_text(inlined, oversized_names, binary_names)
    base_prompt_without_children = _assemble_prompt(
        instructions,
        global_context,
        files_text,
        "",
        existing_summary,
        display_path,
    )
    remaining_for_children = max(0, effective_prompt_tokens - estimate_tokens(base_prompt_without_children))
    children_text, omitted_child_summaries, child_tokens_used = _pack_child_summaries(
        child_summaries,
        remaining_tokens=remaining_for_children,
        display_path=display_path,
    )

    prompt = _assemble_prompt(
        instructions,
        global_context,
        files_text,
        children_text,
        existing_summary,
        display_path,
    )

    estimated_tokens = estimate_tokens(prompt)
    if estimated_tokens > effective_prompt_tokens:
        log.warning(
            "Prompt still exceeds effective budget after packing for %s: ~%d tokens vs %d effective",
            display_path,
            estimated_tokens,
            effective_prompt_tokens,
        )

    diagnostics = PromptBudgetDiagnostics(
        prompt_budget_class=prompt_budget_class,
        capability_max_prompt_tokens=capability_max_prompt_tokens,
        effective_prompt_tokens=effective_prompt_tokens,
        prompt_overhead_tokens=capabilities.invocation.prompt_overhead_tokens if capabilities else 0,
        component_tokens={
            "instructions": estimate_tokens(instructions),
            "global_context": estimate_tokens(global_context),
            "direct_files": direct_file_tokens,
            "child_summaries": child_tokens_used,
            "existing_summary": estimate_tokens(existing_summary),
            "scaffold": max(
                0,
                estimated_tokens
                - estimate_tokens(instructions)
                - estimate_tokens(global_context)
                - direct_file_tokens
                - child_tokens_used
                - estimate_tokens(existing_summary),
            ),
            "total": estimated_tokens,
        },
        deferred_files=deferred_files,
        omitted_child_summaries=omitted_child_summaries,
    )
    return PromptResult(text=prompt, oversized_files=oversized_files, diagnostics=diagnostics)


def build_prompt_from_chunks(
    knowledge_path: str,
    chunk_summaries: dict[str, list[str]],
    child_summaries: dict[str, str],
    insights_dir: Path,
    root: Path,
    binary_names: list[str],
    *,
    capabilities: BackendCapabilities | None,
    settings: PromptPlannerSettings,
    collect_global_context_fn: Callable[[Path, str], str] = collect_global_context,
) -> PromptResult:
    """Build a merge prompt using chunk summaries instead of raw file content."""

    instructions = settings.instructions
    global_context = collect_global_context_fn(root, knowledge_path)
    effective_prompt_tokens, prompt_budget_class, capability_max_prompt_tokens = resolve_effective_prompt_budget(
        capabilities,
        settings,
    )

    files_parts: list[str] = []
    for filename in sorted(chunk_summaries.keys()):
        summaries = chunk_summaries[filename]
        chunk_parts: list[str] = []
        for index, summary in enumerate(summaries, 1):
            heading = first_heading(summary) or f"part {index}"
            chunk_parts.append(f"#### Chunk {index}/{len(summaries)} — section: {heading}\n{summary}")
        files_parts.append(
            f"### {filename} (summarized in {len(summaries)} chunks — original too large to inline)\n\n"
            + "\n\n".join(chunk_parts)
        )

    if binary_names:
        file_list = "\n".join(f"- {name}" for name in binary_names)
        files_parts.append(f"The folder also contains these binary files (not inlined):\n{file_list}")

    files_text = "The knowledge folder contains these files:\n" + "\n\n".join(files_parts) + "\n" if files_parts else ""

    existing_summary = ""
    summary_path = insights_dir / "summary.md"
    if path_exists(summary_path):
        existing_summary = read_text(summary_path, encoding="utf-8")

    display_path = knowledge_path or "(root)"
    base_prompt_without_children = _assemble_prompt(
        instructions,
        global_context,
        files_text,
        "",
        existing_summary,
        display_path,
    )
    remaining_for_children = max(0, effective_prompt_tokens - estimate_tokens(base_prompt_without_children))
    children_text, omitted_child_summaries, child_tokens_used = _pack_child_summaries(
        child_summaries,
        remaining_tokens=remaining_for_children,
        display_path=display_path,
    )

    prompt = _assemble_prompt(
        instructions,
        global_context,
        files_text,
        children_text,
        existing_summary,
        display_path,
    )

    diagnostics = PromptBudgetDiagnostics(
        prompt_budget_class=prompt_budget_class,
        capability_max_prompt_tokens=capability_max_prompt_tokens,
        effective_prompt_tokens=effective_prompt_tokens,
        prompt_overhead_tokens=capabilities.invocation.prompt_overhead_tokens if capabilities else 0,
        component_tokens={
            "instructions": estimate_tokens(instructions),
            "global_context": estimate_tokens(global_context),
            "direct_files": estimate_tokens(files_text),
            "child_summaries": child_tokens_used,
            "existing_summary": estimate_tokens(existing_summary),
            "total": estimate_tokens(prompt),
        },
        deferred_files=(),
        omitted_child_summaries=omitted_child_summaries,
    )
    return PromptResult(text=prompt, diagnostics=diagnostics)


__all__ = [
    "MINIMAL_SYSTEM_PROMPT",
    "PROMPT_VERSION",
    "REGEN_INSTRUCTIONS",
    "DeferredFileDecision",
    "PromptBudgetDiagnostics",
    "PromptPlannerSettings",
    "PromptResult",
    "build_chunk_prompt",
    "build_prompt",
    "build_prompt_from_chunks",
    "collect_global_context",
    "estimate_tokens",
    "first_heading",
    "invalidate_global_context_cache",
    "preprocess_content",
    "resolve_effective_prompt_budget",
    "split_markdown_chunks",
]

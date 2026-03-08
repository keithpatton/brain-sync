"""Insight regeneration engine.

Deterministic incremental recomputation loop (Make/Bazel model):
- Every folder is treated identically: summary = readable files + child summaries
- Loop walks up ancestors, stops when summary hash is unchanged
- Similarity guard prevents trivial LLM rewording (>0.97 → discard)

Architectural boundary: Python handles all orchestration (context assembly,
hash comparison, scheduling, validation). The LLM is a pure function:
assembled context in → summary.md out.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from importlib import resources
from pathlib import Path
from uuid import uuid4

from brain_sync.commands.context import CONFIG_FILE
from brain_sync.fileops import EXCLUDED_DIRS, IMAGE_EXTENSIONS, KNOWLEDGE_EXTENSIONS, TEXT_EXTENSIONS
from brain_sync.fs_utils import (
    find_all_content_paths,
    get_child_dirs,
    is_content_dir,
    is_readable_file,
)
from brain_sync.state import (
    InsightState,
    delete_insight_state,
    load_insight_state,
    reset_running_insight_states,
    save_insight_state,
)


def _load_instruction(name: str) -> str:
    """Load an instruction file bundled with the package."""
    ref = resources.files("brain_sync.instructions").joinpath(name)
    return ref.read_text(encoding="utf-8")


# Loaded once at import time — the single consolidated instruction set
PROMPT_VERSION = "insight-v2"
_REGEN_INSTRUCTIONS = _load_instruction("INSIGHT_INSTRUCTIONS.md")

# Journal instructions — conditionally appended when write_journal=True
_JOURNAL_INSTRUCTIONS = """
## Journal Entry

Write a journal entry capturing what changed and any significant observations.

Write the journal entry to the path given at the end of this prompt.
Keep entries concise. Distinguish between facts, interpretations, and open
questions. Use `## YYYY-MM-DD` headings.

Do not write a journal entry if the knowledge change is trivial (formatting,
minor wording). Only journal when something meaningful shifted.
"""

log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.97
CLAUDE_TIMEOUT = 300  # seconds
MAX_PROMPT_TOKENS = 120_000  # estimated via len(text) // 3
MIN_CHILDREN = 5  # always include at least this many child summaries


# Aliases for backward compat within this module
_is_readable_file = is_readable_file
_is_content_dir = is_content_dir


@dataclass
class RegenConfig:
    """Configuration for the insights agent."""
    model: str = "claude-sonnet-4-6"
    effort: str = "low"  # low, medium, high — controls thinking budget
    timeout: int = CLAUDE_TIMEOUT
    max_turns: int = 6
    similarity_threshold: float = SIMILARITY_THRESHOLD
    write_journal: bool = False

    @classmethod
    def load(cls) -> RegenConfig:
        """Load regen config from ~/.brain-sync/config.json."""
        if not CONFIG_FILE.exists():
            return cls()
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            regen = data.get("regen", {})
            return cls(
                model=regen.get("model", "claude-sonnet-4-6"),
                effort=regen.get("effort", "low"),
                timeout=regen.get("timeout", CLAUDE_TIMEOUT),
                max_turns=regen.get("max_turns", 6),
                similarity_threshold=regen.get("similarity_threshold", SIMILARITY_THRESHOLD),
                write_journal=regen.get("write_journal", False),
            )
        except (json.JSONDecodeError, OSError):
            return cls()


def folder_content_hash(folder: Path) -> str:
    """Compute sha256 of all readable files in a folder.

    Only files matching READABLE_EXTENSIONS are included.
    Files are sorted by name for determinism. Returns hex digest.
    """
    h = hashlib.sha256()
    files = sorted(p for p in folder.iterdir() if _is_readable_file(p))
    for p in files:
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()


def text_similarity(a: str, b: str) -> float:
    """Compute text similarity between two strings after normalising whitespace."""
    def normalise(s: str) -> str:
        return " ".join(s.split())
    return SequenceMatcher(None, normalise(a), normalise(b)).ratio()


@dataclass
class ClaudeResult:
    """Result from a Claude CLI invocation."""
    success: bool
    output: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    num_turns: int | None = None


@dataclass
class PromptResult:
    """Result from prompt construction."""
    text: str
    has_binary_files: bool


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
# Global context cache — built once, invalidated by watcher
# ---------------------------------------------------------------------------

@dataclass
class _GlobalContextCache:
    """Cached global context for prompt assembly."""
    content_hash: str
    compiled_text: str


_global_context_cache: _GlobalContextCache | None = None


def invalidate_global_context_cache() -> None:
    """Invalidate the cached global context. Called by the watcher."""
    global _global_context_cache
    _global_context_cache = None
    log.debug("Global context cache invalidated")


def _hash_directory(directory: Path) -> str:
    """Compute a hash over all readable files in a directory tree."""
    h = hashlib.sha256()
    if not directory.is_dir():
        return h.hexdigest()
    for p in sorted(directory.rglob("*")):
        if p.is_file() and not p.name.startswith("."):
            h.update(str(p.relative_to(directory)).encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest()


def _collect_global_context(root: Path, current_path: str) -> str:
    """Collect and inline global context from knowledge/_core, schemas, insights/_core.

    Uses a module-level cache keyed by content hash. Rebuilt only when files change.
    """
    global _global_context_cache

    core_dir = root / "knowledge" / "_core"
    schemas_dir = root / "schemas"
    insights_core_dir = root / "insights" / "_core"

    # Compute combined hash for cache validation
    combined = hashlib.sha256()
    combined.update(_hash_directory(core_dir).encode())
    combined.update(_hash_directory(schemas_dir).encode())
    combined.update(_hash_directory(insights_core_dir).encode())
    content_hash = combined.hexdigest()

    if _global_context_cache and _global_context_cache.content_hash == content_hash:
        log.debug("Global context cache hit")
        return _global_context_cache.compiled_text

    log.debug("Global context cache miss, rebuilding")
    sections: list[str] = []

    # 1. knowledge/_core
    if core_dir.is_dir():
        parts: list[str] = []
        count = 0
        for p in sorted(core_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS and not p.name.startswith(("_", ".")):
                try:
                    content = p.read_text(encoding="utf-8")
                    rel = p.relative_to(core_dir)
                    parts.append(f"### {rel}\n```\n{content}\n```")
                    count += 1
                except (OSError, UnicodeDecodeError):
                    pass
        if parts:
            sections.append("## Global Context: knowledge/_core\n" + "\n\n".join(parts))
            log.debug("Global context: %d files from knowledge/_core", count)

    # 2. schemas
    if schemas_dir.is_dir():
        parts = []
        count = 0
        for p in sorted(schemas_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in {".md", ".txt"} and not p.name.startswith("."):
                try:
                    content = p.read_text(encoding="utf-8")
                    rel = p.relative_to(schemas_dir)
                    parts.append(f"### {rel}\n```\n{content}\n```")
                    count += 1
                except (OSError, UnicodeDecodeError):
                    pass
        if parts:
            sections.append("## Global Context: schemas\n" + "\n\n".join(parts))
            log.debug("Global context: %d files from schemas", count)

    # 3. insights/_core (excluding journal/)
    if insights_core_dir.is_dir():
        parts = []
        count = 0
        for p in sorted(insights_core_dir.rglob("*")):
            if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS and not p.name.startswith(("_", ".")):
                # Skip journal entries
                try:
                    rel = p.relative_to(insights_core_dir)
                    if str(rel).startswith("journal"):
                        continue
                    # Skip self-reference when regenerating _core
                    if current_path == "_core" and rel.name == "summary.md" and len(rel.parts) == 1:
                        continue
                    content = p.read_text(encoding="utf-8")
                    parts.append(f"### {rel}\n```\n{content}\n```")
                    count += 1
                except (OSError, UnicodeDecodeError):
                    pass
        if parts:
            sections.append("## Global Context: insights/_core\n" + "\n\n".join(parts))
            log.debug("Global context: %d files from insights/_core", count)

    compiled = "\n\n".join(sections)
    _global_context_cache = _GlobalContextCache(content_hash=content_hash, compiled_text=compiled)

    total_chars = len(compiled)
    log.debug("Global context compiled: %d chars (~%d tokens est.)", total_chars, total_chars // 3)
    return compiled


# ---------------------------------------------------------------------------
# Claude CLI invocation
# ---------------------------------------------------------------------------

async def invoke_claude(
    prompt: str,
    cwd: Path,
    timeout: int = CLAUDE_TIMEOUT,
    model: str = "",
    effort: str = "",
    max_turns: int = 6,
    allowed_tools: str = "Write",
) -> ClaudeResult:
    """Invoke Claude CLI in non-interactive mode.

    Prompt is delivered via stdin to avoid the extra Read turn
    that the temp-file indirection pattern caused.
    """
    cmd = [
        "claude", "--print",
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--disable-slash-commands",
        "--max-turns", str(max_turns),
        "--allowedTools", allowed_tools,
    ]
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])

    log.debug("Claude CLI cmd: %s", " ".join(c for c in cmd))

    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        log.warning("Claude CLI timed out after %ds", timeout)
        return ClaudeResult(success=False, output="")

    stderr_text = stderr.decode("utf-8", errors="replace").strip()
    stdout_text = stdout.decode("utf-8", errors="replace")

    if stderr_text:
        for line in stderr_text.splitlines():
            log.info("Claude CLI: %s", line)

    if proc.returncode != 0:
        log.warning("Claude CLI failed (rc=%d): %s", proc.returncode, stderr_text[:500])
        return ClaudeResult(success=False, output="")

    # Parse JSON output for token counts
    input_tokens = None
    output_tokens = None
    num_turns = None
    result_text = stdout_text
    try:
        data = json.loads(stdout_text)
        result_text = data.get("result", stdout_text)
        usage = data.get("usage", {})
        input_tokens = usage.get("input_tokens")
        output_tokens = usage.get("output_tokens")
        duration_ms = data.get("duration_ms")
        num_turns = data.get("num_turns")
        log.info("Claude CLI: model=%s tokens=%s/%s turns=%s duration=%ss",
                 model or "default",
                 input_tokens, output_tokens,
                 num_turns,
                 f"{duration_ms / 1000:.1f}" if duration_ms else "?")
        if data.get("is_error") or data.get("subtype", "").startswith("error"):
            log.warning("Claude CLI error subtype: %s", data.get("subtype"))
            return ClaudeResult(
                success=False, output=result_text,
                input_tokens=input_tokens, output_tokens=output_tokens,
                num_turns=num_turns,
            )
    except (json.JSONDecodeError, TypeError):
        log.debug("Claude CLI output was not JSON, falling back to stderr parsing")
        input_tokens, output_tokens = _parse_token_counts(stderr_text)

    return ClaudeResult(
        success=True, output=result_text,
        input_tokens=input_tokens, output_tokens=output_tokens,
        num_turns=num_turns,
    )


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_prompt(
    knowledge_path: str,
    knowledge_dir: Path,
    child_summaries: dict[str, str],
    insights_dir: Path,
    root: Path,
    *,
    write_journal: bool = False,
) -> PromptResult:
    """Build the prompt for regenerating an insight summary.

    Sections are assembled in a fixed deterministic order — never reorder:
    1. Instructions (INSIGHT_INSTRUCTIONS)
    2. Global context (knowledge/_core → schemas → insights/_core)
    3. Node content (knowledge files for leaf, child summaries for parent)
    4. Existing summary
    5. Output path(s)
    """
    # 1. Instructions
    instructions = _REGEN_INSTRUCTIONS
    if write_journal:
        instructions += _JOURNAL_INSTRUCTIONS

    # 2. Global context (inlined by Python, not discovered by agent)
    global_context = _collect_global_context(root, knowledge_path)

    # 3a. Direct files section — inline text files, list binary ones
    files_text = ""
    has_binary_files = False
    files = sorted(p for p in knowledge_dir.iterdir() if _is_readable_file(p))
    if files:
        inlined_parts: list[str] = []
        binary_files: list[Path] = []
        for f in files:
            if f.suffix.lower() in TEXT_EXTENSIONS:
                try:
                    content = f.read_text(encoding="utf-8")
                    inlined_parts.append(f"### {f.name}\n```\n{content}\n```")
                except (OSError, UnicodeDecodeError):
                    binary_files.append(f)
            else:
                binary_files.append(f)

        parts: list[str] = []
        if inlined_parts:
            parts.append("The knowledge folder contains these files:\n" + "\n\n".join(inlined_parts))
        if binary_files:
            has_binary_files = True
            file_list = "\n".join(f"- {p}" for p in binary_files)
            parts.append(f"Read these files (binary/non-text) using the Read tool:\n{file_list}")
        files_text = "\n\n".join(parts) + "\n" if parts else ""

    # 3b. Child summaries section — adaptive loading with token budget
    children_text = ""
    if child_summaries:
        loaded_parts: list[str] = []
        skipped = 0
        total = len(child_summaries)
        current_tokens = len(instructions + global_context + files_text) // 3
        for i, (name, content) in enumerate(sorted(child_summaries.items())):
            child_tokens = len(content) // 3
            if i >= MIN_CHILDREN and current_tokens + child_tokens > MAX_PROMPT_TOKENS:
                skipped += 1
                continue
            loaded_parts.append(f"\n### {name}\n{content}")
            current_tokens += child_tokens
        if skipped:
            log.info("Truncated %d child summaries for %s (token budget)", skipped, knowledge_path or "(root)")
        loaded = total - skipped
        header = f"Sub-area summaries ({loaded} of {total} loaded):" if skipped else "Sub-area summaries:"
        footer = f"\n({skipped} sub-area summaries omitted — token budget)" if skipped else ""
        children_text = f"\n{header}{''.join(loaded_parts)}{footer}\n"

    # 4. Existing summary
    existing_summary = ""
    summary_path = insights_dir / "summary.md"
    if summary_path.exists():
        existing_summary = summary_path.read_text(encoding="utf-8")

    display_path = knowledge_path or "(root)"

    # 5. Output paths
    output_lines = [f"Write the summary to: {insights_dir / 'summary.md'}"]
    if write_journal:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        journal_dir = insights_dir / "journal" / month
        journal_dir.mkdir(parents=True, exist_ok=True)
        journal_path = journal_dir / f"{today}.md"
        output_lines.append(f"Write the journal entry to: {journal_path}")

    prompt = f"""{instructions}

---

{global_context}

---

You are regenerating the insight summary for knowledge area: {display_path}
{files_text}{children_text}
{"The current summary is:" + chr(10) + existing_summary if existing_summary else "There is no existing summary yet."}

{chr(10).join(output_lines)}"""

    # Token estimate and guardrail warning
    estimated_tokens = len(prompt) // 3
    log.debug("Prompt for %s: ~%d tokens est., %d text files, %d binary files, %d child summaries",
              display_path, estimated_tokens,
              len([f for f in files if f.suffix.lower() in TEXT_EXTENSIONS]) if files else 0,
              1 if has_binary_files else 0,
              len(child_summaries))
    if estimated_tokens > 100_000:
        log.warning("Large prompt for %s: ~%d tokens estimated", display_path, estimated_tokens)

    return PromptResult(text=prompt, has_binary_files=has_binary_files)


_get_child_dirs = get_child_dirs


def _collect_child_summaries(
    root: Path, current_path: str, child_dirs: list[Path],
) -> dict[str, str]:
    """Read existing child summaries from insights/."""
    child_summaries: dict[str, str] = {}
    for child in child_dirs:
        child_rel = current_path + "/" + child.name if current_path else child.name
        child_summary_path = root / "insights" / child_rel / "summary.md"
        if child_summary_path.exists():
            child_summaries[child.name] = child_summary_path.read_text(encoding="utf-8")
    return child_summaries


def _compute_hash(
    child_dirs: list[Path],
    child_summaries: dict[str, str],
    knowledge_dir: Path,
    has_direct_files: bool,
) -> str:
    """Compute unified content hash for a folder.

    All inputs sorted for deterministic output across runs and platforms.
    """
    h = hashlib.sha256()
    for child in sorted(child_dirs, key=lambda d: d.name):
        h.update(b"dir:")
        h.update(child.name.encode("utf-8"))
    for name, content in sorted(child_summaries.items()):
        h.update(name.encode("utf-8"))
        h.update(content.encode("utf-8"))
    if has_direct_files:
        h.update(folder_content_hash(knowledge_dir).encode("utf-8"))
    return h.hexdigest()


def _snapshot_dir(directory: Path) -> set[str]:
    """Snapshot filenames in a directory (non-recursive)."""
    if not directory.is_dir():
        return set()
    return {p.name for p in directory.iterdir() if p.is_file()}


async def regen_path(
    root: Path,
    knowledge_rel_path: str,
    *,
    max_depth: int = 10,
    config: RegenConfig | None = None,
) -> int:
    """Run the deterministic incremental regen loop for a knowledge path.

    Starts at the given path, regenerates its summary, then walks up
    ancestors regenerating parent summaries until a summary is unchanged
    (content hash match or similarity guard).

    Returns the number of summaries regenerated.
    """
    if config is None:
        config = RegenConfig.load()

    regen_id = uuid4().hex[:6]
    similarity_threshold = config.similarity_threshold
    regen_count = 0
    current_path = knowledge_rel_path

    for _ in range(max_depth):
        knowledge_dir = root / "knowledge" / current_path if current_path else root / "knowledge"
        insights_dir = root / "insights" / current_path if current_path else root / "insights"

        # Guard: if knowledge dir doesn't exist, clean up stale insights and walk up
        if not knowledge_dir.is_dir():
            log.debug("[%s] Knowledge dir does not exist: %s", regen_id, knowledge_dir)
            if insights_dir.is_dir():
                shutil.rmtree(insights_dir)
                log.info("[%s] Cleaned up stale insights for %s", regen_id, current_path)
            delete_insight_state(root, current_path)
            if not current_path:
                break
            parts = current_path.rsplit("/", 1)
            current_path = parts[0] if len(parts) > 1 else ""
            continue

        # Collect inputs
        child_dirs = _get_child_dirs(knowledge_dir)
        has_direct_files = any(_is_readable_file(p) for p in knowledge_dir.iterdir())

        # Cleanup: no readable files and no child dirs → remove stale insights
        if not has_direct_files and not child_dirs:
            log.debug("[%s] No readable files or child dirs in %s, cleaning up", regen_id, current_path or "(root)")
            if insights_dir.is_dir():
                shutil.rmtree(insights_dir)
                log.info("[%s] Cleaned up stale insights for %s", regen_id, current_path or "(root)")
            delete_insight_state(root, current_path)
            if not current_path:
                break
            parts = current_path.rsplit("/", 1)
            current_path = parts[0] if len(parts) > 1 else ""
            continue

        # Load current insight state
        istate = load_insight_state(root, current_path)

        # Collect child summaries and compute unified hash
        child_summaries = _collect_child_summaries(root, current_path, child_dirs)

        if not child_summaries and not has_direct_files:
            log.debug("[%s] No child summaries or direct content for %s, skipping", regen_id, current_path or "(root)")
            break

        new_hash = _compute_hash(child_dirs, child_summaries, knowledge_dir, has_direct_files)

        if istate and istate.content_hash == new_hash:
            log.debug("[%s] Content hash unchanged for %s, stopping (hash=%s)",
                      regen_id, current_path or "(root)", new_hash[:12])
            break

        log.debug("[%s] Content hash changed for %s: %s -> %s",
                  regen_id, current_path or "(root)",
                  (istate.content_hash[:12] if istate and istate.content_hash else "none"),
                  new_hash[:12])

        # Build prompt
        prompt_result = _build_prompt(
            current_path, knowledge_dir, child_summaries, insights_dir, root,
            write_journal=config.write_journal,
        )

        # Determine allowed tools
        allowed_tools = "Read,Write" if prompt_result.has_binary_files else "Write"
        log.debug("[%s] Allowed tools for %s: %s", regen_id, current_path or "(root)", allowed_tools)

        # Prompt fingerprint for forensic tracing
        prompt_hash = hashlib.sha1(prompt_result.text.encode("utf-8")).hexdigest()[:8]

        # Read old summary for similarity check
        summary_path = insights_dir / "summary.md"
        old_summary = ""
        if summary_path.exists():
            old_summary = summary_path.read_text(encoding="utf-8")

        # Snapshot insights dir before invocation (for output validation)
        insights_dir.mkdir(parents=True, exist_ok=True)
        pre_snapshot = _snapshot_dir(insights_dir)

        # Mark as running — keep old hash so crashes/failures don't block retries
        started = datetime.now(timezone.utc).isoformat()
        save_insight_state(root, InsightState(
            knowledge_path=current_path,
            content_hash=istate.content_hash if istate else None,
            summary_hash=istate.summary_hash if istate else None,
            regen_started_utc=started,
            last_regen_utc=istate.last_regen_utc if istate else None,
            regen_status="running",
            retry_count=istate.retry_count if istate else 0,
            model=config.model,
        ))

        # Invoke Claude
        log.info("[%s] Generating insights: %s (model=%s prompt_hash=%s)",
                 regen_id, current_path or "(root)", config.model, prompt_hash)
        result = await invoke_claude(
            prompt_result.text, cwd=root, timeout=config.timeout, model=config.model,
            effort=config.effort, max_turns=config.max_turns,
            allowed_tools=allowed_tools,
        )
        now = datetime.now(timezone.utc).isoformat()

        # Output validation: check for unexpected files
        post_snapshot = _snapshot_dir(insights_dir)
        unexpected = post_snapshot - pre_snapshot - {"summary.md"}
        # Allow journal directory (it's a dir, not in snapshot) and journal files
        if config.write_journal:
            unexpected -= {"journal"}
        if unexpected:
            log.warning("[%s] Unexpected files created by agent in %s: %s — removing",
                        regen_id, current_path or "(root)", unexpected)
            for name in unexpected:
                rogue = insights_dir / name
                if rogue.is_file():
                    rogue.unlink()
                elif rogue.is_dir():
                    shutil.rmtree(rogue)

        if not result.success:
            save_insight_state(root, InsightState(
                knowledge_path=current_path,
                content_hash=istate.content_hash if istate else None,
                summary_hash=istate.summary_hash if istate else None,
                regen_started_utc=started,
                last_regen_utc=now,
                regen_status="failed",
                retry_count=(istate.retry_count if istate else 0) + 1,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                num_turns=result.num_turns,
                model=config.model,
            ))
            log.warning("[%s] Claude CLI failed for %s", regen_id, current_path or "(root)")
            break

        # Check if summary was actually written by Claude
        if summary_path.exists():
            new_summary = summary_path.read_text(encoding="utf-8")
        else:
            log.warning("[%s] Claude did not write summary for %s. Output: %s",
                        regen_id, current_path or "(root)", result.output[:500])
            save_insight_state(root, InsightState(
                knowledge_path=current_path,
                content_hash=istate.content_hash if istate else None,
                summary_hash=istate.summary_hash if istate else None,
                regen_started_utc=started,
                last_regen_utc=now,
                regen_status="failed",
                retry_count=(istate.retry_count if istate else 0) + 1,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                num_turns=result.num_turns,
                model=config.model,
            ))
            break

        # Similarity guard
        if old_summary and text_similarity(old_summary, new_summary) > similarity_threshold:
            log.info("[%s] Summary for %s is >%.0f%% similar, discarding rewrite",
                     regen_id, current_path or "(root)", similarity_threshold * 100)
            # Restore old summary
            summary_path.write_text(old_summary, encoding="utf-8")
            summary_hash = hashlib.sha256(old_summary.encode("utf-8")).hexdigest()
            save_insight_state(root, InsightState(
                knowledge_path=current_path,
                content_hash=new_hash,
                summary_hash=summary_hash,
                regen_started_utc=started,
                last_regen_utc=now,
                regen_status="idle",
                retry_count=0,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                num_turns=result.num_turns,
                model=config.model,
            ))
            # Summary unchanged → stop walking up
            break

        # Summary changed — update state
        summary_hash = hashlib.sha256(new_summary.encode("utf-8")).hexdigest()
        save_insight_state(root, InsightState(
            knowledge_path=current_path,
            content_hash=new_hash,
            summary_hash=summary_hash,
            regen_started_utc=started,
            last_regen_utc=now,
            regen_status="idle",
            retry_count=0,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            num_turns=result.num_turns,
            model=config.model,
        ))
        regen_count += 1
        log.info("[%s] Regenerated summary for %s (model=%s in=%s out=%s tokens turns=%s)",
                 regen_id, current_path or "(root)", config.model,
                 result.input_tokens, result.output_tokens, result.num_turns)

        # Walk up to parent (or break if at root)
        if not current_path:
            break
        parts = current_path.rsplit("/", 1)
        current_path = parts[0] if len(parts) > 1 else ""

    return regen_count


_find_all_content_paths = find_all_content_paths


async def regen_all(root: Path, *, config: RegenConfig | None = None) -> int:
    """Regenerate insights for all knowledge paths (bottom-up)."""
    if config is None:
        config = RegenConfig.load()

    # Reset orphaned 'running' states from crashed/killed runs
    reset_count = reset_running_insight_states(root)
    if reset_count:
        log.info("Reset %d orphaned 'running' insight states to 'idle'", reset_count)

    knowledge_root = root / "knowledge"
    content_paths = _find_all_content_paths(knowledge_root)

    if not content_paths:
        log.info("No knowledge paths found")
        return 0

    log.info("Found %d knowledge paths to regenerate", len(content_paths))
    total = 0
    for path in content_paths:
        log.info("Assessing insights generation: %s", path)
        count = await regen_path(root, path, config=config)
        total += count

    return total

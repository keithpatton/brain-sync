"""Insight regeneration engine.

Deterministic incremental recomputation loop (Make/Bazel model):
- Every folder is treated identically: summary = readable files + child summaries
- Loop walks up ancestors, stops when summary hash is unchanged
- Similarity guard prevents trivial LLM rewording (>0.97 → discard)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from importlib import resources
from pathlib import Path

from brain_sync.state import (
    InsightState,
    delete_insight_state,
    load_insight_state,
    reset_running_insight_states,
    save_insight_state,
)


def _load_template(name: str) -> str:
    """Load a template file bundled with the package."""
    ref = resources.files("brain_sync.templates").joinpath(name)
    return ref.read_text(encoding="utf-8")


# Loaded once at import time — embedded into every insights agent prompt
_INSTRUCTIONS = _load_template("INSTRUCTIONS.md")
_INSIGHT_INSTRUCTIONS = _load_template("INSIGHT_INSTRUCTIONS.md")

log = logging.getLogger(__name__)

SIMILARITY_THRESHOLD = 0.97
CLAUDE_TIMEOUT = 300  # seconds
CONFIG_FILE = Path.home() / ".brain-sync" / "config.json"

# File types that Claude CLI can meaningfully read
READABLE_EXTENSIONS = {".md", ".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg"}


def _is_readable_file(p: Path) -> bool:
    """Check if a file has a readable extension and is not hidden."""
    return p.is_file() and p.suffix.lower() in READABLE_EXTENSIONS and not p.name.startswith(("_", "."))


@dataclass
class RegenConfig:
    """Configuration for the insights agent."""
    model: str = "claude-sonnet-4-6"
    effort: str = "medium"  # low, medium, high — controls thinking budget
    timeout: int = CLAUDE_TIMEOUT
    max_turns: int = 50
    similarity_threshold: float = SIMILARITY_THRESHOLD

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
                effort=regen.get("effort", "medium"),
                timeout=regen.get("timeout", CLAUDE_TIMEOUT),
                max_turns=regen.get("max_turns", 50),
                similarity_threshold=regen.get("similarity_threshold", SIMILARITY_THRESHOLD),
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


async def invoke_claude(
    prompt: str,
    cwd: Path,
    timeout: int = CLAUDE_TIMEOUT,
    model: str = "",
    effort: str = "",
    max_turns: int = 50,
) -> ClaudeResult:
    """Invoke Claude CLI in non-interactive mode."""
    import os
    import tempfile

    cmd = [
        "claude", "--print",
        "--output-format", "json",
        "--dangerously-skip-permissions",
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Glob",
    ]
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])

    # Write prompt to temp file to avoid Windows command-line length limits
    # (WinError 206). Claude CLI reads the file via its Read tool.
    fd, prompt_path = tempfile.mkstemp(suffix=".md", prefix="brain-sync-prompt-")
    try:
        os.write(fd, prompt.encode("utf-8"))
        os.close(fd)
        cmd.extend(["-p", f"Read and follow the instructions in {prompt_path}"])

        env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
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
            log.info("Claude CLI: tokens=%s/%s turns=%s duration=%ss",
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
    finally:
        os.unlink(prompt_path)


def _build_prompt(
    knowledge_path: str,
    knowledge_dir: Path,
    child_summaries: dict[str, str],
    insights_dir: Path,
) -> str:
    """Build the prompt for regenerating an insight summary.

    Unified prompt — includes direct files and/or child summaries as available.
    """
    # Direct files section — inline text files, tell Claude to Read binary ones
    files_text = ""
    files = sorted(p for p in knowledge_dir.iterdir() if _is_readable_file(p))
    if files:
        TEXT_EXTENSIONS = {".md", ".txt"}
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

        parts = []
        if inlined_parts:
            parts.append("The knowledge folder contains these files:\n" + "\n\n".join(inlined_parts))
        if binary_files:
            file_list = "\n".join(f"- {p.name}" for p in binary_files)
            parts.append(f"Read these files (binary/non-text) from {knowledge_dir}:\n{file_list}")
        files_text = "\n\n".join(parts) + "\n" if parts else ""

    # Child summaries section
    children_text = ""
    if child_summaries:
        parts = []
        for name, content in sorted(child_summaries.items()):
            parts.append(f"\n### {name}\n{content}")
        children_text = f"""
This area has the following sub-areas with their own summaries:
{"".join(parts)}
"""

    existing_summary = ""
    summary_path = insights_dir / "summary.md"
    if summary_path.exists():
        existing_summary = summary_path.read_text(encoding="utf-8")

    display_path = knowledge_path or "(root)"

    return f"""{_INSIGHT_INSTRUCTIONS}

---

{_INSTRUCTIONS}

---

You are regenerating the insight summary for knowledge area: {display_path}
{files_text}{children_text}
{"The current summary is:" + chr(10) + existing_summary if existing_summary else "There is no existing summary yet."}

Write the summary to: {insights_dir / "summary.md"}"""


def _get_child_dirs(knowledge_dir: Path) -> list[Path]:
    """Get child directories, excluding _ and . prefixed dirs."""
    if not knowledge_dir.is_dir():
        return []
    return sorted(
        p for p in knowledge_dir.iterdir()
        if p.is_dir() and not p.name.startswith(("_", "."))
    )


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

    similarity_threshold = config.similarity_threshold
    regen_count = 0
    current_path = knowledge_rel_path

    for _ in range(max_depth):
        knowledge_dir = root / "knowledge" / current_path if current_path else root / "knowledge"
        insights_dir = root / "insights" / current_path if current_path else root / "insights"

        # Guard: if knowledge dir doesn't exist, clean up stale insights and walk up
        if not knowledge_dir.is_dir():
            log.debug("Knowledge dir does not exist: %s", knowledge_dir)
            if insights_dir.is_dir():
                shutil.rmtree(insights_dir)
                log.info("Cleaned up stale insights for %s", current_path)
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
            log.debug("No readable files or child dirs in %s, cleaning up", current_path or "(root)")
            if insights_dir.is_dir():
                shutil.rmtree(insights_dir)
                log.info("Cleaned up stale insights for %s", current_path or "(root)")
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
            log.debug("No child summaries or direct content for %s, skipping", current_path or "(root)")
            break

        new_hash = _compute_hash(child_dirs, child_summaries, knowledge_dir, has_direct_files)

        if istate and istate.content_hash == new_hash:
            log.debug("Content hash unchanged for %s, stopping", current_path or "(root)")
            break

        # Build prompt
        prompt = _build_prompt(current_path, knowledge_dir, child_summaries, insights_dir)

        # Read old summary for similarity check
        summary_path = insights_dir / "summary.md"
        old_summary = ""
        if summary_path.exists():
            old_summary = summary_path.read_text(encoding="utf-8")

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
        log.info("Generating insights: %s", current_path or "(root)")
        result = await invoke_claude(
            prompt, cwd=root, timeout=config.timeout, model=config.model,
            effort=config.effort, max_turns=config.max_turns,
        )
        now = datetime.now(timezone.utc).isoformat()

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
            log.warning("Claude CLI failed for %s", current_path or "(root)")
            break

        # Check if summary was actually written by Claude
        if summary_path.exists():
            new_summary = summary_path.read_text(encoding="utf-8")
        else:
            log.warning("Claude did not write summary for %s. Output: %s", current_path or "(root)", result.output[:500])
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
            log.info("Summary for %s is >%.0f%% similar, discarding rewrite",
                     current_path or "(root)", similarity_threshold * 100)
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
        log.info("Regenerated summary for %s (in=%s, out=%s tokens)",
                 current_path or "(root)", result.input_tokens, result.output_tokens)

        # Walk up to parent (or break if at root)
        if not current_path:
            break
        parts = current_path.rsplit("/", 1)
        current_path = parts[0] if len(parts) > 1 else ""

    return regen_count


def _find_all_content_paths(knowledge_root: Path) -> list[str]:
    """Find all knowledge paths bottom-up (deepest first).

    Walks the tree, collects all folders that have readable files or
    child content dirs, sorted deepest-first so that regen_all processes
    leaves before parents.
    """
    paths: list[str] = []

    def _walk(directory: Path, prefix: str) -> None:
        if not directory.is_dir():
            return
        for child in sorted(directory.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            child_rel = prefix + "/" + child.name if prefix else child.name
            # Recurse first (depth-first → deepest paths added first)
            _walk(child, child_rel)
            # Include this folder if it has readable files or content child dirs
            has_files = any(_is_readable_file(p) for p in child.iterdir())
            has_children = any(
                p.is_dir() and not p.name.startswith(("_", "."))
                for p in child.iterdir()
            )
            if has_files or has_children:
                paths.append(child_rel)

    _walk(knowledge_root, "")
    return paths


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

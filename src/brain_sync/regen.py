"""Insight regeneration engine.

Deterministic incremental recomputation loop (Make/Bazel model):
- Leaf summaries read raw knowledge (*.md files)
- Parent summaries read child summaries only
- Loop walks up ancestors, stops when summary hash is unchanged
- Similarity guard prevents trivial LLM rewording (>0.97 → discard)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from importlib import resources
from pathlib import Path

from brain_sync.state import (
    InsightState,
    load_insight_state,
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


@dataclass
class RegenConfig:
    """Configuration for the insights agent."""
    model: str = "claude-opus-4-6"
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
                model=regen.get("model", "claude-opus-4-6"),
                effort=regen.get("effort", "medium"),
                timeout=regen.get("timeout", CLAUDE_TIMEOUT),
                max_turns=regen.get("max_turns", 10),
                similarity_threshold=regen.get("similarity_threshold", SIMILARITY_THRESHOLD),
            )
        except (json.JSONDecodeError, OSError):
            return cls()


def folder_content_hash(folder: Path) -> str:
    """Compute sha256 of all *.md files in a folder (excluding _sync-context/).

    Files are sorted by name for determinism. Returns hex digest.
    """
    h = hashlib.sha256()
    md_files = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix == ".md"
    )
    for p in md_files:
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
    cmd = [
        "claude", "--print",
        "--dangerously-skip-permissions",
        "--max-turns", str(max_turns),
        "--allowedTools", "Read,Write,Glob",
    ]
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--effort", effort])
    cmd.extend(["-p", prompt])

    import os
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

    # Log stderr (contains usage stats from Claude CLI)
    if stderr_text:
        for line in stderr_text.splitlines():
            log.info("Claude CLI: %s", line)

    input_tokens, output_tokens = _parse_token_counts(stderr_text)

    if proc.returncode != 0:
        log.warning("Claude CLI failed (rc=%d): %s", proc.returncode, stderr_text[:500])
        return ClaudeResult(
            success=False, output="",
            input_tokens=input_tokens, output_tokens=output_tokens,
        )

    log.debug("Claude CLI output (%d chars): %s", len(stdout_text), stdout_text[:200])
    return ClaudeResult(
        success=True, output=stdout_text,
        input_tokens=input_tokens, output_tokens=output_tokens,
    )


def _build_leaf_prompt(knowledge_path: str, knowledge_dir: Path, insights_dir: Path) -> str:
    """Build the prompt for regenerating a leaf-level insight summary."""
    md_files = sorted(
        p for p in knowledge_dir.iterdir()
        if p.is_file() and p.suffix == ".md"
    )
    file_list = "\n".join(f"- {p.name}" for p in md_files)

    existing_summary = ""
    summary_path = insights_dir / "summary.md"
    if summary_path.exists():
        existing_summary = summary_path.read_text(encoding="utf-8")

    return f"""{_INSIGHT_INSTRUCTIONS}

---

{_INSTRUCTIONS}

---

You are performing a LEAF regeneration for knowledge area: {knowledge_path}

The knowledge folder contains these markdown files:
{file_list}

Read all the markdown files in: {knowledge_dir}

{"The current summary is:" + chr(10) + existing_summary if existing_summary else "There is no existing summary yet."}

Write the summary to: {insights_dir / "summary.md"}"""


def _build_parent_prompt(knowledge_path: str, child_summaries: dict[str, str], insights_dir: Path) -> str:
    """Build the prompt for regenerating a parent-level insight summary."""
    children_text = ""
    for name, content in sorted(child_summaries.items()):
        children_text += f"\n### {name}\n{content}\n"

    existing_summary = ""
    summary_path = insights_dir / "summary.md"
    if summary_path.exists():
        existing_summary = summary_path.read_text(encoding="utf-8")

    return f"""{_INSIGHT_INSTRUCTIONS}

---

{_INSTRUCTIONS}

---

You are performing a PARENT regeneration for knowledge area: {knowledge_path}

This area has the following sub-areas with their own summaries:
{children_text}

{"The current parent summary is:" + chr(10) + existing_summary if existing_summary else "There is no existing parent summary yet."}

Write the parent summary to: {insights_dir / "summary.md"}"""


def _knowledge_has_content(knowledge_dir: Path) -> bool:
    """Check if a knowledge directory has any .md files (excluding _sync-context)."""
    if not knowledge_dir.is_dir():
        return False
    for p in knowledge_dir.iterdir():
        if p.is_file() and p.suffix == ".md":
            return True
        if p.is_dir() and p.name != "_sync-context":
            # Has subdirectories with potential content
            return True
    return False


def _get_child_dirs(knowledge_dir: Path) -> list[Path]:
    """Get child directories that have content, excluding _sync-context."""
    if not knowledge_dir.is_dir():
        return []
    return sorted(
        p for p in knowledge_dir.iterdir()
        if p.is_dir() and p.name != "_sync-context"
    )


async def regen_path(
    root: Path,
    knowledge_rel_path: str,
    *,
    max_depth: int = 10,
    config: RegenConfig | None = None,
) -> int:
    """Run the deterministic incremental regen loop for a knowledge path.

    Starts at the leaf (knowledge_rel_path), regenerates its summary,
    then walks up ancestors regenerating parent summaries until a summary
    is unchanged (content hash match or similarity guard).

    Returns the number of summaries regenerated.
    """
    if config is None:
        config = RegenConfig.load()

    similarity_threshold = config.similarity_threshold
    regen_count = 0
    current_path = knowledge_rel_path

    for _ in range(max_depth):
        if not current_path:
            break

        knowledge_dir = root / "knowledge" / current_path
        insights_dir = root / "insights" / current_path

        if not knowledge_dir.is_dir():
            log.debug("Knowledge dir does not exist: %s", knowledge_dir)
            break

        # Load current insight state
        istate = load_insight_state(root, current_path)

        # Determine if this is a leaf or parent
        child_dirs = _get_child_dirs(knowledge_dir)
        has_direct_md = any(
            p.is_file() and p.suffix == ".md"
            for p in knowledge_dir.iterdir()
            if p.name != "_sync-context"
        )

        if child_dirs:
            # Parent: read child summaries
            child_summaries: dict[str, str] = {}
            for child in child_dirs:
                child_rel = current_path + "/" + child.name if current_path else child.name
                child_summary_path = root / "insights" / child_rel / "summary.md"
                if child_summary_path.exists():
                    child_summaries[child.name] = child_summary_path.read_text(encoding="utf-8")

            if not child_summaries and not has_direct_md:
                log.debug("No child summaries or direct content for %s, skipping", current_path)
                break

            # Compute content hash from child summaries + any direct md files
            h = hashlib.sha256()
            for name, content in sorted(child_summaries.items()):
                h.update(name.encode("utf-8"))
                h.update(content.encode("utf-8"))
            if has_direct_md:
                h.update(folder_content_hash(knowledge_dir).encode("utf-8"))
            new_hash = h.hexdigest()

            if istate and istate.content_hash == new_hash:
                log.debug("Content hash unchanged for %s, stopping", current_path)
                break

            prompt = _build_parent_prompt(current_path, child_summaries, insights_dir)
        else:
            # Leaf: read raw knowledge
            if not has_direct_md:
                log.debug("No md files in leaf %s, skipping", current_path)
                break

            new_hash = folder_content_hash(knowledge_dir)

            if istate and istate.content_hash == new_hash:
                log.debug("Content hash unchanged for %s, stopping", current_path)
                break

            prompt = _build_leaf_prompt(current_path, knowledge_dir, insights_dir)

        # Read old summary for similarity check
        summary_path = insights_dir / "summary.md"
        old_summary = ""
        if summary_path.exists():
            old_summary = summary_path.read_text(encoding="utf-8")

        # Mark as running
        started = datetime.now(timezone.utc).isoformat()
        save_insight_state(root, InsightState(
            knowledge_path=current_path,
            content_hash=new_hash,
            summary_hash=istate.summary_hash if istate else None,
            regen_started_utc=started,
            last_regen_utc=istate.last_regen_utc if istate else None,
            regen_status="running",
            retry_count=istate.retry_count if istate else 0,
        ))

        # Invoke Claude
        log.info("Regenerating insights for: %s", current_path)
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
            ))
            log.warning("Claude CLI failed for %s", current_path)
            break

        # Check if summary was actually written by Claude
        if summary_path.exists():
            new_summary = summary_path.read_text(encoding="utf-8")
        else:
            log.warning("Claude did not write summary for %s. Output: %s", current_path, result.output[:500])
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
            ))
            break

        # Similarity guard
        if old_summary and text_similarity(old_summary, new_summary) > similarity_threshold:
            log.info("Summary for %s is >%.0f%% similar, discarding rewrite",
                     current_path, similarity_threshold * 100)
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
        ))
        regen_count += 1
        log.info("Regenerated summary for %s (in=%s, out=%s tokens)",
                 current_path, result.input_tokens, result.output_tokens)

        # Walk up to parent
        parts = current_path.rsplit("/", 1)
        if len(parts) == 1:
            # Already at top level, try root
            current_path = ""
        else:
            current_path = parts[0]

        # If we've reached the root knowledge level, stop
        if current_path == "":
            # Regenerate root-level summary if there are child dirs
            root_knowledge = root / "knowledge"
            root_insights = root / "insights"
            root_child_dirs = _get_child_dirs(root_knowledge)
            if root_child_dirs:
                root_child_summaries: dict[str, str] = {}
                for child in root_child_dirs:
                    child_summary_path = root_insights / child.name / "summary.md"
                    if child_summary_path.exists():
                        root_child_summaries[child.name] = child_summary_path.read_text(encoding="utf-8")

                if root_child_summaries:
                    # Check hash
                    rh = hashlib.sha256()
                    for name, content in sorted(root_child_summaries.items()):
                        rh.update(name.encode("utf-8"))
                        rh.update(content.encode("utf-8"))
                    root_hash = rh.hexdigest()

                    root_istate = load_insight_state(root, "")
                    if root_istate and root_istate.content_hash == root_hash:
                        break

                    # Regenerate root summary
                    root_prompt = _build_parent_prompt("(root)", root_child_summaries, root_insights)
                    root_summary_path = root_insights / "summary.md"
                    old_root_summary = ""
                    if root_summary_path.exists():
                        old_root_summary = root_summary_path.read_text(encoding="utf-8")

                    root_started = datetime.now(timezone.utc).isoformat()
                    save_insight_state(root, InsightState(
                        knowledge_path="",
                        content_hash=root_hash,
                        regen_started_utc=root_started,
                        regen_status="running",
                    ))

                    root_result = await invoke_claude(
                        root_prompt, cwd=root, timeout=config.timeout,
                        model=config.model, effort=config.effort, max_turns=config.max_turns,
                    )
                    if root_result.success and root_summary_path.exists():
                        new_root_summary = root_summary_path.read_text(encoding="utf-8")
                        if old_root_summary and text_similarity(old_root_summary, new_root_summary) > similarity_threshold:
                            root_summary_path.write_text(old_root_summary, encoding="utf-8")
                        else:
                            regen_count += 1

                    save_insight_state(root, InsightState(
                        knowledge_path="",
                        content_hash=root_hash,
                        summary_hash=hashlib.sha256(
                            (root_summary_path.read_text(encoding="utf-8") if root_summary_path.exists() else "").encode()
                        ).hexdigest(),
                        regen_started_utc=root_started,
                        last_regen_utc=datetime.now(timezone.utc).isoformat(),
                        regen_status="idle",
                        input_tokens=root_result.input_tokens,
                        output_tokens=root_result.output_tokens,
                    ))
            break

    return regen_count


def _find_leaf_paths(knowledge_root: Path, prefix: str = "") -> list[str]:
    """Find all leaf knowledge paths (folders with .md files but no child content dirs)."""
    leaves: list[str] = []
    if not knowledge_root.is_dir():
        return leaves

    for child in sorted(knowledge_root.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        child_rel = prefix + "/" + child.name if prefix else child.name
        grandchildren = _get_child_dirs(child)
        has_md = any(p.is_file() and p.suffix == ".md" for p in child.iterdir())

        if grandchildren:
            # Recurse into children
            leaves.extend(_find_leaf_paths(child, child_rel))
        elif has_md:
            leaves.append(child_rel)

    return leaves


async def regen_all(root: Path, *, config: RegenConfig | None = None) -> int:
    """Regenerate insights for all leaf knowledge paths."""
    if config is None:
        config = RegenConfig.load()

    knowledge_root = root / "knowledge"
    leaves = _find_leaf_paths(knowledge_root)

    if not leaves:
        log.info("No leaf knowledge paths found")
        return 0

    log.info("Found %d leaf knowledge paths to regenerate", len(leaves))
    total = 0
    for leaf in leaves:
        log.info("Regenerating: %s", leaf)
        count = await regen_path(root, leaf, config=config)
        total += count

    return total

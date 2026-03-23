"""Claude CLI backend — subprocess invocation via ``claude --print``.

Extracted from ``regen.invoke_claude()``.  Handles NDJSON stream parsing,
env filtering, timeout management, and stderr logging.

Prompt capture: when ``BRAIN_SYNC_CAPTURE_PROMPTS`` is set to a directory
path, each prompt is written to ``{dir}/{timestamp}_{hash}.prompt.txt``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from brain_sync.llm.base import BackendCapabilities, LlmResult, capabilities_for_model, with_backend_traits

log = logging.getLogger(__name__)

CLAUDE_TIMEOUT = 300


# ---------------------------------------------------------------------------
# Stream-JSON parsing
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


def _parse_token_counts(stderr_text: str) -> tuple[int | None, int | None]:
    """Parse token counts from Claude CLI stderr output (fallback)."""
    input_tokens = None
    output_tokens = None

    m = re.search(r"[Ii]nput.?tokens[:\s]+(\d[\d,]*)", stderr_text)
    if m:
        input_tokens = int(m.group(1).replace(",", ""))
    m = re.search(r"[Oo]utput.?tokens[:\s]+(\d[\d,]*)", stderr_text)
    if m:
        output_tokens = int(m.group(1).replace(",", ""))

    return input_tokens, output_tokens


# ---------------------------------------------------------------------------
# Prompt capture
# ---------------------------------------------------------------------------


def _capture_prompt(prompt: str) -> None:
    """Write prompt to capture directory if BRAIN_SYNC_CAPTURE_PROMPTS is set."""
    capture_dir = os.environ.get("BRAIN_SYNC_CAPTURE_PROMPTS")
    if not capture_dir:
        return
    try:
        d = Path(capture_dir)
        d.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha256(prompt.encode()).hexdigest()[:12]
        ts = time.strftime("%Y%m%d_%H%M%S")
        (d / f"{ts}_{h}.prompt.txt").write_text(prompt, encoding="utf-8")
    except OSError:
        log.debug("Failed to capture prompt", exc_info=True)


# ---------------------------------------------------------------------------
# Claude CLI backend
# ---------------------------------------------------------------------------


class ClaudeCliBackend:
    """LLM backend that invokes the Claude CLI as a subprocess."""

    def get_capabilities(self, *, model: str = "") -> BackendCapabilities:
        return with_backend_traits(
            capabilities_for_model(model),
            max_concurrency=1,
            structured_output_reliability="strict",
            startup_overhead_class="high",
        )

    async def invoke(
        self,
        prompt: str,
        cwd: Path,
        timeout: int = CLAUDE_TIMEOUT,
        model: str = "",
        effort: str = "",
        max_turns: int = 6,
        system_prompt: str | None = None,
        tools: str | None = None,
        is_chunk: bool = False,
    ) -> LlmResult:
        """Invoke Claude CLI in non-interactive mode.

        Prompt is delivered via stdin.  When *system_prompt* and *tools*
        are set, the CLI's heavy agent system prompt is replaced with a
        minimal directive, turning it into a thin inference wrapper.
        """
        _capture_prompt(prompt)
        t0 = time.monotonic()

        cmd = [
            "claude",
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--no-session-persistence",
            "--max-turns",
            str(max_turns),
        ]
        if system_prompt is not None:
            cmd.extend(["--system-prompt", system_prompt])
        if tools is not None:
            cmd.extend(["--tools", tools])
        else:
            # Legacy path: full agent mode with tool permissions
            cmd.extend(["--dangerously-skip-permissions", "--disable-slash-commands"])
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
        except TimeoutError:
            proc.kill()
            await proc.communicate()
            log.warning("Claude CLI timed out after %ds", timeout)
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            return LlmResult(success=False, output="", duration_ms=elapsed_ms, prompt_text=prompt)
        except BaseException:
            proc.kill()
            await proc.communicate()
            raise

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        stdout_text = stdout.decode("utf-8", errors="replace")

        if stderr_text:
            for line in stderr_text.splitlines():
                log.info("Claude CLI: %s", line)

        if proc.returncode != 0:
            log.warning("Claude CLI failed (rc=%d) stderr: %s", proc.returncode, stderr_text[:500])
            if stdout_text.strip():
                log.warning("Claude CLI failed stdout: %s", stdout_text[:1000])
            return LlmResult(success=False, output="", duration_ms=elapsed_ms, prompt_text=prompt)

        # Parse stream-json NDJSON output
        input_tokens = None
        output_tokens = None
        num_turns = None
        result_text = stdout_text
        try:
            parsed = _parse_stream_json(stdout_text)
            result_text = parsed.text or stdout_text
            input_tokens = parsed.input_tokens
            output_tokens = parsed.output_tokens
            num_turns = parsed.num_turns
            log.info(
                "Claude CLI: model=%s tokens=%s/%s turns=%s wall=%ss",
                model or "default",
                input_tokens,
                output_tokens,
                num_turns,
                f"{elapsed_ms / 1000:.1f}",
            )
            if parsed.is_error:
                log.warning("Claude CLI error subtype: %s", parsed.error_subtype)
                return LlmResult(
                    success=False,
                    output=result_text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    num_turns=num_turns,
                    duration_ms=elapsed_ms,
                    prompt_text=prompt,
                )
        except Exception:
            log.warning("Stream-JSON parsing failed, attempting text-only extraction")
            input_tokens, output_tokens = _parse_token_counts(stderr_text)
            # Lightweight fallback: extract assistant text
            fallback_parts: list[str] = []
            for line in stdout_text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if event.get("type") == "assistant":
                    for block in event.get("message", {}).get("content", []):
                        if block.get("type") == "text":
                            fallback_parts.append(block.get("text", ""))
            if fallback_parts:
                result_text = "".join(fallback_parts)
                log.info("Recovered assistant text from NDJSON fallback (%d chars)", len(result_text))
            else:
                log.warning("Could not extract assistant text from NDJSON, failing invocation")
                return LlmResult(success=False, output="", duration_ms=elapsed_ms, prompt_text=prompt)

        return LlmResult(
            success=True,
            output=result_text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            num_turns=num_turns,
            duration_ms=elapsed_ms,
            prompt_text=prompt,
        )

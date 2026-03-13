#!/usr/bin/env python3
"""Fake Claude CLI stub for E2E tests.

Reads BRAIN_SYNC_FAKE_LLM_MODE env var (default: stable).
Emits NDJSON matching the ``--output-format stream-json`` format.
Reads prompt from stdin.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sys


def main() -> None:
    prompt = sys.stdin.read()
    mode = os.environ.get("BRAIN_SYNC_FAKE_LLM_MODE", "stable")

    if mode == "fail":
        # Emit error result
        result_event = {
            "type": "result",
            "is_error": True,
            "subtype": "error",
            "num_turns": 0,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
        print(json.dumps(result_event))
        sys.exit(1)

    h = hashlib.sha256(prompt.encode()).hexdigest()[:8]
    rng = random.Random(int(h, 16))
    phrases = ["Key themes include", "Analysis reveals", "The core pattern is"]
    topics = ["cross-functional alignment", "iterative refinement", "knowledge consolidation"]
    text = f"# Summary\n\n[fake-{h}] {rng.choice(phrases)} {rng.choice(topics)}."

    input_tokens = len(prompt) // 4
    output_tokens = len(text) // 4

    # Emit assistant event
    assistant_event = {
        "type": "assistant",
        "message": {
            "content": [{"type": "text", "text": text}],
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        },
    }
    print(json.dumps(assistant_event))

    # Emit result event
    result_event = {
        "type": "result",
        "is_error": False,
        "num_turns": 1,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        },
    }
    print(json.dumps(result_event))


if __name__ == "__main__":
    main()
